// The main screen: navigation (a room rail on wide screens, a dock and room tabs on
// phones), the Home page (js/home.js) and the Rooms view with device tiles. Also
// live updates, the idle resting clock and the sky background.

import { api, connectEvents } from "./api.js";
import { setMarkup, updateRoomCounts } from "./render.js";
import { store, onChange, reload, upsertDevice, setRoom, setView, devicesIn, applySnapshot } from "./store.js";
import { $, esc, icon, glow, toast } from "./util.js";
import { refreshSheet, closeSheet } from "./sheet.js";
import { openSettings, isSettingsOpen, refreshSettings, closeSettings } from "./settings.js";
import { applyTransparency } from "./glass.js";
import { openFrame, isFrameOpen } from "./photoframe.js";
import { roomGroups, OTHER } from "./store.js";   // room tabs
import { renderAmbient } from "./clockfaces.js";
import { svg, roomIcon } from "./icons.js";
import { tileHtml, updateTiles, bindTiles } from "./tiles.js";
import { applySky, refreshWeather, onWeather } from "./sky.js";
import { applyWallpaper } from "./wallpaper.js";
import { renderHome, tickHome, refreshHomeParts, setupHome, startEditing, isEditing, stopEditing } from "./home.js";
import { startAuth } from "./auth.js";
import "./profiles.js";      // Settings → Profiles
import { setupVoice, closeVoice, isVoiceOpen } from "./voice.js";

const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const wide = () => matchMedia("(min-width: 768px)").matches;

// ---------- clock ----------
function renderClock() {
  const now = new Date();
  const h24 = !!store.settings.clock_24h;
  $("#clock-time").textContent = now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: !h24 });
  renderAmbient(now);
  tickHome(now);
}

// ---------- rooms ----------
// One tab per room that has devices, "Other" for devices without a room, and "All"
// for the overview. The chosen tab is remembered (store.setRoom). Swipe the grid
// sideways to go to the next or previous tab.
const roomLabel = (r) => (r === OTHER ? "Other" : r);
const isOn = (d) => !!d.state?.on && d.state?.online !== false;
const canTurnOff = (d) => isOn(d) && d.caps.includes("power") && !d.keep_on;

// All rooms first, then each room that has devices this profile can see (in the
// order set in Settings → Rooms), then "Other" if some device has no room.
function tabOrder() {
  const groups = roomGroups();
  return groups.length ? ["all", ...groups] : [];
}

const onCount = (r) => devicesIn(r).filter(isOn).length;
const countBadge = (room) => `<span class="count" data-room-count="${esc(room)}" hidden></span>`;

// Phones and the portrait panel: a row of text tabs over the tiles.
function renderTabs() {
  const el = $("#rooms");
  const order = tabOrder();
  el.hidden = !order.length || store.view !== "rooms";
  setMarkup(el, order.map((id) =>
    `<button class="room" role="tab" data-room="${esc(id)}" aria-selected="${store.room === id}">${
      esc(id === "all" ? "All" : roomLabel(id))}${countBadge(id)}</button>`).join(""));
  updateRoomCounts(el, onCount);
}

// iPad and the landscape panel: Home plus every room down the left side.
function renderRail() {
  const order = tabOrder();
  const home = store.view === "home";
  const item = (id) => {
    const sel = !home && store.room === id;
    return `<button class="rail-item" role="tab" data-room="${esc(id)}" aria-selected="${sel}">${roomIcon(id)}<span>${
      esc(id === "all" ? "All rooms" : roomLabel(id))}</span>${countBadge(id)}</button>`;
  };
  setMarkup($("#rail"), `
    <div class="rail-head">${esc(store.settings.home_name || "Home")}</div>
    <button class="rail-item" data-nav="home" aria-current="${home ? "page" : "false"}">${svg("home")}<span>Home</span></button>
    <p class="rail-label">Rooms</p>
    <div class="rail-rooms" role="tablist" aria-orientation="vertical" aria-label="Rooms">${order.map(item).join("")}</div>
    <div class="rail-foot">
      <button class="rail-item" data-add-device>${icon("plus")}<span>Add a device</span></button>
      <button class="rail-item" data-open-settings>${svg("settings")}<span>Settings</span></button>
    </div>`);
  updateRoomCounts($("#rail"), onCount);
}

