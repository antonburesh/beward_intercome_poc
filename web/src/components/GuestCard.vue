<script setup>
import { ref } from "vue";
import { postJson } from "../api";
import { loadBook, now } from "../phoneState";

defineProps({
  guests: { type: Array, default: () => [] },
  panels: { type: Array, default: () => [] },
});

const apartment = ref("");
const where = ref("all");
const minutes = ref("30");
const message = ref("");

function leftLabel(expires) {
  const left = Math.max(0, Math.round((Number(expires) * 1000 - now.value) / 1000));
  if (!left) return "истекает";
  const whole = Math.floor(left / 60);
  const seconds = String(left % 60).padStart(2, "0");
  return `ещё ${whole}:${seconds}`;
}

async function issue() {
  const payload = { apartment: apartment.value.trim(), minutes: Number(minutes.value) };
  if (where.value === "all") payload.all = true;
  else payload.panel = where.value;
  message.value = "записываю код…";
  try {
    const data = await postJson("/api-intercom/guest", payload);
    message.value = data.guest || "не удалось записать код";
    if (data.ok) {
      apartment.value = "";
      loadBook();
    }
  } catch {
    message.value = "не удалось записать код";
  }
}

async function revoke(number) {
  try {
    const data = await postJson("/api-intercom/guest", { apartment: number, remove: true });
    message.value = data.guest || "";
    if (data.ok) loadBook();
  } catch {
    message.value = "";
  }
}

async function revokeAll() {
  if (!confirm("Удалить все временные коды? Гости больше не смогут войти по ним.")) return;
  message.value = "снимаю коды…";
  try {
    const data = await postJson("/api-intercom/guest/clear");
    message.value = data.guest || "не удалось снять коды";
    if (data.ok) loadBook();
  } catch {
    message.value = "не удалось снять коды";
  }
}
</script>

<template>
  <form class="card" @submit.prevent="issue">
    <h3>Временный код</h3>
    <p class="lead">Код для гостя. На домофоне он набирает эти цифры и нажимает кнопку вызова. Можно записать код на один домофон или сразу на все. На одну квартиру можно выдать только один код. Когда время кончится, код пропадёт сам и на двери снова будет прежний.</p>
    <label for="guest-apt">Номер квартиры</label>
    <input id="guest-apt" v-model="apartment" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="Например, 12">
    <label for="guest-panel">Куда записать код</label>
    <select id="guest-panel" v-model="where">
      <option value="all">На все домофоны</option>
      <option v-for="panel in panels" :key="panel.ip" :value="panel.ip">{{ panel.name || panel.ip || "Домофон" }}</option>
    </select>
    <label for="guest-min">Сколько код будет работать</label>
    <select id="guest-min" v-model="minutes">
      <option value="15">15 минут</option>
      <option value="30">30 минут</option>
      <option value="60">1 час</option>
      <option value="180">3 часа</option>
    </select>
    <button class="open" type="submit">Дать код гостю</button>
    <p class="note">{{ message }}</p>
    <p v-if="!guests.length" class="empty">Сейчас нет действующих кодов.</p>
    <template v-else>
      <div v-for="item in guests" :key="item.apartment" class="person">
        <div class="who">
          <b>Квартира {{ item.apartment }}</b>
          <span class="left">{{ leftLabel(item.expires) }}</span>
          <span>{{ item.doors || "Все домофоны" }}</span>
        </div>
        <b class="code">{{ item.code }}</b>
        <button class="reject" type="button" @click="revoke(item.apartment)">Удалить код</button>
      </div>
      <button class="danger" type="button" @click="revokeAll">Удалить все коды</button>
    </template>
  </form>
</template>
