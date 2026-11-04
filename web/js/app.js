// Home screen: clock, scenes, room tabs and the device grid. Also wires up live
// updates and the idle ambient clock.

import { api, connectEvents } from "./api.js";
import { store, onChange, emit, reload, upsertDevice, command, setRoom, devicesIn } from "./store.js";
import { $, esc, icon, kindIcon, glow, glowVar, statusText, toast } from "./util.js";
import { openDevice, refreshSheet, closeSheet, isSheetOpen } from "./sheet.js";
import { openSettings, isSettingsOpen, refreshSettings } from "./settings.js";
import { applyTransparency } from "./glass.js";
import { openFrame, isFrameOpen } from "./photoframe.js";
import { roomGroups, OTHER } from "./store.js";   // room tabs

const SCENE_ICONS = ["sun", "moon", "film", "sparkle", "coffee", "door"];

// ---------- clock ----------
function renderClock() {
  const now = new Date();
  const h24 = !!store.settings.clock_24h;
  const time = now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: !h24 })
    .replace(/\s?[AP]M$/i, "");
  const date = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  $("#clock-time").textContent = time;
  $("#clock-sub").textContent = date;
  $("#ambient-time").textContent = time;
  const on = [...store.devices.values()].filter((d) => d.state?.on && d.kind === "light").length;
  $("#ambient-sub").textContent = on ? `${date}. ${on} ${on === 1 ? "light is" : "lights are"} on.` : date;
}

// ---------- scenes ----------
function renderScenes() {
  const el = $("#scenes");
  const items = store.scenes.map((s) =>
    `<button class="scene" data-scene="${esc(s.id)}">${icon(SCENE_ICONS.includes(s.icon) ? s.icon : "sparkle")}<span>${esc(s.name)}</span></button>`);
  if (store.devices.size) items.push(`<button class="scene add" data-new-scene>${icon("plus")}<span>New scene</span></button>`);
  el.innerHTML = items.join("");
  el.hidden = !items.length;
}

// ---------- rooms ----------
// One tab per room that has devices, "Other" for devices without a room, and "All"
// for the overview. The chosen tab is remembered (store.setRoom). Swipe the grid
// sideways to go to the next or previous tab.
const roomLabel = (r) => (r === OTHER ? "Other" : r);
const isOn = (d) => !!d.state?.on && d.state?.online !== false;
const canTurnOff = (d) => isOn(d) && d.caps.includes("power") && !d.keep_on;

function tabOrder() {
  const groups = roomGroups();
  return groups.length < 2 ? [] : ["all", ...groups];   // one group: nothing to switch between
}

function renderRooms() {
  const el = $("#rooms");
  const order = tabOrder();
  if (!order.length) { el.hidden = true; if (store.room !== "all") setRoom("all"); return; }
  if (!order.includes(store.room)) return setRoom("all");   // its devices moved away
  el.hidden = false;
  el.innerHTML = order.map((id) => {
    const n = devicesIn(id).filter(isOn).length;
    return `<button class="room" role="tab" data-room="${esc(id)}" aria-selected="${store.room === id}">${
      esc(id === "all" ? "All" : roomLabel(id))}${n ? `<span class="count" aria-label="${n} on">${n}</span>` : ""}</button>`;
  }).join("");
}

// Keep the chosen tab visible in the scrolling bar.
function revealTab() {
  const el = $("#rooms");
  const b = el.querySelector('[aria-selected="true"]');
  if (!b) return;
  const left = b.offsetLeft - 24, right = b.offsetLeft + b.offsetWidth + 24 - el.clientWidth;
  if (el.scrollLeft > left) el.scrollLeft = left;
  else if (el.scrollLeft < right) el.scrollLeft = right;
}

function goRoom(room) {
  if (room === store.room) return;
  const order = tabOrder();
  const dir = Math.sign(order.indexOf(room) - order.indexOf(store.room));
  setRoom(room);
  revealTab();
  // If the page was scrolled down, bring the top of the new room into view.
  const grid = $("#grid");
  const top = grid.getBoundingClientRect().top + window.scrollY - $("#rooms").offsetHeight - 8;
  if (window.scrollY > top) window.scrollTo({ top });
  if (dir && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    grid.animate([{ transform: `translateX(${dir * 28}px)`, opacity: 0.3 }, { transform: "none", opacity: 1 }],
                 { duration: 200, easing: "cubic-bezier(.2,.8,.2,1)" });
  }
}

