<script setup>
import { ref } from "vue";
import { postJson } from "../api";
import { loadBook } from "../phoneState";

defineProps({
  items: { type: Array, default: () => [] },
});

const apartment = ref("");
const keyNumber = ref("");
const message = ref("");

async function add() {
  message.value = "записываю ключ…";
  try {
    const data = await postJson("/api-intercom/key", {
      apartment: apartment.value.trim(),
      key: keyNumber.value.trim(),
    });
    message.value = data.key || "не удалось записать ключ";
    if (data.ok) {
      apartment.value = "";
      keyNumber.value = "";
      loadBook();
    }
  } catch {
    message.value = "не удалось записать ключ";
  }
}

async function remove(item) {
  if (!confirm(`Удалить ключ квартиры ${item.apartment || ""}?`)) return;
  message.value = "удаляю ключ…";
  try {
    const data = await postJson("/api-intercom/key", { key: item.key, remove: true });
    message.value = data.key || "не удалось удалить ключ";
    if (data.ok) loadBook();
  } catch {
    message.value = "не удалось удалить ключ";
  }
}

async function removeAll() {
  if (!confirm("Удалить все ключи, добавленные с этого экрана? На домофонах их тоже больше не будет.")) return;
  message.value = "удаляю ключи…";
  try {
    const data = await postJson("/api-intercom/key/clear");
    message.value = data.key || "не удалось удалить ключи";
    if (data.ok) loadBook();
  } catch {
    message.value = "не удалось удалить ключи";
  }
}
</script>

<template>
  <form class="card" @submit.prevent="add">
    <h3>Ключ</h3>
    <p class="lead">Номер ключа, который уже есть у жителя. Впишите квартиру и номер ключа — он сразу запишется на все домофоны. Дверь откроется, когда этот ключ поднесут к считывателю.</p>
    <label for="key-apt">Номер квартиры</label>
    <input id="key-apt" v-model="apartment" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="Например, 12">
    <label for="key-number">Номер ключа</label>
    <input id="key-number" v-model="keyNumber" maxlength="20" autocomplete="off" spellcheck="false" placeholder="Номер с ключа">
    <button class="open" type="submit">Добавить ключ</button>
    <p class="note">{{ message }}</p>
    <p v-if="!items.length" class="empty">Ключей с этого экрана пока нет.</p>
    <template v-else>
      <div v-for="item in items" :key="item.key" class="person">
        <div class="who">
          <b>Квартира {{ item.apartment }}</b>
          <span class="keynum">{{ item.key }}</span>
        </div>
        <button class="reject" type="button" @click="remove(item)">Удалить</button>
      </div>
      <button class="danger" type="button" @click="removeAll">Удалить все ключи</button>
    </template>
  </form>
</template>
