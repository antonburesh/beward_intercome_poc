#!/usr/bin/env python3
"""Local proof-of-concept softphone for the door station.

Registers as SIP user 101 and shows an incoming apartment call,
including the X-Apartment parameter added by Kamailio.

Run from the project directory:

    python3 phone/app.py
"""

import base64
import hashlib
import json
import os
import queue
import re
import secrets
import select
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

SERVER_IP = os.environ.get("ADVERTISE_IP", "192.168.9.106")
SERVER_PORT = int(os.environ.get("SIP_PORT", "5060"))
SIP_USER = os.environ.get("SIP_USER", "101")
SIP_PASSWORD = os.environ.get("SIP_PASSWORD", "phone101")
HTTP_HOST = os.environ.get("PHONE_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("PHONE_PORT", "8090"))
DOOR_URL = os.environ.get(
    "DOOR_URL", "http://192.168.9.82/cgi-bin/intercom_cgi?action=maindoor"
)
SNAPSHOT_URL = os.environ.get(
    "SNAPSHOT_URL", "http://192.168.9.82/cgi-bin/images_cgi?channel=0"
)
DOOR_USER = os.environ.get("DOOR_USER", "admin")
DOOR_PASSWORD = os.environ.get("DOOR_PASSWORD", "admin")
EXPIRES = 120

PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Домофон</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #121410;
    --card: #1c1f18;
    --line: #2c3126;
    --text: #f3f1e8;
    --muted: #a3a898;
    --accent: #d6ff4a;
    --danger: #ff6b4a;
    --ok: #9be36a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    background: var(--bg);
    color: var(--text);
    font: 16px/1.4 "Avenir Next", "Segoe UI", sans-serif;
  }
  main {
    max-width: 720px;
    margin: 0 auto;
    padding: 28px 20px 40px;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
  }
  .open { background: var(--danger); color: #1a0d08; }
  .door-msg { min-height: 1.2em; margin: 10px 0 0; color: var(--ok); font-size: 14px; }
  h1 { font-size: 18px; font-weight: 650; margin: 0; letter-spacing: 0.02em; }
  .status {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--muted);
    font-size: 14px;
  }
  .dot {
    width: 9px; height: 9px; border-radius: 50%;
    background: var(--muted);
  }
  .dot.on { background: var(--ok); }
  .dot.err { background: var(--danger); }
  .stage {
    margin-top: 28px;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 18px;
    min-height: 340px;
    padding: 28px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }
  .eyebrow { color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: 0.12em; }
  .apt {
    font-size: 92px;
    line-height: 0.95;
    font-weight: 700;
    letter-spacing: -0.04em;
    margin: 12px 0 0;
  }
  .idle-title { font-size: 34px; margin: 18px 0 8px; }
  .sub { color: var(--muted); margin: 0; }
  .params {
    margin-top: 22px;
    display: grid;
    gap: 8px;
  }
  .param {
    display: grid;
    grid-template-columns: 160px 1fr;
    gap: 12px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 13px;
  }
  .param span { color: var(--muted); }
  .actions { display: flex; gap: 10px; margin-top: 22px; }
  button {
    border: 0;
    border-radius: 999px;
    padding: 12px 22px;
    font: inherit;
    font-weight: 650;
    cursor: pointer;
  }
  button:disabled { opacity: 0.4; cursor: default; }
  .answer { background: var(--accent); color: #172000; }
  .reject { background: transparent; color: var(--text); border: 1px solid var(--line); }
  .log { margin-top: 22px; color: var(--muted); font-size: 14px; }
  .log li { margin: 6px 0; }
  .rtp { margin-top: 14px; color: var(--accent); font-size: 14px; }
  #cam, #shot {
    display: block;
    width: 100%;
    max-height: 320px;
    margin-top: 16px;
    background: #000;
    border-radius: 12px;
    object-fit: contain;
  }
</style>
</head>
<body>
<main>
  <header>
    <h1>Домофон</h1>
    <div class="status"><i id="dot" class="dot"></i><span id="status">подключение</span></div>
  </header>
  <section class="stage" id="stage"></section>
  <section class="log">
    <div>Последние вызовы</div>
    <ul id="log"></ul>
  </section>