function stepRoom(step) {
  const order = tabOrder();
  const next = order[order.indexOf(store.room) + step];
  if (next !== undefined) goRoom(next);
}

// Heading above a room's tiles: what's on, and a button to turn that room off.
// In "All" the room name is a button that opens the room's tab.
function roomHead(r, linked) {
  const list = devicesIn(r);
  const on = list.filter(isOn).length;
  const offable = list.filter(canTurnOff).length;
  const name = esc(roomLabel(r));
  const title = linked && tabOrder().length
    ? `<button class="room-title" data-room="${esc(r)}" aria-label="Open ${name}">${name}${icon("right")}</button>`
    : `<h2 class="room-title">${name}</h2>`;
  const status = on ? `${on} of ${list.length} on` : "Everything is off";
  return `<div class="room-head" data-head="${esc(r)}">${title}<span class="room-status">${status}</span>${
    offable ? `<button class="room-off" data-room-off="${esc(r)}">${icon("power")}Turn off</button>` : ""}</div>`;
}

function updateHeads() {
  document.querySelectorAll(".room-head[data-head]").forEach((el) => {
    const tmp = document.createElement("div");
    tmp.innerHTML = roomHead(el.dataset.head, !!el.querySelector("button.room-title"));
    el.replaceWith(tmp.firstElementChild);
  });
}

// Shown with "Other": a nudge to give those devices a room so they get a tab.
function sortNudge() {
  const list = devicesIn(OTHER);
  const msg = store.rooms.length
    ? `${list.length === 1 ? "This device isn't" : "These devices aren't"} in a room yet. Pick a room and it gets its own tab.`
    : "Add rooms like Living room or Kitchen to get a tab for each one.";
  const label = !store.rooms.length ? "Add rooms" : list.length === 1 ? "Choose a room" : "Choose rooms";
  return `<div class="nudge"><p>${msg}</p><button class="btn small" data-sort-rooms>${label}</button></div>`;
}

function openSorting() {
  const list = devicesIn(OTHER);
  if (!store.rooms.length) return openSettings("rooms");
  return list.length === 1 ? openSettings("device", list[0].id) : openSettings("devices");
}

// ---------- tiles ----------
function tileHtml(d) {
  const s = d.state || {};
  const on = !!s.on && s.online !== false;
  const offline = s.online === false || s.needs_pairing;
  const level = d.kind === "light" && s.brightness ? Math.max(0.15, s.brightness / 100) : 1;
  const cls = ["tile", on && "on", offline && "offline", store.busy.has(d.id) && "busy", d.kind === "tv" && "wide"]
    .filter(Boolean).join(" ");
  const tvControls = d.kind === "tv" && on ? `
      <div class="tile-tv-ctl">
        <button data-act="volume_down" aria-label="Volume down">${icon("minus")}</button>
        <button data-act="volume_up" aria-label="Volume up">${icon("plus")}</button>
      </div>` : "";
  return `
    <div class="${cls}" data-id="${esc(d.id)}" role="button" tabindex="0"
         style="--glow:${glowVar(d)};--level:${level}"
         aria-label="${esc(d.name)}, ${esc(statusText(d))}">
      <div class="tile-icon">${icon(offline ? "wifi-off" : kindIcon(d))}</div>
      <button class="tile-more" data-more aria-label="${esc(d.name)} controls">${icon("right")}</button>
      <div class="tile-tv-row">
        <div>
          <div class="tile-name">${esc(d.name)}</div>
          <div class="tile-status">${esc(statusText(d))}</div>
        </div>
        ${tvControls}
      </div>
    </div>`;
}

function renderGrid() {
  const grid = $("#grid");
  if (!store.devices.size) {
    grid.innerHTML = `<div class="empty"><h2>Add your first device</h2>
      <p>Plugs, lights and TVs on your Wi-Fi show up here.</p>
      <button class="btn primary" data-add-device>${icon("plus")}Add a device</button></div>`;
    return;
  }
  const room = store.room;
  const section = (r, linked) => `<section class="room-section" aria-label="${esc(roomLabel(r))}">${roomHead(r, linked)}${
    r === OTHER ? sortNudge() : ""}<div class="tiles">${sortDevices(devicesIn(r)).map(tileHtml).join("")}</div></section>`;
  const html = room === "all" ? roomGroups().map((r) => section(r, true)).join("") : section(room, false);
  grid.innerHTML = html;
}

