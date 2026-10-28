<script setup>
import { onMounted, onUnmounted } from "vue";
import FaceCard from "./FaceCard.vue";
import GuestCard from "./GuestCard.vue";
import KeyCard from "./KeyCard.vue";
import { loadBook, loadFaces, state } from "../phoneState";

let timer = 0;

onMounted(() => {
  loadBook();
  loadFaces();
  timer = setInterval(loadBook, 5000);
});

onUnmounted(() => {
  clearInterval(timer);
});
</script>

<template>
  <div class="board">
    <FaceCard :faces="state.faces" :panel-count="state.panel_count" />
    <GuestCard :guests="state.guests" :panels="state.panels" />
    <KeyCard :items="state.keys" />
  </div>
</template>
