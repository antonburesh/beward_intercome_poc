"""SIP softphone: registration, one call at a time, and RTP send/receive."""

import hashlib
import os
import queue
import re
import secrets
import select
import socket
import struct
import threading
import time

from phone import config
from phone.codecs import alaw_to_linear, linear_to_alaw, linear_to_ulaw, rtp_packet, ulaw_to_linear
from phone.echo import EchoCanceller
from phone.h264 import avc_decoder_config, depacketize, sprop_nals
from phone.sdp import answer_sdp, parse_offer, sdp_media

# 120 ms. A microphone chunk can be a little late without a hole in the word.
MIC_PREROLL_FRAMES = 6


def md5(text):
    return hashlib.md5(text.encode()).hexdigest()


def header_value(headers, name):
    name = name.lower()
    for key, value in headers:
        if key.lower() == name:
            return value
    return ""


def parse_message(data):
    text = data.decode("utf-8", "replace")
    head, _, body = text.partition("\r\n\r\n")
    lines = head.split("\r\n")
    headers = []
    for line in lines[1:]:
        if line.startswith((" ", "\t")) and headers:
            key, value = headers[-1]
            headers[-1] = (key, value + " " + line.strip())
            continue
        key, _, value = line.partition(":")
        headers.append((key.strip(), value.strip()))
    return lines[0], headers, body


def digest_authorization(method, username, password, challenge, uri):
    def grab(name):
        match = re.search(rf'{name}=("([^"]+)"|([^",\s]+))', challenge)
        if not match:
            return ""
        return match.group(2) or match.group(3)

    realm = grab("realm")
    nonce = grab("nonce")
    opaque = grab("opaque")
    qop = (grab("qop") or "").split(",")[0]
    ha1 = md5(f"{username}:{realm}:{password}")
    ha2 = md5(f"{method}:{uri}")
    extra = ""
    if qop:
        nc = "00000001"
        cnonce = secrets.token_hex(4)
        response = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
        extra = f', qop={qop}, nc={nc}, cnonce="{cnonce}"'
    else:
        response = md5(f"{ha1}:{nonce}:{ha2}")
    if opaque:
        extra += f', opaque="{opaque}"'
    return (
        f'Authorization: Digest username="{username}", realm="{realm}", nonce="{nonce}", '
        f'uri="{uri}", response="{response}", algorithm=MD5{extra}'
    )


def apartment_of(headers):
    explicit = header_value(headers, "X-Apartment")
    if explicit:
        return explicit
    from_header = header_value(headers, "From")
    match = re.search(r'"Apt-([^"]+)"', from_header)
    if match:
        return match.group(1)
    to_header = header_value(headers, "To")
    match = re.search(r"sip:([^@>;]+)", to_header)
    return match.group(1) if match else ""


def door_station_of(headers):
    """SIP user of the door panel: X-Door-Station, otherwise the From user."""
    explicit = header_value(headers, "X-Door-Station").strip()
    if explicit:
        return explicit
    match = re.search(r"sip:([^@>;\s]+)", header_value(headers, "From"))
    return match.group(1) if match else ""


def public_headers(headers):
    """SIP headers safe to show. Auth and password fields stay off the page."""
    hidden = {"authorization", "proxy-authorization", "www-authenticate", "proxy-authenticate"}
    visible = []
    for name, value in headers:
        key = name.lower()
        if key in hidden or any(word in key for word in ("password", "passwd", "secret")):
            continue
        visible.append({"name": name, "value": value})
    return visible


