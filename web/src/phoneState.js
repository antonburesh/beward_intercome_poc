import { reactive, ref } from "vue";

export const state = reactive({
  registered: false,
  error: "",
  offline: false,
  call: null,
  guests: [],
  faces: null,
  keys: [],
  panel_count: 0,
  panels: [],
});

export const now = ref(Date.now());

let started = false;
let events = null;

function applyCall(data) {
  state.offline = false;
  state.registered = !!data.registered;
  state.error = data.error || "";
  state.call = data.call || null;
}

export function startPhone() {
  if (started) return;
  started = true;
  events = new EventSource("/api-intercom/events");
  events.onmessage = (message) => {
    try {
      applyCall(JSON.parse(message.data));
    } catch {
      state.offline = true;
    }
  };
  events.onerror = () => {
    state.offline = true;
  };
  setInterval(() => {
    now.value = Date.now();
  }, 1000);
}

export async function loadBook() {
  const response = await fetch("/api-intercom/book", { cache: "no-store" });
  const data = await response.json();
  state.guests = data.guests || [];
  state.keys = data.keys || [];
  state.panels = data.panels || [];
  state.panel_count = data.panel_count || 0;
}

export async function loadFaces() {
  const response = await fetch("/api-intercom/faces", { cache: "no-store" });
  const data = await response.json();
  state.faces = data.faces || [];
}
