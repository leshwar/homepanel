// Client-side state. The server is the source of truth; this mirrors it and
// applies optimistic updates so taps feel instant.

import { api } from "./api.js";
import { storage, toast } from "./util.js";

export const store = {
  devices: new Map(),
  rooms: [],
  scenes: [],
  settings: {},
  adapters: [],
  automations: [],
  presence: [],
  demo: false,
  room: storage.get("room", "all"),
  busy: new Set(),
};

const listeners = new Set();
export const onChange = (fn) => listeners.add(fn);
export const emit = (what, id) => listeners.forEach((fn) => fn(what, id));

export function applySnapshot(s) {
  store.devices = new Map(s.devices.map((d) => [d.id, d]));
  store.rooms = s.rooms;
  store.scenes = s.scenes;
  store.settings = s.settings;
  store.adapters = s.adapters;
  store.automations = s.automations || [];
  store.presence = s.presence || [];
  store.demo = s.demo;
  store.inContainer = !!s.in_container;
  if (store.room !== "all" && !store.rooms.includes(store.room)) store.room = "all";
  emit("all");
}

export async function reload() {
  applySnapshot(await api.state());
}

export function upsertDevice(d) {
  if (store.busy.has(d.id)) {           // keep the optimistic value until our own command returns
    const local = store.devices.get(d.id);
    if (local) d.state = { ...d.state, ...pick(local.state, ["on", "brightness", "color", "color_temp", "color_mode", "volume", "muted"]) };
  }
  store.devices.set(d.id, d);
  emit("device", d.id);
}

const pick = (o, keys) => Object.fromEntries(keys.filter((k) => k in o).map((k) => [k, o[k]]));

// Send a command with an optimistic state change. Reverts and shows the error if it fails.
export async function command(id, action, value, optimistic = {}) {
  const d = store.devices.get(id);
  if (!d) return;
  const before = { ...d.state };
  d.state = { ...d.state, ...optimistic };
  store.busy.add(id);
  emit("device", id);
  try {
    const updated = await api.command(id, action, value);
    store.busy.delete(id);
    upsertDevice(updated);
  } catch (e) {
    store.busy.delete(id);
    d.state = before;
    emit("device", id);
    toast(e.message, true);
  }
}

export function setRoom(room) {
  store.room = room;
  storage.set("room", room);
  emit("room");
}

export const devicesIn = (room) =>
  [...store.devices.values()].filter((d) => room === "all" || d.room === room);
