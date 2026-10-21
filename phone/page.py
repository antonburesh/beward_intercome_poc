"""Browser page: call screen, panel snapshot, microphone, and door button."""

PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#f0f2f8">
<title>Домофон</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body {
    max-width: 100%;
    overflow-x: hidden;
    background: #f0f2f8;
    color: #1c1c1e;
  }
  body {
    min-height: 100vh;
    font-family: "Golos Text", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-feature-settings: "kern" 1, "liga" 1;
    -webkit-font-smoothing: antialiased;
    -webkit-text-size-adjust: 100%;
  }
  button { font: inherit; touch-action: manipulation; }
  img { max-width: 100%; }
  main {
    width: 100%;
    max-width: 640px;
    margin: 0 auto;
    padding: 16px 16px max(16px, env(safe-area-inset-bottom));
  }
  .reg-error {
    color: #FF3B30;
    font-size: 16px;
    font-weight: 500;
    line-height: 1.35;
    margin-bottom: 12px;
  }
  .eyebrow {
    color: #8e8e93;
    font-size: 16px;
    font-weight: 500;
  }
  .apt {
    font-size: clamp(64px, 22vw, 92px);
    line-height: 0.95;
    font-weight: 700;
    letter-spacing: -0.04em;
    margin: 6px 0 8px;
  }
  .panel {
    font-size: 19px;
    font-weight: 600;
    margin-bottom: 16px;
  }
  .shot, #cam {
    display: block;
    width: 100%;
    height: auto;
    max-height: 52vh;
    object-fit: contain;
    background: #0f0f12;
    border-radius: 24px;
    margin-bottom: 16px;
  }
  .actions { display: flex; flex-direction: column; gap: 10px; }
  .row { display: flex; gap: 10px; }
  button {
    min-height: 48px;
    width: 100%;
    border: 0;
    border-radius: 14px;
    padding: 12px 16px;
    font-size: 19px;
    font-weight: 600;
    cursor: pointer;
  }
  .row button { flex: 1 1 0; min-width: 0; }
  button:active { transform: scale(0.98); }
  button:disabled { background: #c6c6c8; color: #fff; cursor: default; transform: none; }
  .answer { background: #34C759; color: #fff; }
  .reject { background: #FF3B30; color: #fff; }
  .open { background: #007AFF; color: #fff; }
  .note {
    min-height: 1.3em;
    margin-top: 12px;
    color: #8e8e93;
    font-size: 16px;
    line-height: 1.35;
  }
  .idle-title {
    margin: 8px 0 10px;
    font-size: clamp(30px, 8vw, 36px);
    font-weight: 700;
    letter-spacing: -0.03em;
    line-height: 1.15;
  }
  .sub { color: #8e8e93; font-size: 18px; }
  .debug { margin-top: 18px; }
  .debug-title {
    color: #8e8e93;
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 8px;
  }
  .debug-row {
    display: grid;
    grid-template-columns: minmax(96px, 38%) 1fr;
    gap: 8px;
    margin: 4px 0;
    font-size: 15px;
    line-height: 1.35;
    overflow-wrap: anywhere;
  }
  .debug-row span { color: #8e8e93; }
  .debug-row b { font-weight: 500; }
  .face { margin-top: 28px; }
  .face label {
    display: block;
    margin: 14px 0 6px;
    color: #8e8e93;
    font-size: 16px;
    font-weight: 500;
  }
  .face input {
    display: block;
    width: 100%;
    min-height: 48px;
    border: 0;
    border-radius: 14px;
    background: #fff;
    padding: 12px 14px;
    font-size: 18px;
    color: #1c1c1e;
  }
  .face button { margin-top: 14px; }
  .face .note { margin-top: 10px; }
</style>
</head>
<body>
<main>
  <p class="reg-error" id="reg-error" hidden></p>
  <section class="screen" id="stage"></section>
</main>
<script>
const stage = document.getElementById("stage");
const regError = document.getElementById("reg-error");
let lastRing = "";
let audioCtx;
let doorNote = "";

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

function noteText() {
  const parts = [];
  if (micNote) parts.push(micNote);
  if (doorNote) parts.push(doorNote);
  return parts.join(" · ");
}

function showNote() {
  const el = document.getElementById("note");
  if (el) el.textContent = noteText();
}

function row(name, value) {
  const text = value ? esc(value) : "—";
  return `<div class="debug-row"><span>${esc(name)}</span><b>${text}</b></div>`;
}

function debugBlock(call, panelName) {
  const skip = { from: true, to: true };
  const headers = (call.headers && call.headers.length) ? call.headers : (call.params || []);
  const extra = headers
    .filter(item => item && !skip[String(item.name || "").toLowerCase()])
    .map(item => row(item.name, item.value))
    .join("");
  return `
    <section class="debug">
      <div class="debug-title">Отладка</div>
      ${row("Квартира", call.apartment)}
      ${row("Панель", panelName)}
      ${row("Состояние", call.state)}
      ${row("From", call.from)}
      ${row("To", call.to)}
      ${extra}
    </section>`;
}

function setRegError(text) {
  regError.textContent = text || "";
  regError.hidden = !text;
}

function render(data) {
  const call = data.call;
  if (!call) {
    lastRing = "";
    doorNote = "";
    stopMic();
    stage.innerHTML = `
      <p class="eyebrow">Ожидание</p>
      <h2 class="idle-title">Наберите квартиру на домофоне</h2>
      <p class="sub">Вызов придёт на этот экран.</p>
      <form class="face" id="face-form">
        <label for="face-apt">Квартира</label>
        <input id="face-apt" name="apartment" inputmode="numeric" autocomplete="off" maxlength="4">
        <label for="face-file">Фото</label>
        <input id="face-file" name="photo" type="file" accept="image/*">
        <p class="sub">Снимок с телефона уменьшится сам: панели нужен JPG от 300 пикселей и не больше 100 КБ.</p>
        <button class="open" type="submit">Загрузить фото</button>
        <p class="note" id="face-msg"></p>
      </form>`;
    document.getElementById("face-form").onsubmit = (event) => {
      event.preventDefault();
      uploadFace();
    };
    return;
  }
  if (call.state === "ringing" && call.id !== lastRing) {
    lastRing = call.id;
    doorNote = "";
    beep();
  }
  const talking = call.state === "talking";
  const panelName = call.panel_known && call.panel ? call.panel : "Панель неизвестна";
  const shot = talking
    ? `<canvas id="cam" class="shot" width="960" height="540"></canvas>`
    : (call.panel_known
      ? `<img id="shot" class="shot" alt="Камера панели" src="/snapshot?t=${Date.now()}">`
      : "");
  const actions = talking
    ? `<button class="reject" id="reject" type="button">Завершить</button>`
    : `<div class="row">
         <button class="answer" id="answer" type="button">Ответить</button>
         <button class="reject" id="reject" type="button">Отклонить</button>
       </div>`;
  stage.innerHTML = `
    <p class="eyebrow">${talking ? "Разговор" : "Входящий вызов"}</p>
    <div class="apt">${esc(call.apartment || "?")}</div>
    <p class="panel">${esc(panelName)}</p>
    ${shot}
    <div class="actions">
      ${actions}
      <button class="open" id="open" type="button" ${call.panel_known ? "" : "disabled"}>Открыть дверь</button>
    </div>
    <p class="note" id="note">${esc(noteText())}</p>
    ${debugBlock(call, panelName)}`;
  if (!talking && call.panel_known) shotAt = Date.now();
  if (!talking) {
    document.getElementById("answer").onclick = () => { startMedia(); post("/api/answer"); };
  } else {
    startMedia();
  }
  document.getElementById("reject").onclick = () => post(talking ? "/api/hangup" : "/api/reject");
  if (call.panel_known) document.getElementById("open").onclick = openDoor;
}

async function uploadFace() {
  const note = document.getElementById("face-msg");
  const apartment = (document.getElementById("face-apt").value || "").trim();
  const file = document.getElementById("face-file").files[0];
  if (!apartment || !file) {
    if (note) note.textContent = "укажите квартиру и фото";
    return;
  }
  const body = new FormData();
  body.append("apartment", apartment);
  body.append("photo", file, file.name || "face.jpg");
  if (note) note.textContent = "загружаю…";
  try {
    const res = await fetch("/api/face", { method: "POST", body });
    const data = await res.json();
    if (note) note.textContent = data.face || "не удалось загрузить";
  } catch (e) {
    if (note) note.textContent = "не удалось загрузить";
  }
}

async function post(url) {
  await fetch(url, { method: "POST" });
  refresh();
}

async function openDoor() {
  const button = document.getElementById("open");
  if (!button) return;
  button.disabled = true;
  doorNote = "открываю…";
  showNote();
  try {
    const res = await fetch("/api/open", { method: "POST" });
    const data = await res.json();
    doorNote = data.door || "не удалось открыть";
  } catch (e) {
    doorNote = "не удалось открыть";
  }
  showNote();
  button.disabled = false;
}

let mediaStarted = false;
let audioNext = 0;

let micNote = "";
let micStream = null;
let micPc = null;

function setMicNote(text) {
  micNote = text;
  showNote();
}

function startMedia() {
  if (mediaStarted) return;
  mediaStarted = true;
  audioCtx = new AudioContext();
  audioCtx.resume();
  readMedia();
  startMic();
}

function waitIce(pc) {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise(resolve => {
    const done = () => {
      if (pc.iceGatheringState === "complete") {
        pc.removeEventListener("icegatheringstatechange", done);
        resolve();
      }
    };
    pc.addEventListener("icegatheringstatechange", done);
    setTimeout(resolve, 1500);
  });
}

function startMic() {
  if (!navigator.mediaDevices || micStream) return;
  setMicNote("микрофон включается");
  navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    video: false
  }).then(async stream => {
    if (!mediaStarted) {
      stream.getTracks().forEach(track => track.stop());
      return;
    }
    micStream = stream;
    const pc = new RTCPeerConnection();
    micPc = pc;
    stream.getTracks().forEach(track => pc.addTrack(track, stream));
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitIce(pc);
    const res = await fetch("/api/webrtc", {
      method: "POST",
      headers: { "Content-Type": "application/sdp" },
      body: pc.localDescription.sdp
    });
    if (!res.ok) throw new Error("webrtc");
    const answer = await res.text();
    if (micPc !== pc) return;
    await pc.setRemoteDescription({ type: "answer", sdp: answer });
    setMicNote("микрофон включён");
  }).catch(() => setMicNote("нет доступа к микрофону"));
}

function stopMic() {
  if (micStream) micStream.getTracks().forEach(track => track.stop());
  if (micPc) micPc.close();
  micPc = null;
  micStream = null;
  micNote = "";
  mediaStarted = false;
  if (videoDecoder && videoDecoder.state !== "closed") {
    try { videoDecoder.close(); } catch (e) {}
  }
  videoDecoder = null;
  videoCodec = "";
  videoDescription = null;
  pendingVideo = [];
  videoTime = 0;
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

let videoDecoder = null;
let videoCodec = "";
let videoDescription = null;
let pendingVideo = [];
let videoTime = 0;

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
    setRegError(data.registered ? "" : (data.error || ""));
    const key = viewKey(data);
    if (key !== lastView) {
      lastView = key;
      render(data);
    }
    if (data.call && data.call.state === "ringing") refreshShot();
  } catch (e) {
    setRegError("нет связи");
  }
}

refresh();
setInterval(refresh, 700);
</script>
</body>
</html>
"""