</main>
<script>
const stage = document.getElementById("stage");
const log = document.getElementById("log");
const statusEl = document.getElementById("status");
const dot = document.getElementById("dot");
let lastRing = "";
let audioCtx;

function beep() {
  try {
    audioCtx = audioCtx || new AudioContext();
    const o = audioCtx.createOscillator();
    const g = audioCtx.createGain();
    o.frequency.value = 880;
    g.gain.value = 0.04;
    o.connect(g); g.connect(audioCtx.destination);
    o.start();
    setTimeout(() => o.stop(), 180);
  } catch (e) {}
}

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function row(name, value) {
  const text = value ? esc(value) : "—";
  return `<div class="param"><span>${esc(name)}</span><b>${text}</b></div>`;
}

function render(data) {
  dot.className = "dot" + (data.registered ? " on" : data.error ? " err" : "");
  statusEl.textContent = data.registered
    ? "номер " + data.user + " зарегистрирован"
    : (data.error || "подключение");

  const call = data.call;
  if (!call) {
    lastRing = "";
    stopMic();
    stage.innerHTML = `
      <div>
        <div class="eyebrow">ожидание</div>
        <h2 class="idle-title">Наберите квартиру на домофоне</h2>
        <p class="sub">Вызов с квартиры 1–1000 придёт сюда вместе с параметрами SIP.</p>
      </div>`;
  } else {
    if (call.state === "ringing" && call.id !== lastRing) {
      lastRing = call.id;
      beep();
    }
    const title = call.state === "talking" ? "разговор" : "входящий вызов";
    const params = (call.params || []).map(p => row(p.name, p.value)).join("");
    stage.innerHTML = `
      <div>
        <div class="eyebrow">${title}</div>
        <div class="apt">${esc(call.apartment || "?")}</div>
        <p class="sub">${call.state === "talking" ? "Трубка снята" : "Квартира вызывает"}</p>
        <div class="params">
          ${row("From", call.from)}
          ${row("To", call.to)}
          ${params}
        </div>
        ${call.state === "ringing" ? `<img id="shot" alt="Камера панели" src="/snapshot?t=${Date.now()}">` : ""}
        ${call.state === "talking" ? `<canvas id="cam" width="960" height="540"></canvas><div class="rtp" id="mic-note">${esc(micNote)}</div><div class="rtp" id="rtp-count">RTP от домофона: ${call.rtp} пакетов</div>` : ""}
      </div>
      <div>
        <div class="actions">
          <button class="answer" id="answer" ${call.state === "ringing" ? "" : "disabled"}>Ответить</button>
          <button class="reject" id="reject">${call.state === "talking" ? "Завершить" : "Отклонить"}</button>
          <button class="open" id="open" type="button">Открыть дверь</button>
        </div>
        <p class="door-msg" id="door-msg"></p>
      </div>`;
    document.getElementById("answer").onclick = () => { startMedia(); post("/api/answer"); };
    if (call.state === "ringing") shotAt = Date.now();
    if (call.state === "talking") startMedia();
    document.getElementById("reject").onclick = () => post(call.state === "talking" ? "/api/hangup" : "/api/reject");
    document.getElementById("open").onclick = openDoor;
  }

  log.innerHTML = (data.log || []).map(item =>
    `<li>${item.time} — квартира ${item.apartment}, ${item.result}</li>`
  ).join("") || "<li>пока пусто</li>";
}

async function post(url) {
  await fetch(url, { method: "POST" });
  refresh();
}

async function openDoor() {
  const button = document.getElementById("open");
  const note = document.getElementById("door-msg");
  if (!button) return;
  button.disabled = true;
  if (note) note.textContent = "открываю…";
  try {
    const res = await fetch("/api/open", { method: "POST" });
    const data = await res.json();
    if (note) note.textContent = data.door || "не удалось открыть";
  } catch (e) {
    if (note) note.textContent = "не удалось открыть";
  }
  button.disabled = false;
}

let mediaStarted = false;
let audioNext = 0;
let videoDecoder = null;
let videoTime = 0;
let pendingVideo = [];
let videoCodec = "";
let videoDescription = null;

let micNote = "";
let micStream = null;
let micQueue = [];
let micPos = 0;
let micSending = false;