const KIND_ORDER = { tv: 0, light: 1, switch: 2, fan: 3, plug: 4, other: 5 };
const sortDevices = (list) => list.sort((a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || a.name.localeCompare(b.name));

function updateTile(id) {
  const d = store.devices.get(id);
  const old = document.querySelector(`.tile[data-id="${CSS.escape(id)}"]`);
  if (!d || !old) return renderGrid();
  const tmp = document.createElement("div");
  tmp.innerHTML = tileHtml(d);
  old.replaceWith(tmp.firstElementChild);
}

// The backdrop behind the glass takes on the color of the lights that are on,
// so the whole screen gets warmer as the room does.
function renderAmbience() {
  const root = document.documentElement;
  root.classList.toggle("glass", store.settings.glass_effect !== false);
  root.dataset.bg = store.settings.background || "ocean";
  applyTransparency(store.settings.glass_transparency ?? 45);
  const lit = [...store.devices.values()].filter((d) => d.kind === "light" && d.state?.on && d.state?.online !== false);
  const warmth = Math.min(1, lit.length / 4);
  const avg = lit.length
    ? [0, 1, 2].map((i) => Math.round(lit.reduce((sum, d) => sum + glow(d)[i], 0) / lit.length))
    : [150, 166, 255];
  root.style.setProperty("--room-glow", avg.join(" "));
  root.style.setProperty("--warmth", warmth.toFixed(2));
}

function renderAll() {
  renderAmbience();
  renderClock();
  renderScenes();
  renderRooms();
  renderGrid();
}

// ---------- interactions ----------
function toggle(d) {
  if (d.state?.needs_pairing) return openDevice(d.id);
  if (d.state?.online === false) {
    toast(`${d.name} is offline. ${d.state.error || ""}`.trim(), true);
    return;
  }
  const on = !d.state?.on;
  command(d.id, "power", on, { on });
}

function setupGrid() {
  const grid = $("#grid");
  let pressTimer = null, longPressed = false;

  // Swipe sideways anywhere on the grid to change room tab.
  let start = null, swiped = false;
  grid.addEventListener("pointerdown", (e) => {
    start = { x: e.clientX, y: e.clientY };
    swiped = false;
    const tile = e.target.closest(".tile");
    if (!tile || e.target.closest("button")) return;
    longPressed = false;
    pressTimer = setTimeout(() => { longPressed = true; openDevice(tile.dataset.id); }, 480);
  });
  grid.addEventListener("pointermove", (e) => {
    if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 12) clearTimeout(pressTimer);
  });
  window.addEventListener("pointerup", (e) => {     // window: the finger may end up past the grid's edge
    clearTimeout(pressTimer);
    if (!start) return;
    const dx = e.clientX - start.x, dy = e.clientY - start.y;
    start = null;
    if (Math.abs(dx) > 70 && Math.abs(dx) > 1.5 * Math.abs(dy) && tabOrder().length) {
      swiped = true;
      stepRoom(dx < 0 ? 1 : -1);
    }
  });
  const cancel = () => { clearTimeout(pressTimer); start = null; };
  grid.addEventListener("pointerleave", () => clearTimeout(pressTimer));
  grid.addEventListener("pointercancel", cancel);
  grid.addEventListener("click", (e) => {   // a swipe isn't a tap
    if (swiped) { swiped = false; e.stopImmediatePropagation(); e.preventDefault(); }
  }, { capture: true });
  grid.addEventListener("contextmenu", (e) => e.preventDefault());

  grid.addEventListener("click", (e) => {
    if (e.target.closest("[data-add-device]")) return openSettings("add");
    if (e.target.closest("[data-sort-rooms]")) return openSorting();
    const off = e.target.closest("[data-room-off]");
    if (off) return turnOff(off.dataset.roomOff);
    const title = e.target.closest("[data-room]");
    if (title) return goRoom(title.dataset.room);
    const tile = e.target.closest(".tile");
    if (!tile) return;
    if (longPressed) { longPressed = false; return; }
    const d = store.devices.get(tile.dataset.id);
    if (!d) return;
    if (e.target.closest("[data-more]")) return openDevice(d.id);
    const act = e.target.closest("[data-act]");
    if (act) return command(d.id, act.dataset.act);
    if (d.kind === "tv") return openDevice(d.id);   // never toggle a TV by accident
    toggle(d);
  });
  grid.addEventListener("keydown", (e) => {
    const tile = e.target.closest(".tile");
    if (tile && e.target === tile && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); tile.click(); }
  });
}

