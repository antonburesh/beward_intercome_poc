"""Local HTTP routes: page, call control, microphone, snapshot, door, faces, and keys."""

import json
import re
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from phone import config
from phone.door import delete_all_faces, delete_face, fetch_face, fetch_snapshot, list_faces, open_door, upload_faces
from phone.page import PAGE

PHONE = None
WEBRTC = None
GUESTS = None
KEYS = None
_FACE_CACHE = {"at": 0.0, "rows": []}
_KEY_CACHE = {"at": 0.0, "rows": []}


def multipart_parts(content_type, body):
    """Read multipart fields into memory. Nothing is written to disk."""
    match = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not match:
        return {}
    marker = b"--" + match.group(1).encode()
    parts = {}
    for chunk in body.split(marker):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        if chunk.endswith(b"--"):
            chunk = chunk[:-2].strip(b"\r\n")
        head, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        header = head.decode("utf-8", "replace")
        name = re.search(r'name="([^"]+)"', header)
        if not name:
            continue
        filename = re.search(r'filename="([^"]*)"', header)
        parts[name.group(1)] = {
            "filename": filename.group(1) if filename else "",
            "data": data,
        }
    return parts


def face_rows():
    """Face list for the page. The panel is asked at most once every few seconds."""
    now = time.time()
    if now - _FACE_CACHE["at"] < 3:
        return _FACE_CACHE["rows"]
    rows = list_faces(config.PANELS)
    _FACE_CACHE["at"] = time.time()
    _FACE_CACHE["rows"] = rows
    return rows


def drop_face_cache():
    _FACE_CACHE["at"] = 0.0


def key_rows():
    """Keys entered on this phone. The panel is asked only when one is saved or removed."""
    now = time.time()
    if now - _KEY_CACHE["at"] < 3:
        return _KEY_CACHE["rows"]
    rows = KEYS.public() if KEYS else []
    _KEY_CACHE["at"] = time.time()
    _KEY_CACHE["rows"] = rows
    return rows


def drop_key_cache():
    _KEY_CACHE["at"] = 0.0


def panel_choices():
    """Names and addresses for the page. Login fields stay on the server."""
    return [
        {"name": str(item.get("name") or ""), "ip": str(item.get("ip") or "")}
        for item in config.PANELS
        if item
    ]