class Softphone:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # SIP_BIND is 0.0.0.0 in Docker, where the LAN address is not on an interface.
        # Contact and SDP still use sip.ip so the panel can reach the published ports.
        self.bind_ip = os.environ.get("SIP_BIND") or config.SERVER_IP or "0.0.0.0"
        self.sock.bind((self.bind_ip, int(os.environ.get("SIP_PORT") or 0)))
        _bound_ip, self.local_port = self.sock.getsockname()
        self.local_ip = config.SERVER_IP or _bound_ip
        # On the server the public address is a NAT address. REGISTER goes to the
        # Kamailio container by name. Contact and SDP stay on sip.ip.
        self.register_host = os.environ.get("SIP_REGISTER_HOST") or config.SERVER_IP
        self.reg_call_id = secrets.token_hex(8)
        self.reg_tag = secrets.token_hex(4)
        self.reg_cseq = 0
        self.registered = False
        self.error = ""
        self.expires_at = 0
        self.next_register = 0
        self.call = None
        self.log = []
        self.rtp_sock = None
        self.video_sock = None
        self.rtp_target = None
        self.rtp_close = False
        self.listeners = []
        self.fu = None
        self.access = []
        self.sps = None
        self.pps = None
        self.config_sent = False
        self.rtp_seq = 0
        self.rtp_ts = 0
        self.rtp_ssrc = secrets.randbits(32)
        self.next_rtp = 0
        self.mic = bytearray()
        self.mic_tail = b""
        self.mic_ready = False
        self.audio_gaps = 0
        self.audio_pt = 8
        self.mic_heard = False
        self.audio_started = False
        self.rtp_error = False
        self.echo = EchoCanceller()
        self.lock = threading.Lock()
        self.running = True

    def contact(self):
        return f"<sip:{config.SIP_USER}@{self.local_ip}:{self.local_port}>"

    def send(self, payload, addr):
        self.sock.sendto(payload if isinstance(payload, bytes) else payload.encode(), addr)

    def build_register(self, auth_line=None):
        self.reg_cseq += 1
        lines = [
            f"REGISTER sip:{config.SERVER_IP} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{secrets.token_hex(6)};rport",
            "Max-Forwards: 70",
            f"From: <sip:{config.SIP_USER}@{config.SERVER_IP}>;tag={self.reg_tag}",
            f"To: <sip:{config.SIP_USER}@{config.SERVER_IP}>",
            f"Call-ID: {self.reg_call_id}",
            f"CSeq: {self.reg_cseq} REGISTER",
            f"Contact: {self.contact()}",
            f"Expires: {config.EXPIRES}",
            "User-Agent: door-poc",
        ]
        if auth_line:
            lines.append(auth_line)
        lines.extend(["Content-Length: 0", "", ""])
        return "\r\n".join(lines).encode()

    def start_register(self):
        self.next_register = time.time() + config.EXPIRES / 2
        self.send(self.build_register(), (self.register_host, config.SERVER_PORT))

    def reply(self, addr, headers, status, to_tag, extra, body=b""):
        lines = [f"SIP/2.0 {status}"]
        seen = set()
        for name, value in headers:
            key = name.lower()
            if key not in ("via", "from", "to", "call-id", "cseq"):
                continue
            if key == "to" and to_tag and "tag=" not in value.lower():
                value = f"{value};tag={to_tag}"
            label = name if key in ("call-id", "cseq") else key.capitalize()
            lines.append(f"{label}: {value}")
            seen.add(key)
        if seen != {"via", "from", "to", "call-id", "cseq"}:
            return
        lines.extend(extra)
        lines.append(f"Content-Length: {len(body)}")
        lines.extend(["", ""])
        self.send("\r\n".join(lines).encode() + body, addr)

    def ringing_response(self, addr, headers, to_tag):
        self.reply(addr, headers, "180 Ringing", to_tag, [f"Contact: {self.contact()}"])

    def answer_response(self, addr, headers, to_tag, sdp):
        self.reply(
            addr,
            headers,
            "200 OK",
            to_tag,
            [
                f"Contact: {self.contact()}",
                "Content-Type: application/sdp",
            ],
            sdp,
        )

    def bind_udp(self, port=0):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.bind_ip, port))
        return sock

    def make_sdp(self, offer):
        if self.rtp_sock is None:
            self.rtp_sock = self.bind_udp(int(os.environ.get("RTP_PORT") or 0))
        sections, _ = parse_offer(offer or "")
        wants_video = any(section.get("h264") for section in sections)
        if wants_video and self.video_sock is None:
            self.video_sock = self.bind_udp(int(os.environ.get("VIDEO_PORT") or 0))
        audio_port = self.rtp_sock.getsockname()[1]
        video_port = self.video_sock.getsockname()[1] if self.video_sock else 0
        return answer_sdp(config.SIP_USER, self.local_ip, audio_port, video_port, offer)

    def close_rtp(self):
        # Closed later by the SIP thread. Closing here races with select().
        with self.lock:
            self.rtp_close = True
            self.rtp_target = None

    def subscribe(self):
        listener = queue.Queue(maxsize=240)
        with self.lock:
            self.listeners.append(listener)
        return listener

    def unsubscribe(self, listener):
        with self.lock:
            if listener in self.listeners:
                self.listeners.remove(listener)

    def push_media(self, kind, payload):
        frame = bytes([kind]) + struct.pack("!I", len(payload)) + payload
        with self.lock:
            listeners = list(self.listeners)
        for listener in listeners:
            try:
                listener.put_nowait(frame)
            except queue.Full:
                try:
                    listener.get_nowait()
                except queue.Empty:
                    continue
                try:
                    listener.put_nowait(frame)
                except queue.Full:
                    continue

    def emit_audio(self, payload_type, payload):
        decode = ulaw_to_linear if payload_type == 0 else alaw_to_linear
        samples = [decode(byte) for byte in payload]
        samples = self.echo.clean(samples)
        packed = b"".join(struct.pack("<h", sample) for sample in samples)
        if packed:
            self.push_media(1, packed)

    def emit_video(self, marker):
        if not marker or not self.access:
            return
        pictures = []
        for nal in self.access:
            if not nal:
                continue
            kind = nal[0] & 0x1F
            if kind == 7 and nal != self.sps:
                self.sps = nal
                self.config_sent = False
            elif kind == 8 and nal != self.pps:
                self.pps = nal
                self.config_sent = False
            elif kind in (1, 5):
                pictures.append(nal)
        self.access = []
        if self.sps and self.pps and not self.config_sent and len(self.sps) >= 4:
            codec = "avc1." + self.sps[1:4].hex().upper()
            description = avc_decoder_config(self.sps, self.pps)
            self.push_media(3, bytes([len(codec)]) + codec.encode() + description)
            self.config_sent = True
        if not pictures:
            return
        key = any((nal[0] & 0x1F) == 5 for nal in pictures)
        body = bytearray([1 if key else 0])
        for nal in pictures:
            body += struct.pack("!I", len(nal)) + nal
        self.push_media(2, bytes(body))

    def handle_h264(self, payload, marker):
        if not payload:
            return
        nals, self.fu = depacketize(payload, self.fu)
        for nal in nals:
            if not nal:
                continue
            kind = nal[0] & 0x1F
            if kind == 7:
                self.sps = nal
            elif kind == 8:
                self.pps = nal
            self.access.append(nal)
        if marker:
            self.emit_video(True)

    def handle_rtp(self, sock, data, addr):
        parsed = rtp_packet(data)
        if not parsed:
            return
        payload_type, marker, payload = parsed
        with self.lock:
            if self.call and self.call["state"] == "talking":
                self.call["rtp"] += 1
        if sock is self.rtp_sock:
            # The offer often says 0.0.0.0. The port the panel is sending
            # from is the port that plays our voice.
            if addr and addr[0] not in ("0.0.0.0", "127.0.0.1") and self.rtp_target != addr:
                print(f"голос на панель: {addr[0]}:{addr[1]}", flush=True)
                self.rtp_target = addr
            if payload_type in (0, 8):
                self.audio_pt = payload_type
                self.emit_audio(payload_type, payload)
        elif sock is self.video_sock:
            self.handle_h264(payload, marker)

    def remember(self, apartment, result):
        stamp = time.strftime("%H:%M:%S")
        self.log.insert(0, {"time": stamp, "apartment": apartment or "?", "result": result})
        del self.log[8:]

    def begin_call(self, addr, headers, body):
        call_id = header_value(headers, "Call-ID")
        with self.lock:
            current = self.call
        if current and current["id"] == call_id:
            self.resend_current(addr)
            return
        if current and current["state"] in ("ringing", "talking"):
            self.reply(addr, headers, "486 Busy Here", secrets.token_hex(4), [])
            return
        to_tag = secrets.token_hex(4)
        media_ip, media_port = sdp_media(body)
        # X-Door-Station is the door's SIP user. The UDP source is often Docker NAT.
        station = door_station_of(headers)
        panel = config.panel_for(station)
        call = {
            "id": call_id,
            "state": "ringing",
            "apartment": apartment_of(headers),
            "panel": panel["name"] if panel else "",
            "panel_known": panel is not None,
            "panel_cfg": panel,
            "from": header_value(headers, "From"),
            "to": header_value(headers, "To"),
            "params": [
                {"name": name, "value": value}
                for name, value in headers
                if name.lower().startswith("x-")
            ],
            "to_tag": to_tag,
            "headers": headers,
            "addr": addr,
            "rtp": 0,
            "media": (media_ip, media_port),
            "offer": body,
            "sdp": b"",
        }
        with self.lock:
            self.call = call
        self.ringing_response(addr, headers, to_tag)

    def resend_current(self, addr):
        with self.lock:
            call = self.call
        if not call:
            return
        if call["state"] == "ringing":
            self.ringing_response(addr, call["headers"], call["to_tag"])
        elif call["state"] == "talking" and call["sdp"]:
            self.answer_response(addr, call["headers"], call["to_tag"], call["sdp"])

    def answer(self):
        with self.lock:
            call = self.call
            if not call or call["state"] != "ringing":
                return
            self.fu = None
            self.access = []
            self.sps = None
            self.pps = None
            self.config_sent = False
            self.mic.clear()
            self.mic_tail = b""
            self.mic_heard = False
            self.audio_started = False
            self.rtp_error = False
            self.mic_ready = False
            self.audio_gaps = 0
            self.echo.reset()
            self.audio_pt = 8
            sections, _ = parse_offer(call.get("offer") or "")
            for section in sections:
                for nal in sprop_nals(section.get("fmtp_h264") or ""):
                    kind = nal[0] & 0x1F if nal else 0
                    if kind == 7:
                        self.sps = nal
                    elif kind == 8:
                        self.pps = nal
            for listener in list(self.listeners):
                while True:
                    try:
                        listener.get_nowait()
                    except queue.Empty:
                        break
            sdp = self.make_sdp(call.get("offer") or "")
            call["state"] = "talking"
            call["sdp"] = sdp
            media_ip, media_port = call["media"]
            if media_ip and media_ip != "0.0.0.0" and media_port:
                self.rtp_target = (media_ip, media_port)
            else:
                self.rtp_target = None
            self.next_rtp = 0
            addr, headers, to_tag = call["addr"], call["headers"], call["to_tag"]
        self.answer_response(addr, headers, to_tag, sdp)

    def reject(self):
        with self.lock:
            call = self.call
            if not call or call["state"] != "ringing":
                return
            self.call = None
            self.remember(call["apartment"], "отклонён")
            addr, headers, to_tag = call["addr"], call["headers"], call["to_tag"]
        self.reply(addr, headers, "486 Busy Here", to_tag, [])

    def hangup(self):
        with self.lock:
            call = self.call
            if not call or call["state"] != "talking":
                return
            self.call = None
            self.remember(call["apartment"], "завершён")
            cseq = header_value(call["headers"], "CSeq")
            number = cseq.split()[0] if cseq else "1"
            try:
                next_cseq = int(number) + 1
            except ValueError:
                next_cseq = 2
            lines = [
                f"BYE sip:{config.SERVER_IP} SIP/2.0",
                f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{secrets.token_hex(6)};rport",
                "Max-Forwards: 70",
                f"From: {call['to']};tag={call['to_tag']}" if "tag=" not in call["to"].lower() else f"From: {call['to']}",
                f"To: {call['from']}",
                f"Call-ID: {call['id']}",
                f"CSeq: {next_cseq} BYE",
                "Content-Length: 0",
                "",
                "",
            ]
            addr = call["addr"]
        self.close_rtp()
        self.send("\r\n".join(lines), addr)

    def end_call(self, result):
        with self.lock:
            call = self.call
            self.call = None
            self.mic.clear()
            self.mic_tail = b""
            self.mic_ready = False
            self.echo.reset()
            self.audio_gaps = 0
            if call:
                self.remember(call["apartment"], result)
        self.close_rtp()

    def handle_response(self, start, headers):
        cseq = header_value(headers, "CSeq")
        if not cseq.upper().endswith("REGISTER"):
            return
        if start.startswith("SIP/2.0 401") or start.startswith("SIP/2.0 407"):
            challenge = header_value(headers, "WWW-Authenticate") or header_value(headers, "Proxy-Authenticate")
            auth = digest_authorization(
                "REGISTER", config.SIP_USER, config.SIP_PASSWORD, challenge, f"sip:{config.SERVER_IP}"
            )
            self.send(self.build_register(auth), (self.register_host, config.SERVER_PORT))
            return
        if start.startswith("SIP/2.0 200"):
            with self.lock:
                self.registered = True
                self.error = ""
                self.expires_at = time.time() + config.EXPIRES
            return
        with self.lock:
            self.registered = False
            self.error = start

    def handle_request(self, start, headers, body, addr):
        method = start.split(" ", 1)[0]
        if method == "INVITE":
            self.begin_call(addr, headers, body)
            return
        if method == "ACK":
            return
        if method == "CANCEL":
            self.reply(addr, headers, "200 OK", None, [])
            with self.lock:
                call = self.call
            if call and call["state"] == "ringing" and header_value(headers, "Call-ID") == call["id"]:
                self.reply(addr, call["headers"], "487 Request Terminated", call["to_tag"], [])
                self.end_call("отменён")
            return
        if method == "BYE":
            self.reply(addr, headers, "200 OK", None, [])
            self.end_call("завершён домофоном")
            return
        if method == "OPTIONS":
            self.reply(addr, headers, "200 OK", secrets.token_hex(3), [f"Contact: {self.contact()}"])

    def audio_clock(self):
        """Send one 20 ms voice packet on its own clock.

        Audio and video are separate RTP sessions. A late packet does not
        make the next one go out immediately: the panel plays on arrival,
        and a burst after a gap is what sounds torn.
        """
        while self.running:
            with self.lock:
                active = self.rtp_sock is not None and self.rtp_target is not None
                due = self.next_rtp
            if not active:
                time.sleep(0.02)
                continue
            now = time.monotonic()
            if due <= 0:
                due = now
            if due > now:
                time.sleep(min(0.02, due - now))
                continue
            self._send_audio_frame()
            self.next_rtp = time.monotonic() + 0.02

    def push_mic(self, payload):
        """Append little-endian PCM16. An odd trailing byte waits for the next chunk."""
        if not payload:
            return
        with self.lock:
            payload = self.mic_tail + bytes(payload)
            if len(payload) % 2:
                self.mic_tail = payload[-1:]
                payload = payload[:-1]
            else:
                self.mic_tail = b""
            if payload:
                self.mic.extend(payload)
            # A full second used to sit here, so the panel spoke the oldest
            # audio. Keep only the preroll: the speaker stays close to the mic.
            keep = 320 * MIC_PREROLL_FRAMES
            if len(self.mic) > keep:
                del self.mic[:len(self.mic) - keep]

    def _take_pcm(self):
        """One 20 ms frame from the microphone, in the order it was captured.

        Playback starts after the preroll. A missing frame is silence.
        Repeating the previous frame is what made the panel sound torn.
        """
        frame = 320
        with self.lock:
            keep = frame * MIC_PREROLL_FRAMES
            if len(self.mic) > keep:
                del self.mic[:len(self.mic) - keep]
            if not self.mic_ready:
                if len(self.mic) < keep:
                    return b""
                self.mic_ready = True
            if len(self.mic) >= frame:
                pcm = bytes(self.mic[:frame])
                del self.mic[:frame]
                return pcm
            self.mic_ready = False
            self.audio_gaps += 1
            if self.audio_gaps == 1:
                print("голос прервался: микрофон не успел", flush=True)
            return b""

    def _send_audio_frame(self):
        with self.lock:
            sock = self.rtp_sock
            target = self.rtp_target
            if not sock or not target:
                return False
            self.rtp_seq = (self.rtp_seq + 1) & 0xFFFF
            self.rtp_ts = (self.rtp_ts + 160) & 0xFFFFFFFF
            pt = 0 if self.audio_pt == 0 else 8
            marker = 0 if self.audio_started else 0x80
            self.audio_started = True
            header = struct.pack("!BBHII", 0x80, marker | pt, self.rtp_seq, self.rtp_ts, self.rtp_ssrc)
        pcm = self._take_pcm()
        encode = linear_to_ulaw if pt == 0 else linear_to_alaw
        silence = 0xFF if pt == 0 else 0xD5
        if len(pcm) == 320:
            samples = struct.unpack("<160h", pcm)
            peak = max(abs(sample) for sample in samples)
            if peak > 400 and not self.mic_heard:
                self.mic_heard = True
                name = "G.711U" if pt == 0 else "G.711A"
                print(f"микрофон со звуком, пик {peak}, {name}", flush=True)
            payload = bytes(encode(sample) for sample in samples)
        else:
            samples = (0,) * 160
            payload = bytes([silence]) * 160
        self.echo.remember(samples)
        try:
            sock.sendto(header + payload, target)
        except OSError as exc:
            if not self.rtp_error:
                self.rtp_error = True
                print(f"голос не отправился: {exc}", flush=True)
        return bool(pcm)

    def drop_rtp_socket(self):
        with self.lock:
            closing = self.rtp_close
            socks = []
            if closing:
                socks = [sock for sock in (self.rtp_sock, self.video_sock) if sock]
                self.rtp_sock = None
                self.video_sock = None
                self.rtp_close = False
        for sock in socks:
            try:
                sock.close()
            except OSError:
                pass

    def loop(self):
        self.start_register()
        threading.Thread(target=self.audio_clock, name="rtp-audio", daemon=True).start()
        while self.running:
            try:
                self.drop_rtp_socket()
                if time.time() >= self.next_register:
                    self.start_register()
                with self.lock:
                    rtp = self.rtp_sock
                    video = self.video_sock
                sockets = [self.sock]
                if rtp:
                    sockets.append(rtp)
                if video:
                    sockets.append(video)
                try:
                    readable, _, _ = select.select(sockets, [], [], 0.2)
                except OSError:
                    continue
            except Exception as exc:
                print("sip loop:", exc, flush=True)
                time.sleep(0.2)
                continue
            for sock in readable:
                try:
                    data, addr = sock.recvfrom(65535)
                except OSError:
                    continue
                if sock is self.rtp_sock or sock is self.video_sock:
                    self.handle_rtp(sock, data, addr)
                    continue
                start, headers, body = parse_message(data)
                if start.startswith("SIP/2.0"):
                    self.handle_response(start, headers)
                else:
                    self.handle_request(start, headers, body, addr)

    def active_panel(self):
        """Panel for the current call, or None when there is no known panel."""
        with self.lock:
            call = self.call
            if not call or not call.get("panel_known"):
                return None
            return call.get("panel_cfg")

    def door_target(self):
        """Panel to command, plus a message when the command must not be sent."""
        with self.lock:
            call = self.call
            if not call:
                return None, "нет вызова"
            if not call.get("panel_known"):
                return None, "панель неизвестна"
            return call.get("panel_cfg"), ""

    def snapshot(self):
        with self.lock:
            call = None
            if self.call:
                call = {
                    "id": self.call["id"],
                    "state": self.call["state"],
                    "apartment": self.call["apartment"],
                    "panel": self.call.get("panel") or None,
                    "panel_known": bool(self.call.get("panel_known")),
                    "from": self.call["from"],
                    "to": self.call["to"],
                    "params": self.call["params"],
                    "headers": public_headers(self.call.get("headers") or []),
                    "rtp": self.call["rtp"],
                }
            alive = self.registered and time.time() < self.expires_at + 5
            return {
                "registered": alive,
                "error": self.error,
                "user": config.SIP_USER,
                "server": f"{config.SERVER_IP}:{config.SERVER_PORT}",
                "call": call,
                "log": list(self.log),
            }