function setMicNote(text) {
  micNote = text;
  const el = document.getElementById("mic-note");
  if (el) el.textContent = text;
}

function startMedia() {
  if (mediaStarted) return;
  mediaStarted = true;
  audioCtx = new AudioContext();
  audioCtx.resume();
  readMedia();
  startMic();
}

function startMic() {
  if (!navigator.mediaDevices || micStream) return;
  setMicNote("микрофон включается");
  navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    video: false
  }).then(stream => {
    if (!mediaStarted) {
      stream.getTracks().forEach(track => track.stop());
      return;
    }
    micStream = stream;
    const source = audioCtx.createMediaStreamSource(stream);
    const processor = audioCtx.createScriptProcessor(1024, 1, 1);
    const mute = audioCtx.createGain();
    mute.gain.value = 0;
    const ratio = audioCtx.sampleRate / 8000;
    processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      const samples = [];
      let pos = micPos;
      while (pos < input.length) {
        const sample = Math.max(-1, Math.min(1, input[Math.floor(pos)] || 0));
        samples.push((sample * 32767) | 0);
        pos += ratio;
      }
      micPos = pos - input.length;
      if (samples.length) queueMic(samples);
    };
    source.connect(processor);
    processor.connect(mute);
    mute.connect(audioCtx.destination);
    setMicNote("микрофон включён, вас слышно на панели");
  }).catch(() => setMicNote("нет доступа к микрофону"));
}

function queueMic(samples) {
  micQueue.push.apply(micQueue, samples);
  if (micQueue.length > 8000) micQueue.splice(0, micQueue.length - 8000);
  flushMic();
}

function flushMic() {
  if (micSending || micQueue.length < 160) return;
  micSending = true;
  const count = Math.min(micQueue.length - (micQueue.length % 160), 800);
  const chunk = micQueue.splice(0, count);
  const body = new Int16Array(chunk);
  fetch("/api/mic", {
    method: "POST",
    body: body.buffer,
    headers: { "Content-Type": "application/octet-stream" }
  }).catch(() => {}).then(() => {
    micSending = false;
    flushMic();
  });
}

function stopMic() {
  if (micStream) micStream.getTracks().forEach(track => track.stop());
  micStream = null;
  micQueue = [];
  micPos = 0;
  micNote = "";
  mediaStarted = false;
}

function playPcm(bytes) {
  if (!audioCtx) return;
  const samples = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
  const floats = new Float32Array(samples.length);
  for (let i = 0; i < samples.length; i++) floats[i] = samples[i] / 32768;
  const buffer = audioCtx.createBuffer(1, floats.length, 8000);
  buffer.copyToChannel(floats, 0);
  const src = audioCtx.createBufferSource();
  src.buffer = buffer;
  src.connect(audioCtx.destination);
  if (audioNext < audioCtx.currentTime) audioNext = audioCtx.currentTime + 0.08;
  src.start(audioNext);
  audioNext += buffer.duration;
}

function configureVideo(codec, description) {
  if (typeof VideoDecoder === "undefined") return;
  videoCodec = codec;
  videoDescription = new Uint8Array(description);
  if (videoDecoder && videoDecoder.state !== "closed") videoDecoder.close();
  const canvas = () => document.getElementById("cam");
  const decoder = new VideoDecoder({
    output(frame) {
      const el = canvas();
      if (el) {
        if (el.width !== frame.displayWidth) el.width = frame.displayWidth;
        if (el.height !== frame.displayHeight) el.height = frame.displayHeight;
        el.getContext("2d").drawImage(frame, 0, 0);
      }
      frame.close();
    },
    error() {
      if (videoDecoder === decoder) videoDecoder = null;
    }
  });
  videoDecoder = decoder;
  videoDecoder.configure({ codec, description: videoDescription, optimizeForLatency: true });
  pendingVideo.splice(0).forEach(item => decodeVideo(item.key, item.data));
}

function decodeVideo(key, data) {
  if ((!videoDecoder || videoDecoder.state !== "configured") && key && videoCodec) {
    configureVideo(videoCodec, videoDescription);
  }
  if (!videoDecoder || videoDecoder.state !== "configured") {
    if (key) pendingVideo = [{ key, data }];
    return;
  }
  videoTime += 33333;
  try {
    videoDecoder.decode(new EncodedVideoChunk({
      type: key ? "key" : "delta",
      timestamp: videoTime,
      data
    }));
  } catch (e) {
    videoDecoder = null;
    if (key) pendingVideo = [{ key, data }];
  }
}