def guest_target(payload):
    """A panel ip, or all panels when the request asks for every door."""
    if isinstance(payload, dict) and payload.get("all") is True:
        return "all"
    panel = payload.get("panel") if isinstance(payload, dict) else None
    if panel in (None, "", "all"):
        return "all"
    return str(panel).strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/media"):
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            listener = PHONE.subscribe()
            try:
                while True:
                    self.wfile.write(listener.get(timeout=15))
                    self.wfile.flush()
            except Exception:
                PHONE.unsubscribe(listener)
                return
            return
        if self.path.startswith("/face"):
            params = parse_qs(urlparse(self.path).query)
            face_id = (params.get("id") or [""])[0]
            panel_ip = (params.get("panel") or [""])[0]
            panel = next((item for item in config.PANELS if item.get("ip") == panel_ip), None)
            image = fetch_face(panel, face_id) if panel else None
            if not image:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("Content-Length", str(len(image)))
            self.end_headers()
            self.wfile.write(image)
            return
        if self.path.startswith("/snapshot"):
            panel = PHONE.active_panel()
            if not panel:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            image = fetch_snapshot(panel)
            if not image:
                self.send_response(502)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(image)))
            self.end_headers()
            self.wfile.write(image)
            return
        if self.path.startswith("/api/state"):
            data = PHONE.snapshot()
            data["guests"] = GUESTS.public() if GUESTS else []
            data["faces"] = face_rows()
            data["keys"] = key_rows()
            data["panel_count"] = len(config.PANELS)
            data["panels"] = panel_choices()
            self.send_json(data)
            return
        if self.path in ("/", "/index.html"):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/webrtc":
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0 or length > 200000 or WEBRTC is None:
                self.send_response(400)
                self.end_headers()
                return
            offer = self.rfile.read(length).decode("utf-8", "replace")
            try:
                answer = WEBRTC.accept_offer_sync(offer)
            except Exception as exc:
                print(f"микрофон WebRTC не поднялся: {exc}", flush=True)
                self.send_response(500)
                self.end_headers()
                return
            body = answer.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/sdp")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/guest":
            length = int(self.headers.get("Content-Length", "0") or "0")
            if GUESTS is None or length <= 0 or length > 4000:
                self.send_json({"ok": False, "guest": "не удалось записать код"})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                self.send_json({"ok": False, "guest": "не удалось записать код"})
                return
            panels = list(config.PANELS)
            if payload.get("remove"):
                ok, message = GUESTS.revoke(panels, payload.get("apartment"))
            else:
                ok, message = GUESTS.issue(
                    panels,
                    payload.get("apartment"),
                    payload.get("minutes"),
                    guest_target(payload),
                )
            self.send_json({"ok": ok, "guest": message})
            return
        if self.path == "/api/guest/clear":
            if GUESTS is None:
                self.send_json({"ok": False, "guest": "не удалось снять коды"})
                return
            ok, message = GUESTS.revoke_all(list(config.PANELS))
            self.send_json({"ok": ok, "guest": message})
            return
        if self.path == "/api/face/delete":
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0 or length > 4000:
                self.send_json({"ok": False, "face": "не удалось удалить фото"})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                self.send_json({"ok": False, "face": "не удалось удалить фото"})
                return
            panels = list(config.PANELS)
            if payload.get("all"):
                ok, message = delete_all_faces(panels)
            else:
                ok, message = delete_face(panels, payload.get("panel"), payload.get("id"))
            drop_face_cache()
            self.send_json({"ok": ok, "face": message})
            return
        if self.path == "/api/key/clear":
            if KEYS is None:
                self.send_json({"ok": False, "key": "не удалось удалить ключи"})
                return
            ok, message = KEYS.remove_all(list(config.PANELS))
            drop_key_cache()
            self.send_json({"ok": ok, "key": message})
            return
        if self.path == "/api/key":
            length = int(self.headers.get("Content-Length", "0") or "0")
            if KEYS is None or length <= 0 or length > 4000:
                self.send_json({"ok": False, "key": "не удалось записать ключ"})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                self.send_json({"ok": False, "key": "не удалось записать ключ"})
                return
            panels = list(config.PANELS)
            if payload.get("remove"):
                ok, message = KEYS.remove(panels, payload.get("key"))
            else:
                ok, message = KEYS.add(panels, payload.get("apartment"), payload.get("key"))
            drop_key_cache()
            self.send_json({"ok": ok, "key": message})
            return
        if self.path == "/api/face":
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0 or length > 12 * 1024 * 1024:
                self.send_json({"ok": False, "face": "нужны квартира и фото"})
                return
            body = self.rfile.read(length)
            parts = multipart_parts(self.headers.get("Content-Type", ""), body)
            apartment = parts.get("apartment", {}).get("data", b"").decode("utf-8", "replace").strip()
            photo = parts.get("photo", {}).get("data", b"")
            ok, message = upload_faces(config.PANELS, apartment, photo)
            drop_face_cache()
            self.send_json({"ok": ok, "face": message})
            return
        if self.path == "/api/open":
            panel, message = PHONE.door_target()
            if not panel:
                self.send_json({"ok": False, "door": message})
                return
            ok, message = open_door(panel)
            self.send_json({"ok": ok, "door": message})
            return
        if self.path == "/api/answer":
            PHONE.answer()
        elif self.path == "/api/reject":
            PHONE.reject()
        elif self.path == "/api/hangup":
            PHONE.hangup()
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_json(PHONE.snapshot())
