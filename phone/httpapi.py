"""Local HTTP routes: page, call control, microphone, snapshot, door, and face upload."""

import json
import re
from http.server import BaseHTTPRequestHandler

from phone import config
from phone.door import fetch_snapshot, open_door, upload_face
from phone.page import PAGE

PHONE = None
WEBRTC = None


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


def face_panel():
    """The door panel from settings. Prefer the known Beward address."""
    for panel in config.PANELS:
        if panel.get("ip") == "192.168.9.82":
            return panel
    return config.PANELS[0] if config.PANELS else None


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
            self.send_json(PHONE.snapshot())
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
        if self.path == "/api/face":
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0 or length > 12 * 1024 * 1024:
                self.send_json({"ok": False, "face": "нужны квартира и фото"})
                return
            body = self.rfile.read(length)
            parts = multipart_parts(self.headers.get("Content-Type", ""), body)
            apartment = parts.get("apartment", {}).get("data", b"").decode("utf-8", "replace").strip()
            photo = parts.get("photo", {}).get("data", b"")
            ok, message = upload_face(face_panel(), apartment, photo)
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