function renderDock() {
  document.querySelectorAll("#dock [data-nav]").forEach((b) =>
    b.setAttribute("aria-current", b.dataset.nav === store.view ? "page" : "false"));
}

function renderNav() {
  const order = tabOrder();
  if (store.room !== "all" && !order.includes(store.room)) { setRoom("all"); return; }   // its devices moved away
  renderTabs();
  renderRail();
  renderDock();
}

// Title over the content: the greeting on Home, the room on wide screens.
function renderTitle() {
  const home = store.view === "home";
  const all = [...store.devices.values()];
  const room = store.room;
  let title = store.settings.home_name || "Home", sub;
  if (home) {
    const on = all.filter(isOn).length;
    sub = on ? `${on} ${on === 1 ? "thing is" : "things are"} on` : "Everything is off";
  } else {
    title = room === "all" ? "All rooms" : roomLabel(room);   // the page is the room, on every screen size
    const list = devicesIn(room);
    const on = list.filter(isOn).length;
    sub = on ? `${on} of ${list.length} on` : list.length ? "Everything is off" : "";
  }
  $("#title").textContent = title;
  $("#subtitle").textContent = sub;
  $("#edit-home").hidden = !home;
  $("#clock").hidden = home && store.settings.home_layout?.widgets?.some((w) => w.type === "clock" && !w.hidden);
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
  const fromHome = store.view === "home";
  if (fromHome) { setRoom(room); setView("rooms"); return; }
  if (room === store.room) return;
  const order = tabOrder();
  const dir = Math.sign(order.indexOf(room) - order.indexOf(store.room));
  setRoom(room);
  revealTab();
  const grid = $("#grid");
  const top = grid.getBoundingClientRect().top + window.scrollY - ($("#rooms").offsetHeight || 0) - 8;
  if (window.scrollY > top) window.scrollTo({ top });
  if (dir && !reduceMotion()) {
    grid.animate([{ transform: `translate${wide() ? "Y" : "X"}(${dir * 24}px)`, opacity: 0.3 }, { transform: "none", opacity: 1 }],
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
  return `<div class="room-head${linked ? "" : " single"}" data-head="${esc(r)}">${title}<span class="room-status">${status}</span>${
    offable ? `<button class="room-off" data-room-off="${esc(r)}">${icon("power")}Turn off</button>` : ""}</div>`;
}

function updateHeads() {
  document.querySelectorAll(".room-head[data-head]").forEach((el) => {
    const tmp = document.createElement("div");
    tmp.innerHTML = roomHead(el.dataset.head, !el.classList.contains("single"));
    if (el.outerHTML !== tmp.firstElementChild.outerHTML) el.replaceWith(tmp.firstElementChild);
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
function renderGrid() {
  const grid = $("#grid");
  if (!store.devices.size) {
    grid.innerHTML = store.me && store.me.role !== "admin"
      ? `<div class="empty"><h2>No devices yet</h2><p>Ask an admin to share some devices with your profile.</p></div>`
      : `<div class="empty"><h2>Add your first device</h2>
      <p>Plugs, lights and TVs on your Wi-Fi show up here.</p>
      <button class="btn primary" data-add-device>${icon("plus")}Add a device</button></div>`;
    return;
  }
  const room = store.room;
  const section = (r, linked) => `<section class="room-section" aria-label="${esc(roomLabel(r))}">${roomHead(r, linked)}${
    r === OTHER ? sortNudge() : ""}<div class="tiles">${sortDevices(devicesIn(r)).map((d) => tileHtml(d)).join("")}</div></section>`;
  const html = room === "all" ? roomGroups().map((r) => section(r, true)).join("") : section(room, false);
  grid.innerHTML = html;
}

const KIND_ORDER = { tv: 0, speaker: 1, light: 2, switch: 3, fan: 4, plug: 5, vacuum: 6, other: 7 };
const sortDevices = (list) => list.sort((a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || a.name.localeCompare(b.name));

// The backdrop behind the glass takes on the color of the lights that are on,
// so the whole screen gets warmer as the room does.
function renderAmbience() {
  const root = document.documentElement;
  root.classList.toggle("glass", store.settings.glass_effect !== false);
  root.dataset.bg = store.settings.background || "sky";
  applyTransparency(store.settings.glass_transparency ?? 45);
  applySky();
  applyWallpaper();
  const lit = [...store.devices.values()].filter((d) => d.kind === "light" && d.state?.on && d.state?.online !== false);
  const warmth = Math.min(1, lit.length / 4);
  const avg = lit.length
    ? [0, 1, 2].map((i) => Math.round(lit.reduce((sum, d) => sum + glow(d)[i], 0) / lit.length))
    : [150, 166, 255];
  root.style.setProperty("--room-glow", avg.join(" "));
  root.style.setProperty("--warmth", warmth.toFixed(2));
}

// Show Home or Rooms. `enter` plays the short entrance animation.
function renderView(enter = false) {
  const home = store.view === "home";
  document.documentElement.dataset.view = store.view;
  $("#home").hidden = !home;
  $("#grid").hidden = home;
  renderNav();
  renderTitle();
  if (home) renderHome({ enter });
  else {
    renderGrid();
    if (enter && !reduceMotion()) {
      $("#grid").animate([{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "none" }],
                         { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
  }
}

function renderAll() {
  renderAmbience();
  refreshWeather();
  renderView();
  renderClock();
}

// ---------- interactions ----------
function setupGrid() {
  const grid = $("#grid");

  // Swipe sideways anywhere on the grid to change room tab.
  let start = null, swiped = false;
  grid.addEventListener("pointerdown", (e) => {
    start = { x: e.clientX, y: e.clientY };
    swiped = false;
  });
  window.addEventListener("pointerup", (e) => {     // window: the finger may end up past the grid's edge
    if (!start) return;
    const dx = e.clientX - start.x, dy = e.clientY - start.y;
    start = null;
    if (Math.abs(dx) > 70 && Math.abs(dx) > 1.5 * Math.abs(dy) && tabOrder().length) {
      swiped = true;
      stepRoom(dx < 0 ? 1 : -1);
    }
  });
  grid.addEventListener("pointercancel", () => { start = null; });
  grid.addEventListener("click", (e) => {   // a swipe isn't a tap
    if (swiped) { swiped = false; e.stopImmediatePropagation(); e.preventDefault(); }
  }, { capture: true });
  bindTiles(grid);

  grid.addEventListener("click", (e) => {
    if (e.target.closest("[data-sort-rooms]")) return openSorting();
    const off = e.target.closest("[data-room-off]");
    if (off) return turnOff(off.dataset.roomOff);
    const title = e.target.closest("[data-room]");
    if (title) return goRoom(title.dataset.room);
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
  // The tab bar sticks to the top while scrolling; give it a glass backing only then.
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(([en]) => bar.classList.toggle("stuck", en.intersectionRatio < 1 && en.boundingClientRect.top < 1),
                             { threshold: [1] }).observe(bar);
  }
  // Navigation and shared buttons, wherever they are (rail, dock, tabs, empty states).
  document.addEventListener("click", (e) => {
    const t = e.target;
    if (!t.closest("#app")) return;
    const nav = t.closest("[data-nav]");
    if (nav) {
      if (nav.dataset.nav === store.view && nav.dataset.nav === "rooms" && store.room !== "all") return goRoom("all");
      return setView(nav.dataset.nav);
    }
    const room = t.closest("#rooms [data-room], #rail [data-room]");
    if (room) return goRoom(room.dataset.room);
    if (t.closest("[data-open-settings]")) return openSettings();
    if (t.closest("[data-add-device]")) return openSettings("add");
  });
  $("#all-off").addEventListener("click", () => turnOff());   // always everything; rooms have their own button
  $("#open-frame").addEventListener("click", () => { closeSheet(); openFrame(); });
  $("#clock").addEventListener("click", showAmbient);
  $("#edit-home").addEventListener("click", startEditing);
  matchMedia("(min-width: 768px)").addEventListener?.("change", () => { renderNav(); renderTitle(); });
}

// ---------- idle ambient clock ----------
let lastActivity = Date.now();
function showAmbient() { closeSheet(); closeVoice(); $("#ambient").hidden = false; renderAmbient(); }
function setupIdle() {
  const wake = () => { lastActivity = Date.now(); };
  ["pointerdown", "keydown"].forEach((ev) => document.addEventListener(ev, wake, { capture: true }));
  $("#ambient").addEventListener("pointerdown", (e) => {   // swallow the wake-up touch
    e.preventDefault(); e.stopPropagation();
    $("#ambient").hidden = true;
  });
  setInterval(() => {
    const after = Number(store.settings.dim_after_seconds || 0);
    if (!(after > 0 && Date.now() - lastActivity > after * 1000) || isSettingsOpen() || isEditing() || isVoiceOpen()) return;
    if (!$("#ambient").hidden || isFrameOpen()) return;
    const hour = new Date().getHours();
    const night = store.settings.frame_night_clock !== false && (hour >= 22 || hour < 7);
    if (store.settings.idle_screen === "photos" && !night) { closeSheet(); openFrame(); }
    else showAmbient();
  }, 5000);
}

// ---------- live updates ----------
let live = null;
function setupLive() {
  if (live) return live.restart();     // a new profile: a new stream
  live = connectEvents((ev) => {
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
    const d = store.devices.get(id);
    const shown = updateTiles(id);
    // A poll for a device in another room must not rebuild the visible grid.
    if (!shown && store.view === "rooms" && devicesIn(store.room).some((dev) => dev.id === id)) renderGrid();
    renderAmbience();
    refreshSheet(id);
    renderNav();
    renderTitle();
    updateHeads();
    if (d) refreshHomeParts(["rooms"]);
  } else if (what === "room") {
    renderNav(); renderTitle();
    if (store.view === "rooms") renderGrid();
  } else if (what === "view") {
    window.scrollTo({ top: 0 });
    renderView(true);
  } else {
    renderAll();
    refreshSheet();
    refreshSettings();
  }
});

onWeather(() => refreshHomeParts(["weather"]));

setupGrid();
setupChrome();
setupVoice();
setupHome({ goRoom, showAmbient });
bindTiles($("#home"), { enabled: () => !isEditing(), onLongPress: () => startEditing() });
setupIdle();
setInterval(renderClock, 10_000);
setInterval(() => { applySky(); refreshWeather(); }, 60_000);

// Sign-in first (js/auth.js). Signed out, the panel keeps only its look (background,
// clock face) so the resting clock and photo frame still work on a locked wall panel.
function closeAll() {
  closeSheet();
  closeSettings();
  if (isEditing()) stopEditing();
}
startAuth({
  signedIn: () => reload().then(() => { revealTab(); setupLive(); }).catch((e) => { toast(e.message, true); setupLive(); }),
  signedOut: (display) => {
    live?.stop();
    closeAll();
    $("#home").innerHTML = "";          // the view that isn't showing keeps its last render
    $("#grid").innerHTML = "";
    applySnapshot({ devices: [], rooms: [], scenes: [], settings: { ...display, home_layout: { version: 1, widgets: [] } },
                    adapters: [], demo: store.demo });
  },
  closeAll,
});
