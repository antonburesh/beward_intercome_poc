<script setup>
import { computed, ref, watch } from "vue";
import { micNote, startMedia } from "../callMedia";
import { state } from "../phoneState";

const doorNote = ref("");
const doorBusy = ref(false);
const shotUrl = ref("");
let shotTries = 0;

const call = computed(() => state.call);
const talking = computed(() => call.value && call.value.state === "talking");
const panelName = computed(() => {
  if (!call.value) return "";
  return call.value.panel_known && call.value.panel ? call.value.panel : "Панель неизвестна";
});
const noteText = computed(() => [micNote.value, doorNote.value].filter(Boolean).join(" · "));

const debugRows = computed(() => {
  if (!call.value) return [];
  const skip = { from: true, to: true };
  const headers = call.value.headers && call.value.headers.length
    ? call.value.headers
    : (call.value.params || []);
  const extra = headers
    .filter((item) => item && !skip[String(item.name || "").toLowerCase()])
    .map((item) => ({ name: item.name, value: item.value }));
  return [
    { name: "Квартира", value: call.value.apartment },
    { name: "Панель", value: panelName.value },
    { name: "Состояние", value: call.value.state },
    { name: "From", value: call.value.from },
    { name: "To", value: call.value.to },
    ...extra,
  ];
});

watch(
  () => (call.value && call.value.state === "ringing" && call.value.panel_known ? call.value.id : ""),
  (id) => {
    shotTries = 0;
    doorNote.value = "";
    shotUrl.value = id ? `/snapshot?id=${encodeURIComponent(id)}` : "";
  },
);

function shotFailed() {
  const id = call.value && call.value.id;
  if (!id || shotTries >= 1) return;
  shotTries += 1;
  setTimeout(() => {
    if (call.value && call.value.id === id && call.value.state === "ringing") {
      shotUrl.value = `/snapshot?id=${encodeURIComponent(id)}&try=1`;
    }
  }, 2000);
}

async function answer() {
  startMedia();
  await fetch("/api-intercom/answer", { method: "POST" });
}

async function reject() {
  const url = talking.value ? "/api-intercom/hangup" : "/api-intercom/reject";
  await fetch(url, { method: "POST" });
}

async function openDoor() {
  doorBusy.value = true;
  doorNote.value = "открываю…";
  try {
    const response = await fetch("/api-intercom/open", { method: "POST" });
    const data = await response.json();
    doorNote.value = data.door || "не удалось открыть";
  } catch {
    doorNote.value = "не удалось открыть";
  }
  doorBusy.value = false;
}
</script>

<template>
  <header v-if="!call" class="hero">
    <p class="eyebrow">Ожидание</p>
    <h2 class="idle-title">Наберите квартиру на домофоне</h2>
    <p class="sub">Вызов придёт на этот экран.</p>
  </header>

  <section v-else class="call">
    <p class="eyebrow">{{ talking ? "Разговор" : "Входящий вызов" }}</p>
    <div class="apt">{{ call.apartment || "?" }}</div>
    <p class="panel">{{ panelName }}</p>
    <canvas v-if="talking" id="cam" class="shot" width="960" height="540"></canvas>
    <img v-else-if="call.panel_known && shotUrl" class="shot" alt="Камера панели" :src="shotUrl" @error="shotFailed">
    <div class="actions">
      <button v-if="!talking" class="answer" type="button" @click="answer">Ответить</button>
      <button class="reject" type="button" @click="reject">{{ talking ? "Завершить" : "Отклонить" }}</button>
      <button class="open" type="button" :disabled="!call.panel_known || doorBusy" @click="openDoor">Открыть дверь</button>
    </div>
    <p class="note">{{ noteText }}</p>
    <section class="debug">
      <div class="debug-title">Отладка</div>
      <div v-for="(row, index) in debugRows" :key="index" class="debug-row">
        <span>{{ row.name }}</span>
        <b>{{ row.value || "—" }}</b>
      </div>
    </section>
  </section>
</template>