async function readMedia() {
  while (mediaStarted) {
  const res = await fetch("/media");
  const reader = res.body.getReader();
  let buf = new Uint8Array(0);
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    const merged = new Uint8Array(buf.length + chunk.value.length);
    merged.set(buf);
    merged.set(chunk.value, buf.length);
    buf = merged;
    while (buf.length >= 5) {
      const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
      const kind = view.getUint8(0);
      const size = view.getUint32(1);
      if (buf.length < 5 + size) break;
      const payload = buf.slice(5, 5 + size);
      buf = buf.slice(5 + size);
      if (kind === 1) playPcm(payload);
      else if (kind === 3 && payload.length > 1) {
        const n = payload[0];
        const codec = new TextDecoder().decode(payload.slice(1, 1 + n));
        configureVideo(codec, payload.slice(1 + n));
      } else if (kind === 2 && payload.length > 0) {
        decodeVideo(payload[0] === 1, payload.slice(1));
      }
    }
    if (chunk.done) break;
  }
  }
}

let lastView = "";
let shotAt = 0;

function refreshShot() {
  const shot = document.getElementById("shot");
  if (!shot) return;
  const now = Date.now();
  if (now - shotAt < 1000) return;
  shotAt = now;
  shot.src = "/snapshot?t=" + now;
}

function viewKey(data) {
  const copy = JSON.parse(JSON.stringify(data));
  if (copy.call) copy.call.rtp = 0;
  return JSON.stringify(copy);
}

async function refresh() {
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    const data = await res.json();
    const key = viewKey(data);
    if (key !== lastView) {
      lastView = key;
      render(data);
    } else if (data.call && data.call.state === "talking") {
      const rtp = document.getElementById("rtp-count");
      if (rtp) rtp.textContent = "RTP от домофона: " + data.call.rtp + " пакетов";
    } else if (data.call && data.call.state === "ringing") {
      refreshShot();
    }
  } catch (e) {
    statusEl.textContent = "нет связи со страницей";
    dot.className = "dot err";
  }
}

