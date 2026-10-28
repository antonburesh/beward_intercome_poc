<script setup>
import { ref } from "vue";
import { postJson } from "../api";
import { loadFaces } from "../phoneState";

defineProps({
  faces: { default: null },
  panelCount: { type: Number, default: 0 },
});

const apartment = ref("");
const message = ref("");
const fileInput = ref(null);

function faceLabel(item) {
  const number = String(item.apartment || "");
  if (/^\d+$/.test(number)) return `Квартира ${number}`;
  return number || "Фото без подписи";
}

function faceSrc(item) {
  return `/face?panel=${encodeURIComponent(item.panel)}&id=${encodeURIComponent(item.id)}`;
}

async function upload() {
  const file = fileInput.value && fileInput.value.files[0];
  if (!apartment.value.trim() || !file) {
    message.value = "укажите квартиру и фото";
    return;
  }
  const body = new FormData();
  body.append("apartment", apartment.value.trim());
  body.append("photo", file, file.name || "face.jpg");
  message.value = "загружаю…";
  try {
    const response = await fetch("/api/face", { method: "POST", body });
    const data = await response.json();
    message.value = data.face || "не удалось загрузить";
    if (data.ok) {
      apartment.value = "";
      fileInput.value.value = "";
      loadFaces();
    }
  } catch {
    message.value = "не удалось загрузить";
  }
}

async function remove(item) {
  const label = faceLabel(item);
  if (!confirm(`Удалить фотографию: ${label}?`)) return;
  message.value = "удаляю фотографию…";
  try {
    const data = await postJson("/api/face/delete", { panel: item.panel, id: item.id });
    message.value = data.face || "не удалось удалить фото";
    if (data.ok) loadFaces();
  } catch {
    message.value = "не удалось удалить фото";
  }
}

async function removeAll() {
  if (!confirm("Удалить все фотографии на всех домофонах? Вход по лицу перестанет работать, пока фото не добавят снова.")) return;
  message.value = "удаляю фотографии…";
  try {
    const data = await postJson("/api/face/delete", { all: true });
    message.value = data.face || "не удалось удалить фото";
    if (data.ok) loadFaces();
  } catch {
    message.value = "не удалось удалить фото";
  }
}
</script>

<template>
  <form class="card" @submit.prevent="upload">
    <h3>Вход по лицу</h3>
    <p class="lead">Фотография жителя. Человек подходит к камере домофона, панель узнаёт его и открывает дверь. Снимок сохраняется на каждом домофоне. Телефон сам уменьшит фото до нужного размера.</p>
    <label for="face-apt">Номер квартиры</label>
    <input id="face-apt" v-model="apartment" inputmode="numeric" autocomplete="off" maxlength="4" placeholder="Например, 12">
    <label for="face-file">Фотография жителя</label>
    <input id="face-file" ref="fileInput" type="file" accept="image/*">
    <button class="open" type="submit">Добавить фотографию</button>
    <p class="note">{{ message }}</p>
    <p v-if="faces && !faces.length" class="empty">Фотографий пока нет. Добавьте снимок жителя — дверь откроется, когда панель его узнает.</p>
    <template v-else-if="faces && faces.length">
      <div v-for="item in faces" :key="`${item.panel}-${item.id}`" class="person">
        <img class="thumb" :alt="faceLabel(item)" :src="faceSrc(item)">
        <div class="who">
          <b>{{ faceLabel(item) }}</b>
          <span v-if="panelCount > 1">{{ item.panel_name || "Панель" }}</span>
        </div>
        <button class="reject" type="button" @click="remove(item)">Удалить фото</button>
      </div>
      <button class="danger" type="button" @click="removeAll">Удалить все фотографии</button>
    </template>
  </form>
</template>
