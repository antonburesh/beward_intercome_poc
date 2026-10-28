"""Local HTTP routes: the Vue page, call control, microphone, snapshot, door, faces, and keys."""

import json
import re
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from phone import config
from phone.door import delete_all_faces, delete_face, fetch_face, fetch_snapshot, list_faces, open_door, upload_faces

_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".txt": "text/plain; charset=utf-8",
}


def content_type(suffix):
    return _TYPES.get(suffix.lower(), "application/octet-stream")


def static_target(path, dist):
    """A file inside dist, or index.html for an app route. None if it must 404."""
    dist = Path(dist).resolve()
    raw = unquote(urlparse(path).path)
    if raw != "/" and raw.endswith("/"):
        raw = raw[:-1] or "/"
    if "\\" in raw:
        return None
    rel = "" if raw == "/" else raw.lstrip("/")
    if any(part == ".." for part in Path(rel).parts):
        return None
    if rel:
        candidate = (dist / rel).resolve()
        try:
            candidate.relative_to(dist)
        except ValueError:
            return None
        if candidate.is_file():
            return candidate
        if Path(rel).suffix:
            return None
    index = dist / "index.html"
    return index if index.is_file() else None

PHONE = None
WEBRTC = None
GUESTS = None
KEYS = None
_FACE_CACHE = {"at": 0.0, "rows": []}


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


def panel_choices():
    """Names and addresses for the page. Login fields stay on the server."""
    return [
        {"name": str(item.get("name") or ""), "ip": str(item.get("ip") or "")}
        for item in config.PANELS
        if item
    ]


def call_payload(phone):
    """Call and registration only. Asking the panel here stalls the page."""
    raw = phone.snapshot()
    call = raw.get("call")
    if call:
        call = {
            "id": call.get("id"),
            "state": call.get("state"),
            "apartment": call.get("apartment"),
            "panel": call.get("panel") or None,
            "panel_known": bool(call.get("panel_known")),
            "from": call.get("from"),
            "to": call.get("to"),
            "params": call.get("params") or [],
            "headers": call.get("headers") or [],
            "rtp": call.get("rtp") or 0,
        }
    return {
        "registered": bool(raw.get("registered")),
        "error": raw.get("error") or "",
        "user": raw.get("user") or "",
        "server": raw.get("server") or "",
        "call": call,
    }


def call_event_key(payload):
    """What makes the page redraw. Packet counts are not a new call."""
    call = payload.get("call") or {}
    return (
        bool(payload.get("registered")),
        payload.get("error") or "",
        call.get("id") or "",
        call.get("state") or "",
        call.get("apartment") or "",
        bool(call.get("panel_known")),
        call.get("panel") or "",
    )


def book_payload():
    """Guests, keys, and panel names. These live on disk, not on the panel."""
    return {
        "guests": GUESTS.public() if GUESTS else [],
        "keys": KEYS.public() if KEYS else [],
        "panels": panel_choices(),
        "panel_count": len(config.PANELS),
    }


def guest_target(payload):
    """A panel ip, or all panels when the request asks for every door."""
    if not isinstance(payload, dict) or payload.get("all") is True:
        return "all"
    panel = payload.get("panel")
    if panel in (None, "", "all"):
        return "all"
    return str(panel).strip()


def read_json(handler, limit):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0 or length > limit:
        return None
    try:
        value = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


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

    def send_bytes(self, status, content_type, body, cache="no-store"):
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def fail(self, field, message):
        self.send_json({"ok": False, field: message})

    def stream_events(self):
        """One connection. The server writes when the call changes."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last = None
        try:
            while True:
                payload = call_payload(PHONE)
                key = call_event_key(payload)
                if key != last:
                    text = json.dumps(payload, ensure_ascii=False)
                    self.wfile.write(f"data: {text}\n\n".encode())
                    last = key
                else:
                    self.wfile.write(b":\n\n")
                self.wfile.flush()
                PHONE.wake.wait(3)
                PHONE.wake.clear()
        except Exception:
            return

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
                self.send_bytes(404, "", b"")
                return
            self.send_bytes(200, "image/jpeg", image, "private, no-store")
            return
        if self.path.startswith("/snapshot"):
            panel = PHONE.active_panel()
            image = fetch_snapshot(panel) if panel else None
            if not panel:
                self.send_bytes(404, "", b"")
                return
            if not image:
                self.send_bytes(502, "", b"")
                return
            self.send_bytes(200, "image/jpeg", image)
            return
        if self.path.startswith("/api/events"):
            self.stream_events()
            return
        if self.path.startswith("/api/state"):
            self.send_json(call_payload(PHONE))
            return
        if self.path.startswith("/api/book"):
            self.send_json(book_payload())
            return
        if self.path.startswith("/api/faces"):
            self.send_json({"faces": face_rows()})
            return
        target = static_target(self.path, _DIST)
        if target is not None:
            cache = "no-store" if target.name == "index.html" else "public, max-age=31536000, immutable"
            self.send_bytes(200, content_type(target.suffix), target.read_bytes(), cache)
            return
        if not (_DIST / "index.html").is_file() and not Path(urlparse(self.path).path).suffix:
            self.send_bytes(
                503,
                "text/plain; charset=utf-8",
                "Нет сборки страницы. В каталоге web выполните npm run build.\n".encode(),
            )
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
            self.send_bytes(200, "application/sdp", answer.encode())
            return
        if self.path == "/api/guest":
            payload = read_json(self, 4000)
            if GUESTS is None or payload is None:
                self.fail("guest", "не удалось записать код")
                return
            panels = list(config.PANELS)
            if payload.get("remove"):
                ok, message = GUESTS.revoke(panels, payload.get("apartment"))
            else:
                ok, message = GUESTS.issue(
                    panels, payload.get("apartment"), payload.get("minutes"), guest_target(payload)
                )
            self.send_json({"ok": ok, "guest": message})
            return
        if self.path == "/api/guest/clear":
            if GUESTS is None:
                self.fail("guest", "не удалось снять коды")
                return
            ok, message = GUESTS.revoke_all(list(config.PANELS))
            self.send_json({"ok": ok, "guest": message})
            return
        if self.path == "/api/face/delete":
            payload = read_json(self, 4000)
            if payload is None:
                self.fail("face", "не удалось удалить фото")
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
                self.fail("key", "не удалось удалить ключи")
                return
            ok, message = KEYS.remove_all(list(config.PANELS))
            self.send_json({"ok": ok, "key": message})
            return
        if self.path == "/api/key":
            payload = read_json(self, 4000)
            if KEYS is None or payload is None:
                self.fail("key", "не удалось записать ключ")
                return
            panels = list(config.PANELS)
            if payload.get("remove"):
                ok, message = KEYS.remove(panels, payload.get("key"))
            else:
                ok, message = KEYS.add(panels, payload.get("apartment"), payload.get("key"))
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