refresh();
setInterval(refresh, 700);
</script>
</body>
</html>
"""


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


def sdp_media(body):
    sections, _ = parse_offer(body)
    for section in sections:
        if section["kind"] == "audio" and section["port"]:
            return section["ip"], section["port"]
    return None, None


def parse_offer(body):
    session_ip = None
    sections = []
    current = None
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith("c=IN IP4 ") and current is None:
            session_ip = line.split()[-1]
        elif line.startswith("m="):
            parts = line.split()
            current = {
                "kind": parts[0][2:],
                "port": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
                "proto": parts[2] if len(parts) > 2 else "RTP/AVP",
                "payloads": [int(p) for p in parts[3:] if p.isdigit()],
                "ip": session_ip,
                "rtpmap": {},
                "fmtp": {},
            }
            sections.append(current)
        elif current is not None and line.startswith("c=IN IP4 "):
            current["ip"] = line.split()[-1]
        elif current is not None and line.startswith("a=rtpmap:"):
            pt, _, enc = line[9:].partition(" ")
            if pt.isdigit():
                current["rtpmap"][int(pt)] = enc
        elif current is not None and line.startswith("a=fmtp:"):
            pt, _, params = line[7:].partition(" ")
            if pt.isdigit():
                current["fmtp"][int(pt)] = params
    for section in sections:
        if section["kind"] != "video":
            continue
        for pt, enc in section["rtpmap"].items():
            if enc.upper().startswith("H264"):
                section["h264"] = pt
                section["fmtp_h264"] = section["fmtp"].get(pt, "packetization-mode=1;profile-level-id=42e01f")
                break
    return sections, session_ip


def alaw_to_linear(value):
    value ^= 0x55
    sign = value & 0x80
    exponent = (value & 0x70) >> 4
    mantissa = value & 0x0F
    sample = mantissa << 4
    if exponent:
        sample = (sample + 0x108) << (exponent - 1)
    else:
        sample += 8
    return sample if sign else -sample


def linear_to_alaw(sample):
    sample >>= 3
    if sample >= 0:
        mask = 0xD5
    else:
        mask = 0x55
        sample = -sample - 1
    segment = 8
    for index, end in enumerate((0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF)):
        if sample <= end:
            segment = index
            break
    if segment >= 8:
        value = 0x7F
    else:
        value = segment << 4
        shift = 1 if segment < 2 else segment
        value |= (sample >> shift) & 0x0F
    return (value ^ mask) & 0xFF


def ulaw_to_linear(value):
    value = (~value) & 0xFF
    sign = value & 0x80
    exponent = (value >> 4) & 0x07
    mantissa = value & 0x0F
    sample = ((mantissa << 3) + 0x84) << exponent
    sample -= 0x84
    return -sample if sign else sample


def rtp_packet(packet):
    if len(packet) < 12 or (packet[0] >> 6) != 2:
        return None
    cc = packet[0] & 0x0F
    extension = (packet[0] >> 4) & 0x01
    marker = (packet[1] >> 7) & 0x01
    payload_type = packet[1] & 0x7F
    offset = 12 + cc * 4
    if extension:
        if len(packet) < offset + 4:
            return None
        length = struct.unpack("!H", packet[offset + 2:offset + 4])[0]
        offset += 4 + length * 4
    if offset > len(packet):
        return None
    payload = packet[offset:]
    if packet[0] & 0x20:
        if not payload or payload[-1] > len(payload):
            return None
        payload = payload[:-payload[-1]]
    return payload_type, marker, payload


def sprop_nals(fmtp):
    match = re.search(r"sprop-parameter-sets=([^;,\s]+(?:,[^;,\s]+)*)", fmtp or "")
    if not match:
        return []
    nals = []
    for part in match.group(1).split(","):
        try:
            nals.append(base64.b64decode(part))
        except (ValueError, TypeError):
            continue
    return nals


def avc_decoder_config(sps, pps):
    return (
        b"\x01" + sps[1:4] + b"\xff\xe1"
        + struct.pack("!H", len(sps)) + sps
        + b"\x01" + struct.pack("!H", len(pps)) + pps
    )


class Softphone:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((SERVER_IP, 0))
        self.local_ip, self.local_port = self.sock.getsockname()
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
        self.lock = threading.Lock()
        self.running = True

    def contact(self):
        return f"<sip:{SIP_USER}@{self.local_ip}:{self.local_port}>"

    def send(self, payload, addr):
        self.sock.sendto(payload if isinstance(payload, bytes) else payload.encode(), addr)

    def build_register(self, auth_line=None):
        self.reg_cseq += 1
        lines = [
            f"REGISTER sip:{SERVER_IP} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{secrets.token_hex(6)};rport",
            "Max-Forwards: 70",
            f"From: <sip:{SIP_USER}@{SERVER_IP}>;tag={self.reg_tag}",
            f"To: <sip:{SIP_USER}@{SERVER_IP}>",
            f"Call-ID: {self.reg_call_id}",
            f"CSeq: {self.reg_cseq} REGISTER",
            f"Contact: {self.contact()}",
            f"Expires: {EXPIRES}",
            "User-Agent: door-poc",
        ]
        if auth_line:
            lines.append(auth_line)
        lines.extend(["Content-Length: 0", "", ""])
        return "\r\n".join(lines).encode()

    def start_register(self):
        self.next_register = time.time() + EXPIRES / 2
        self.send(self.build_register(), (SERVER_IP, SERVER_PORT))

    def reply(self, addr, headers, status, to_tag, extra, body=b""):
        lines = [f"SIP/2.0 {status}"]
        copied = {"via": False, "from": False, "to": False, "call-id": False, "cseq": False}
        for name, value in headers:
            key = name.lower()
            if key == "via":
                lines.append(f"Via: {value}")
                copied["via"] = True
            elif key == "from":
                lines.append(f"From: {value}")
                copied["from"] = True
            elif key == "to":
                if to_tag and "tag=" not in value.lower():
                    value = f"{value};tag={to_tag}"
                lines.append(f"To: {value}")
                copied["to"] = True
            elif key in ("call-id", "cseq"):
                lines.append(f"{name}: {value}")
                copied[key] = True
        if not all(copied.values()):
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

    def bind_udp(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.local_ip, 0))
        return sock

    def make_sdp(self, offer):
        if self.rtp_sock is None:
            self.rtp_sock = self.bind_udp()
        sections, _ = parse_offer(offer or "")
        wants_video = any(section.get("h264") for section in sections)
        if wants_video and self.video_sock is None:
            self.video_sock = self.bind_udp()
        audio_port = self.rtp_sock.getsockname()[1]
        video_port = self.video_sock.getsockname()[1] if self.video_sock else 0
        lines = [
            "v=0",
            f"o={SIP_USER} 0 0 IN IP4 {self.local_ip}",
            "s=door-poc",
            f"c=IN IP4 {self.local_ip}",
            "t=0 0",
        ]
        answered_video = False
        for section in sections:
            if section["kind"] == "audio":
                lines += [
                    f"m=audio {audio_port} RTP/AVP 8",
                    "a=rtpmap:8 PCMA/8000",
                    "a=sendrecv",
                ]
            elif section["kind"] == "video" and section.get("h264") and not answered_video:
                pt = section["h264"]
                fmtp = section.get("fmtp_h264") or "packetization-mode=1;profile-level-id=42e01f"
                lines += [
                    f"m=video {video_port} RTP/AVP {pt}",
                    f"a=rtpmap:{pt} H264/90000",
                    f"a=fmtp:{pt} {fmtp}",
                    "a=sendrecv",
                ]
                answered_video = True
            else:
                lines.append(f"m={section['kind']} 0 {section['proto']} 0")
        if not any(section["kind"] == "audio" for section in sections):
            lines += [
                f"m=audio {audio_port} RTP/AVP 8",
                "a=rtpmap:8 PCMA/8000",
                "a=sendrecv",
            ]
        return ("\r\n".join(lines) + "\r\n").encode()

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
        samples = bytearray()
        decode = ulaw_to_linear if payload_type == 0 else alaw_to_linear
        for byte in payload:
            samples += struct.pack("<h", decode(byte))
        if samples:
            self.push_media(1, bytes(samples))

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
        nal_type = payload[0] & 0x1F
        nals = []
        if nal_type == 28 and len(payload) >= 2:
            start = payload[1] & 0x80
            end = payload[1] & 0x40
            header = bytes([(payload[0] & 0xE0) | (payload[1] & 0x1F)])
            if start:
                self.fu = bytearray(header)
                self.fu += payload[2:]
            elif self.fu is not None:
                self.fu += payload[2:]
            if end and self.fu is not None:
                nals.append(bytes(self.fu))
                self.fu = None
        elif nal_type == 24:
            index = 1
            while index + 2 <= len(payload):
                size = struct.unpack("!H", payload[index:index + 2])[0]
                index += 2
                nals.append(payload[index:index + size])
                index += size
        elif 1 <= nal_type <= 23:
            nals.append(payload)
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
            if not self.rtp_target:
                self.rtp_target = addr
            if payload_type in (0, 8):
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
        call = {
            "id": call_id,
            "state": "ringing",
            "apartment": apartment_of(headers),
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
            if media_ip and media_port:
                self.rtp_target = (media_ip, media_port)
            self.next_rtp = time.time()
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
                f"BYE sip:{SERVER_IP} SIP/2.0",
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
                "REGISTER", SIP_USER, SIP_PASSWORD, challenge, f"sip:{SERVER_IP}"
            )
            self.send(self.build_register(auth), (SERVER_IP, SERVER_PORT))
            return
        if start.startswith("SIP/2.0 200"):
            with self.lock:
                self.registered = True
                self.error = ""
                self.expires_at = time.time() + EXPIRES
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

    def send_silence(self):
        if not self.rtp_sock or not self.rtp_target:
            return
        if time.time() < self.next_rtp:
            return
        self.next_rtp = time.time() + 0.02
        self.rtp_seq = (self.rtp_seq + 1) & 0xFFFF
        self.rtp_ts = (self.rtp_ts + 160) & 0xFFFFFFFF
        packet = struct.pack("!BBHII", 0x80, 8, self.rtp_seq, self.rtp_ts, self.rtp_ssrc)
        with self.lock:
            if len(self.mic) >= 320:
                pcm = bytes(self.mic[:320])
                del self.mic[:320]
            else:
                pcm = b""
        if len(pcm) == 320:
            packet += bytes(linear_to_alaw(sample) for sample in struct.unpack("<160h", pcm))
        else:
            packet += bytes([0xD5]) * 160
        try:
            self.rtp_sock.sendto(packet, self.rtp_target)
        except OSError:
            pass

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
                self.send_silence()
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

    def snapshot(self):
        with self.lock:
            call = None
            if self.call:
                call = {
                    "id": self.call["id"],
                    "state": self.call["state"],
                    "apartment": self.call["apartment"],
                    "from": self.call["from"],
                    "to": self.call["to"],
                    "params": self.call["params"],
                    "rtp": self.call["rtp"],
                }
            alive = self.registered and time.time() < self.expires_at + 5
            return {
                "registered": alive,
                "error": self.error,
                "user": SIP_USER,
                "server": f"{SERVER_IP}:{SERVER_PORT}",
                "call": call,
                "log": list(self.log),
            }


PHONE = None


def http_digest(method, url, user, password, challenge):
    fields = {}
    for match in re.finditer(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', challenge):
        fields[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
    realm = fields.get("realm", "")
    nonce = fields.get("nonce", "")
    qop = (fields.get("qop") or "").split(",")[0].strip()
    opaque = fields.get("opaque")
    parsed = urlsplit(url)
    uri = parsed.path + (("?" + parsed.query) if parsed.query else "")
    ha1 = hashlib.md5(f"{user}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    cnonce = secrets.token_hex(8)
    nc = "00000001"
    if qop:
        response = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
    else:
        response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
    header = (
        f'Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
        f'algorithm=MD5, response="{response}"'
    )
    if qop:
        header += f', qop={qop}, nc={nc}, cnonce="{cnonce}"'
    if opaque:
        header += f', opaque="{opaque}"'
    return header


def fetch_snapshot():
    def read(response):
        data = response.read()
        if data.startswith(b"\xff\xd8"):
            return data
        return None

    request = urllib.request.Request(SNAPSHOT_URL, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            return read(response)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            return None
        challenge = exc.headers.get("WWW-Authenticate", "")
        if not challenge:
            return None
        authed = urllib.request.Request(
            SNAPSHOT_URL,
            method="GET",
            headers={"Authorization": http_digest("GET", SNAPSHOT_URL, DOOR_USER, DOOR_PASSWORD, challenge)},
        )
        try:
            with urllib.request.urlopen(authed, timeout=4) as response:
                return read(response)
        except (urllib.error.HTTPError, OSError):
            return None
    except OSError:
        return None


def open_door():
    request = urllib.request.Request(DOOR_URL, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            return False, "панель не открыла дверь"
        challenge = exc.headers.get("WWW-Authenticate", "")
        if not challenge:
            return False, "панель не открыла дверь"
        authed = urllib.request.Request(
            DOOR_URL,
            method="GET",
            headers={"Authorization": http_digest("GET", DOOR_URL, DOOR_USER, DOOR_PASSWORD, challenge)},
        )
        try:
            with urllib.request.urlopen(authed, timeout=4) as response:
                status = response.status
        except urllib.error.HTTPError:
            return False, "панель не приняла команду"
        except OSError:
            return False, "панель не ответила"
    except OSError:
        return False, "панель не ответила"
    if status in (200, 204, 302):
        return True, "дверь открыта"
    return False, "панель не открыла дверь"


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
            image = fetch_snapshot()
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
            ok, message = open_door()
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


def load_env():
    global SERVER_IP
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        if line.startswith("ADVERTISE_IP=") and not os.environ.get("ADVERTISE_IP"):
            SERVER_IP = line.split("=", 1)[1].strip()


def main():
    global PHONE
    load_env()
    PHONE = Softphone()
    thread = threading.Thread(target=PHONE.loop, daemon=True)
    thread.start()
    server = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), Handler)
    print(f"Софтфон {SIP_USER} → sip:{SERVER_IP}:{SERVER_PORT}")
    print(f"Откройте http://{HTTP_HOST}:{HTTP_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        PHONE.running = False
        server.shutdown()


if __name__ == "__main__":
    main()
