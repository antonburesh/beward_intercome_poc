import { createRouter, createWebHistory } from "vue-router";
import CallView from "./views/CallView.vue";
import SettingsView from "./views/SettingsView.vue";

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "call", component: CallView },
    { path: "/settings", name: "settings", component: SettingsView },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
