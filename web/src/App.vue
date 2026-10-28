<script setup>
import { computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { beep, startCallMedia } from "./callMedia";
import { startPhone, state } from "./phoneState";

startPhone();
startCallMedia();

const route = useRoute();
const router = useRouter();
let lastRing = "";

const regError = computed(() => {
  if (state.offline) return "нет связи";
  if (state.registered) return "";
  return state.error || "";
});

watch(
  () => (state.call && state.call.state === "ringing" ? state.call.id : ""),
  (id) => {
    if (!id) {
      lastRing = "";
      return;
    }
    if (id === lastRing) return;
    lastRing = id;
    beep();
    if (route.path !== "/") router.push("/");
  },
);
</script>

<template>
  <main>
    <p v-if="regError" class="reg-error">{{ regError }}</p>
    <nav class="nav">
      <router-link to="/">
        Вызов
        <span v-if="state.call" class="live"></span>
      </router-link>
      <router-link to="/settings">Настройки</router-link>
    </nav>
    <router-view />
  </main>
</template>