// room: null = everything, "" = devices without a room, else that room.
async function turnOff(room = null) {
  try {
    const r = await api.allOff(room);
    toast(r.turned_off ? `Turned off ${r.turned_off} ${r.turned_off === 1 ? "device" : "devices"}` : "Everything is already off");
  } catch (err) { toast(err.message, true); }
}

function setupChrome() {
  const bar = $("#rooms");
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("[data-room]");
    if (b) goRoom(b.dataset.room);
  });
  // The bar sticks to the top while scrolling; give it a glass backing only then.
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(([en]) => bar.classList.toggle("stuck", en.intersectionRatio < 1 && en.boundingClientRect.top < 1),
                             { threshold: [1] }).observe(bar);
  }
  $("#scenes").addEventListener("click", async (e) => {
    if (e.target.closest("[data-new-scene]")) return openSettings("scene-new");
    const b = e.target.closest("[data-scene]");
    if (!b) return;
    b.classList.add("running");
    try {
      const r = await api.runScene(b.dataset.scene);
      const name = store.scenes.find((s) => s.id === b.dataset.scene)?.name || "Scene";
      toast(r.failed.length ? `${name}: ${r.failed.length} device(s) didn't respond` : `${name} is on`, !!r.failed.length);
    } catch (err) { toast(err.message, true); }
    b.classList.remove("running");
  });
  $("#all-off").addEventListener("click", () => turnOff());   // always everything; rooms have their own button
  $("#open-settings").addEventListener("click", () => openSettings());
  $("#open-frame").addEventListener("click", () => { closeSheet(); openFrame(); });
  $("#clock").addEventListener("click", showAmbient);
}

// ---------- idle ambient clock ----------
let lastActivity = Date.now();
function showAmbient() { closeSheet(); $("#ambient").hidden = false; }
function setupIdle() {
  const wake = () => { lastActivity = Date.now(); };
  ["pointerdown", "keydown"].forEach((ev) => document.addEventListener(ev, wake, { capture: true }));
  $("#ambient").addEventListener("pointerdown", (e) => {   // swallow the wake-up touch
    e.preventDefault(); e.stopPropagation();
    $("#ambient").hidden = true;
  });
  setInterval(() => {
    const after = Number(store.settings.dim_after_seconds || 0);
    if (!(after > 0 && Date.now() - lastActivity > after * 1000) || isSettingsOpen()) return;
    if (!$("#ambient").hidden || isFrameOpen()) return;
    const hour = new Date().getHours();
    const night = store.settings.frame_night_clock !== false && (hour >= 22 || hour < 7);
    if (store.settings.idle_screen === "photos" && !night) { closeSheet(); openFrame(); }
    else showAmbient();
  }, 5000);
}

// ---------- live updates ----------
function setupLive() {
  connectEvents((ev) => {
    if (ev.type === "device") upsertDevice(ev.device);
    else if (ev.type === "layout") reload().catch(() => {});
    else if (ev.type === "automation") {
      const ok = String(ev.result).startsWith("ok");
      toast(ok ? `${ev.name}: done` : `${ev.name}: ${ev.result}`, !ok);
      reload().catch(() => {});
    }
  }, (connected) => {
    $("#conn").hidden = connected;
    if (connected) reload().catch(() => {});
  });
}

onChange((what, id) => {
  if (what === "device") {
    updateTile(id);
    renderAmbience();
    refreshSheet(id);
    renderRooms();
    updateHeads();
  } else if (what === "room") {
    renderRooms(); renderGrid();
  } else {
    renderAll();
    refreshSheet();
    refreshSettings();
  }
});

setupGrid();
setupChrome();
setupIdle();
setInterval(renderClock, 10_000);
reload().then(() => { revealTab(); setupLive(); }).catch((e) => { toast(e.message, true); setupLive(); });
