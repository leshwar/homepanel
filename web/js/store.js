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
  me: null,            // the signed-in profile (js/auth.js); null while signed out
  profiles: [],        // every profile, for admins (Settings → Profiles)
  demo: false,
  room: storage.get("room", "all"),
  view: storage.get("view", "home"),     // "home" (widgets) or "rooms" (device tiles); remembered per screen
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
  store.me = s.me || null;
  store.profiles = s.profiles || [];
  store.demo = s.demo;
  store.inContainer = !!s.in_container;
  if (store.room !== "all" && store.room !== OTHER && !store.rooms.includes(store.room)) store.room = "all";
  emit("all");
}

export async function reload() {
  applySnapshot(await api.state());
}

export function upsertDevice(d) {
  if (store.busy.has(d.id)) {           // keep the optimistic value until our own command returns
    const local = store.devices.get(d.id);
    if (local) d.state = { ...d.state, ...pick(local.state, ["on", "brightness", "color", "color_temp", "color_mode", "volume", "muted",
                                                         "effect", "music", "segments", "toggles"]) };
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
    return true;
  } catch (e) {
    store.busy.delete(id);
    d.state = before;
    emit("device", id);
    toast(e.message, true);
    return false;
  }
}

export function setView(view) {
  store.view = view === "rooms" ? "rooms" : "home";
  storage.set("view", store.view);
  emit("view");
}

export function setRoom(room) {
  store.room = room;
  storage.set("room", room);
  emit("room");
}

// Devices with no room (or a room that was deleted) are grouped as "Other"; its
// tab and the server's all-off both use "" for it.
export const OTHER = "";
export const roomOf = (d) => (store.rooms.includes(d.room) ? d.room : OTHER);
export const devicesIn = (room) =>
  [...store.devices.values()].filter((d) => room === "all" || roomOf(d) === room);

// The groups that get a tab, in display order: rooms that have devices, then "Other".
export function roomGroups() {
  const groups = store.rooms.filter((r) => devicesIn(r).length);
  if (devicesIn(OTHER).length) groups.push(OTHER);
  return groups;
}
