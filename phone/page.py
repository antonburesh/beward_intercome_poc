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
    max-width: 1240px;
    margin: 0 auto;
    padding: 16px 16px max(16px, env(safe-area-inset-bottom));
  }
  .hero, .call { text-align: center; }
  .call {
    width: min(100%, 720px);
    margin: 0 auto;
  }
  .call .debug, .call .note { text-align: left; }
  .board {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    align-items: stretch;
    gap: 16px;
    margin-top: 18px;
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
    margin: 0 auto 16px;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 10px;
  }
  .actions button { flex: 1 1 200px; max-width: 280px; width: auto; }
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
  .card {
    flex: 1 1 300px;
    width: 100%;
    max-width: 400px;
    margin-top: 0;
    padding: 16px 16px 18px;
    background: #fff;
    border-radius: 22px;
    text-align: left;
  }
  .card h3 {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.02em;
  }
  .card .lead {
    margin-top: 6px;
    color: #636366;
    font-size: 16px;
    line-height: 1.4;
  }
  .card label {
    display: block;
    margin: 14px 0 6px;
    color: #636366;
    font-size: 16px;
    font-weight: 600;
  }
  .card input, .card select {
    display: block;
    width: 100%;
    min-height: 48px;
    border: 0;
    border-radius: 14px;
    background: #f0f2f8;
    padding: 12px 14px;
    font-size: 18px;
    color: #1c1c1e;
  }
  .card .open { margin-top: 14px; }
  .card .note { margin-top: 10px; }
  .empty { margin-top: 14px; color: #8e8e93; font-size: 16px; }
  .person {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    align-items: center;
    gap: 8px 12px;
    margin-top: 10px;
    padding: 12px;
    background: #f0f2f8;
    border-radius: 16px;
  }
  .thumb {
    width: 64px;
    height: 64px;
    border-radius: 14px;
    object-fit: cover;
    background: #d1d1d6;
    flex: 0 0 auto;
  }
  .person .who { flex: 1 1 140px; min-width: 0; }
  .person .who b { display: block; font-size: 18px; font-weight: 600; }
  .person .who span, .person .left { color: #8e8e93; font-size: 15px; }
  .person .code {
    font-size: 26px;
    font-weight: 700;
    letter-spacing: 0.06em;
  }
  .person .keynum {
    font-size: 16px;
    font-weight: 600;
    letter-spacing: 0.04em;
  }
  .person button, .danger {
    width: auto;
    flex: 0 0 auto;
    min-width: 132px;
    min-height: 44px;
    margin: 0;
  }
  .danger {
    width: 100%;
    margin-top: 14px;
    background: transparent;
    color: #FF3B30;
    border: 1px solid #FF3B30;
  }
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
let keyNote = "";

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
      <header class="hero">
        <p class="eyebrow">Ожидание</p>
        <h2 class="idle-title">Наберите квартиру на домофоне</h2>
        <p class="sub">Вызов придёт на этот экран.</p>
      </header>
      ${settingsCards(data)}`;
    bindSettings();
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
    : `<button class="answer" id="answer" type="button">Ответить</button>
       <button class="reject" id="reject" type="button">Отклонить</button>`;
  stage.innerHTML = `
    <section class="call">
      <p class="eyebrow">${talking ? "Разговор" : "Входящий вызов"}</p>
      <div class="apt">${esc(call.apartment || "?")}</div>
      <p class="panel">${esc(panelName)}</p>
      ${shot}
      <div class="actions">
        ${actions}
        <button class="open" id="open" type="button" ${call.panel_known ? "" : "disabled"}>Открыть дверь</button>
      </div>
      <p class="note" id="note">${esc(noteText())}</p>
      ${debugBlock(call, panelName)}
    </section>
    ${settingsCards(data)}`;
  if (!talking && call.panel_known) shotAt = Date.now();
  if (!talking) {
    document.getElementById("answer").onclick = () => { startMedia(); post("/api/answer"); };
  } else {
    startMedia();
  }
  document.getElementById("reject").onclick = () => post(talking ? "/api/hangup" : "/api/reject");
  if (call.panel_known) document.getElementById("open").onclick = openDoor;
  bindSettings();
}

function faceLabel(item) {
  const apartment = String(item.apartment || "");
  if (/^\d+$/.test(apartment)) return "Квартира " + apartment;
  return apartment || "Фото без подписи";
}

function settingsCards(data) {
  return `<div class="board">${faceCard(data.faces, data.panel_count)}${guestBlock(data.guests, data.panels)}${keyCard(data.keys)}</div>`;
}

function faceCard(faces, panelCount) {
  const items = (faces || []).map(item => `
    <div class="person">
      <img class="thumb" alt="${esc(faceLabel(item))}" src="/face?panel=${encodeURIComponent(item.panel)}&id=${encodeURIComponent(item.id)}">
      <div class="who">
        <b>${esc(faceLabel(item))}</b>
        ${Number(panelCount) > 1 ? `<span>${esc(item.panel_name || "Панель")}</span>` : ""}
      </div>
      <button class="reject" type="button" data-action="face" data-id="${esc(item.id)}" data-panel="${esc(item.panel)}" data-label="${esc(faceLabel(item))}">Удалить фото</button>
    </div>`).join("");
  const clear = items
    ? `<button class="danger" id="clear-faces" type="button">Удалить все фотографии</button>`
    : `<p class="empty">Фотографий пока нет. Добавьте снимок жителя — дверь откроется, когда панель его узнает.</p>`;
  return `
    <form class="card" id="face-form">
      <h3>Вход по лицу</h3>
      <p class="lead">Фотография жителя. Человек подходит к камере домофона, панель узнаёт его и открывает дверь. Снимок сохраняется на каждом домофоне. Телефон сам уменьшит фото до нужного размера.</p>
      <label for="face-apt">Номер квартиры</label>
      <input id="face-apt" name="apartment" inputmode="numeric" autocomplete="off" maxlength="4" placeholder="Например, 12">
      <label for="face-file">Фотография жителя</label>
      <input id="face-file" name="photo" type="file" accept="image/*">
      <button class="open" type="submit">Добавить фотографию</button>
      <p class="note" id="face-msg"></p>
      ${items}
      ${clear}
    </form>`;
}

function guestBlock(guests, panels) {
  const list = Array.isArray(panels) ? panels : [];
  const options = ['<option value="all" selected>На все домофоны</option>']
    .concat(list.map(item => `<option value="${esc(item.ip)}">${esc(item.name || item.ip || "Домофон")}</option>`))
    .join("");
  const items = (guests || []).map(item => `
    <div class="person">
      <div class="who">
        <b>Квартира ${esc(item.apartment)}</b>
        <span class="left" data-expires="${Number(item.expires) * 1000}"></span>
        <span>${esc(item.doors || "Все домофоны")}</span>
      </div>
      <b class="code">${esc(item.code)}</b>
      <button class="reject" type="button" data-action="revoke" data-apt="${esc(item.apartment)}">Удалить код</button>
    </div>`).join("");
  const clear = items
    ? `<button class="danger" id="clear-guests" type="button">Удалить все коды</button>`
    : `<p class="empty">Сейчас нет действующих кодов.</p>`;
  return `
    <form class="card" id="guest-form">
      <h3>Временный код</h3>
      <p class="lead">Код для гостя. На домофоне он набирает эти цифры и нажимает кнопку вызова. Можно записать код на один домофон или сразу на все. На одну квартиру можно выдать только один код. Когда время кончится, код пропадёт сам и на двери снова будет прежний.</p>
      <label for="guest-apt">Номер квартиры</label>
      <input id="guest-apt" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="Например, 12">
      <label for="guest-panel">Куда записать код</label>
      <select id="guest-panel">
        ${options}
      </select>
      <label for="guest-min">Сколько код будет работать</label>
      <select id="guest-min">
        <option value="15">15 минут</option>
        <option value="30" selected>30 минут</option>
        <option value="60">1 час</option>
        <option value="180">3 часа</option>
      </select>
      <button class="open" type="submit">Дать код гостю</button>
      <p class="note" id="guest-msg"></p>
      ${items}
      ${clear}
    </form>`;
}

function keyCard(keys) {
  const items = (keys || []).map(item => `
    <div class="person">
      <div class="who">
        <b>Квартира ${esc(item.apartment)}</b>
        <span class="keynum">${esc(item.key)}</span>
      </div>
      <button class="reject" type="button" data-action="key" data-key="${esc(item.key)}" data-apt="${esc(item.apartment)}">Удалить</button>
    </div>`).join("");
  const clear = items
    ? `<button class="danger" id="clear-keys" type="button">Удалить все ключи</button>`
    : `<p class="empty">Ключей с этого экрана пока нет.</p>`;
  return `
    <form class="card" id="key-form">
      <h3>Ключ</h3>
      <p class="lead">Номер ключа, который уже есть у жителя. Впишите квартиру и номер ключа — он сразу запишется на все домофоны. Дверь откроется, когда этот ключ поднесут к считывателю.</p>
      <label for="key-apt">Номер квартиры</label>
      <input id="key-apt" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="Например, 12">
      <label for="key-number">Номер ключа</label>
      <input id="key-number" maxlength="20" autocomplete="off" spellcheck="false" placeholder="Номер с ключа">
      <button class="open" type="submit">Добавить ключ</button>
      <p class="note" id="key-msg">${esc(keyNote)}</p>
      ${items}
      ${clear}
    </form>`;
}

function bindSettings() {
  const face = document.getElementById("face-form");
  if (face) face.onsubmit = (event) => { event.preventDefault(); uploadFace(); };
  const guest = document.getElementById("guest-form");
  if (guest) guest.onsubmit = issueGuest;
  document.querySelectorAll("[data-action='revoke']").forEach(button => {
    button.onclick = () => revokeGuest(button.getAttribute("data-apt"));
  });
  document.querySelectorAll("[data-action='face']").forEach(button => {
    button.onclick = () => deleteFace(button.getAttribute("data-panel"), button.getAttribute("data-id"), button.getAttribute("data-label"));
  });
  const clearFaces = document.getElementById("clear-faces");
  if (clearFaces) clearFaces.onclick = deleteAllFaces;
  const clearGuests = document.getElementById("clear-guests");
  if (clearGuests) clearGuests.onclick = deleteAllGuests;
  const keyForm = document.getElementById("key-form");
  if (keyForm) keyForm.onsubmit = addKey;
  document.querySelectorAll("[data-action='key']").forEach(button => {
    button.onclick = () => deleteKey(button.getAttribute("data-key"), button.getAttribute("data-apt"));
  });
  const clearKeys = document.getElementById("clear-keys");
  if (clearKeys) clearKeys.onclick = deleteAllKeys;
  tickGuests();
}

async function addKey(event) {
  event.preventDefault();
  const apartment = (document.getElementById("key-apt").value || "").trim();
  const key = (document.getElementById("key-number").value || "").trim();
  keyNote = "записываю ключ…";
  try {
    const res = await fetch("/api/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apartment, key })
    });
    const data = await res.json();
    keyNote = data.key || "не удалось записать ключ";
  } catch (e) {
    keyNote = "не удалось записать ключ";
  }
  lastView = "";
  refresh();
}

async function deleteKey(key, apartment) {
  if (!confirm("Удалить ключ квартиры " + (apartment || "") + "?")) return;
  keyNote = "удаляю ключ…";
  try {
    const res = await fetch("/api/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, remove: true })
    });
    const data = await res.json();
    keyNote = data.key || "не удалось удалить ключ";
  } catch (e) {
    keyNote = "не удалось удалить ключ";
  }
  lastView = "";
  refresh();
}

async function deleteAllKeys() {
  if (!confirm("Удалить все ключи, добавленные с этого экрана? На домофонах их тоже больше не будет.")) return;
  keyNote = "удаляю ключи…";
  try {
    const res = await fetch("/api/key/clear", { method: "POST" });
    const data = await res.json();
    keyNote = data.key || "не удалось удалить ключи";
  } catch (e) {
    keyNote = "не удалось удалить ключи";
  }
  lastView = "";
  refresh();
}

async function issueGuest(event) {
  event.preventDefault();
  const note = document.getElementById("guest-msg");
  const apartment = (document.getElementById("guest-apt").value || "").trim();
  const minutes = Number(document.getElementById("guest-min").value);
  const where = (document.getElementById("guest-panel") || {}).value || "all";
  const payload = { apartment, minutes };
  if (where === "all") payload.all = true;
  else payload.panel = where;
  if (note) note.textContent = "записываю код…";
  try {
    const res = await fetch("/api/guest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (note) note.textContent = data.guest || "не удалось записать код";
  } catch (e) {
    if (note) note.textContent = "не удалось записать код";
  }
  lastView = "";
  refresh();
}

async function revokeGuest(apartment) {
  await fetch("/api/guest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apartment, remove: true })
  });
  lastView = "";
  refresh();
}

async function deleteAllGuests() {
  if (!confirm("Удалить все временные коды? Гости больше не смогут войти по ним.")) return;
  const note = document.getElementById("guest-msg");
  if (note) note.textContent = "снимаю коды…";
  try {
    const res = await fetch("/api/guest/clear", { method: "POST" });
    const data = await res.json();
    if (note) note.textContent = data.guest || "не удалось снять коды";
  } catch (e) {
    if (note) note.textContent = "не удалось снять коды";
  }
  lastView = "";
  refresh();
}

async function deleteFace(panel, id, label) {
  if (!confirm("Удалить фотографию: " + (label || "эта запись") + "?")) return;
  const note = document.getElementById("face-msg");
  if (note) note.textContent = "удаляю фотографию…";
  try {
    const res = await fetch("/api/face/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ panel, id })
    });
    const data = await res.json();
    if (note) note.textContent = data.face || "не удалось удалить фото";
  } catch (e) {
    if (note) note.textContent = "не удалось удалить фото";
  }
  lastView = "";
  refresh();
}

async function deleteAllFaces() {
  if (!confirm("Удалить все фотографии на всех домофонах? Вход по лицу перестанет работать, пока фото не добавят снова.")) return;
  const note = document.getElementById("face-msg");
  if (note) note.textContent = "удаляю фотографии…";
  try {
    const res = await fetch("/api/face/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ all: true })
    });
    const data = await res.json();
    if (note) note.textContent = data.face || "не удалось удалить фото";
  } catch (e) {
    if (note) note.textContent = "не удалось удалить фото";
  }
  lastView = "";
  refresh();
}

function tickGuests() {
  document.querySelectorAll("[data-expires]").forEach(el => {
    const left = Math.max(0, Math.round((Number(el.dataset.expires) - Date.now()) / 1000));
    const minutes = Math.floor(left / 60);
    const seconds = String(left % 60).padStart(2, "0");
    el.textContent = left ? "ещё " + minutes + ":" + seconds : "истекает";
  });
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
  lastView = "";
  refresh();
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
setInterval(tickGuests, 1000);
</script>
</body>
</html>
"""
