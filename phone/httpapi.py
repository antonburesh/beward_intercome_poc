"""Local HTTP routes: page, call control, microphone, snapshot, and door."""

import json
from http.server import BaseHTTPRequestHandler

from phone.door import fetch_snapshot, open_door
from phone.page import PAGE

PHONE = None


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
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/mic":
            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = self.rfile.read(min(length, 64000)) if length > 0 else b""
            if len(payload) >= 2:
                payload = payload[:len(payload) - (len(payload) % 2)]
                with PHONE.lock:
                    PHONE.mic.extend(payload)
                    if len(PHONE.mic) > 16000:
                        del PHONE.mic[:len(PHONE.mic) - 16000]
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
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
