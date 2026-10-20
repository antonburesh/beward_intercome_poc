"""Browser page: call screen, panel name, camera, microphone, and door button."""

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
    const panelName = call.panel_known && call.panel ? call.panel : "панель неизвестна";
    const params = (call.params || []).map(p => row(p.name, p.value)).join("");
    stage.innerHTML = `
      <div>
        <div class="eyebrow">${title}</div>
        <div class="apt">${esc(call.apartment || "?")}</div>
        <p class="sub">${call.state === "talking" ? "Трубка снята" : "Квартира вызывает"} · ${esc(panelName)}</p>
        <div class="params">
          ${row("Панель", panelName)}
          ${row("From", call.from)}
          ${row("To", call.to)}
          ${params}
        </div>
        ${call.state === "ringing" && call.panel_known ? `<img id="shot" alt="Камера панели" src="/snapshot?t=${Date.now()}">` : ""}
        ${call.state === "talking" ? `<canvas id="cam" width="960" height="540"></canvas><div class="rtp" id="mic-note">${esc(micNote)}</div><div class="rtp" id="rtp-count">RTP от домофона: ${call.rtp} пакетов</div>` : ""}
      </div>
      <div>
        <div class="actions">
          <button class="answer" id="answer" ${call.state === "ringing" ? "" : "disabled"}>Ответить</button>
          <button class="reject" id="reject">${call.state === "talking" ? "Завершить" : "Отклонить"}</button>
          <button class="open" id="open" type="button" ${call.panel_known ? "" : "disabled"}>Открыть дверь</button>
        </div>
        <p class="door-msg" id="door-msg">${call.panel_known ? "" : "панель неизвестна"}</p>
      </div>`;
    document.getElementById("answer").onclick = () => { startMedia(); post("/api/answer"); };
    if (call.state === "ringing" && call.panel_known) shotAt = Date.now();
    if (call.state === "talking") startMedia();
    document.getElementById("reject").onclick = () => post(call.state === "talking" ? "/api/hangup" : "/api/reject");
    if (call.panel_known) document.getElementById("open").onclick = openDoor;
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
