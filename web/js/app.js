// The main screen: navigation (a room rail on wide screens, a dock and room tabs on
// phones), the Home page (js/home.js) and the Rooms view with device tiles. Also
// live updates, the idle resting clock and the sky background.

import { api, connectEvents } from "./api.js";
import { setMarkup, updateRoomCounts, syncAttributes } from "./render.js";
import { store, onChange, reload, upsertDevice, setRoom, setView, devicesIn, applySnapshot, addRoom } from "./store.js";
import { $, esc, icon, glow, roomStatus, toast } from "./util.js";
import { refreshSheet, closeSheet } from "./sheet.js";
import { openSettings, isSettingsOpen, refreshSettings, closeSettings, roomAddForm } from "./settings.js";
import { applyTransparency } from "./glass.js";
import { openFrame, isFrameOpen } from "./photoframe.js";
import { roomGroups, OTHER } from "./store.js";   // room tabs
import { renderAmbient } from "./clockfaces.js";
import { svg, roomIcon } from "./icons.js";
import { updateTiles, bindTiles } from "./tiles.js";
import { applySky, refreshWeather, onWeather } from "./sky.js";
import { applyWallpaper } from "./wallpaper.js";
import { renderHome, tickHome, refreshHomeParts, setupHome, startEditing, isEditing, stopEditing } from "./home.js";
import { startAuth } from "./auth.js";
import "./profiles.js";      // Settings → Profiles
import { roomTiles, roomLayoutKey, setupRoomEditor, startRoomEditing, stopRoomEditing, isRoomEditing } from "./room-layout.js";
import { roomGrip, roomEditButton, roomNameField, roomNameHelp, editableRoomNames, syncRoomSorters, isSortingRooms, isEditingRooms, isEditingRoomName, canLeaveRoomNames, toggleRoomEditing } from "./room-sort.js";
import { applyTypography } from "./typography.js";
import { setupVoice, closeVoice, isVoiceOpen } from "./voice.js";

const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const wide = () => matchMedia("(min-width: 768px)").matches;
let addingRoom = false, savingRooms = false;
let newRoomName = "", addingProfile = null, navFocus = null;
let roomTransition = null;
const editing = () => isEditing() || isRoomEditing();
function canNavigate(allowRoomNames = false) {
  if (savingRooms || (addingRoom && (!allowRoomNames || newRoomName.trim()))) {
    toast("Add or cancel the new room first.", true); return false;
  }
  if (isSortingRooms()) { toast("Finish moving the room first."); return false; }
  if (!allowRoomNames && !canLeaveRoomNames()) return false;
  if (!editing()) return true;
  toast("Save or cancel your layout changes first.");
  return false;
}

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

// Phones and portrait panels: one room picker, or the same inline Edit list.
function renderTabs() {
  const el = $("#rooms");
  const order = tabOrder();
  const admin = store.me?.role === "admin";
  const editingRooms = admin && isEditingRooms();
  el.hidden = !editingRooms || store.view !== "rooms";
  el.classList.toggle("editing-rooms", editingRooms);
  el.setAttribute("role", editingRooms ? "group" : "tablist");
  const tab = (id) =>
    `<button class="room" data-room="${esc(id)}" aria-current="${store.room === id ? "page" : "false"}">${
      esc(id === "all" ? "All rooms" : roomLabel(id))}${countBadge(id)}</button>`;
  const actual = order.filter((r) => r !== "all" && r !== OTHER);
  const names = editingRooms ? editableRoomNames(actual) : actual;
  setMarkup(el, `${order.includes("all") ? tab("all") : ""}
    <div class="room-sort-tabs" ${admin ? 'data-room-sort="vertical"' : ""}>${names.map((r) =>
      `<div class="room-tab${editingRooms ? " editing-rooms" : ""}" data-sort-room="${esc(r)}">${editingRooms ? roomNameField(r) + roomGrip(r) : tab(r)}</div>`).join("")}</div>
    ${order.includes(OTHER) ? tab(OTHER) : ""}`);
  updateRoomCounts(el, onCount);
  $("#room-tools").hidden = store.view !== "rooms";
  const choices = order.length ? order : ["all"];
  setMarkup($("#room-tools"), `${editingRooms ? "<span>Rooms</span>" : `<label class="room-picker-label">
    <span class="visually-hidden">Room</span><select data-room-picker aria-label="Room">${choices.map(room =>
      `<option value="${esc(room)}" ${room === store.room ? "selected" : ""}>${esc(room === "all" ? "All rooms" : roomLabel(room))}</option>`).join("")}</select></label>`}
    ${admin ? roomEditButton() : ""}${editingRooms ? '<button class="btn small" data-add-room>Add room</button>' + roomNameHelp() : ""}
    ${addingRoom && editingRooms ? roomAddForm("nav-add-room", newRoomName) : ""}`);
  syncRoomSorters();
}

// iPad and the landscape panel: Home plus every room down the left side.
function renderRail() {
  const order = tabOrder();
  const home = store.view === "home";
  const admin = store.me?.role === "admin";
  const editingRooms = admin && isEditingRooms();
  const actual = order.filter((r) => r !== "all" && r !== OTHER);
  const names = editingRooms ? editableRoomNames(actual) : actual;
  if (!editingRooms) addingRoom = false;
  const item = (id) => {
    const sel = !home && store.room === id;
    return `<button class="rail-item" role="tab" data-room="${esc(id)}" aria-selected="${sel}">${roomIcon(id)}<span>${
      esc(id === "all" ? "All rooms" : roomLabel(id))}</span>${countBadge(id)}</button>`;
  };
  setMarkup($("#rail"), `
    <button class="rail-item" data-nav="home" aria-current="${home ? "page" : "false"}">${svg("home")}<span>Home</span></button>
    <div class="rail-room-heading"><p class="rail-label">Rooms</p>${admin ? roomEditButton() : ""}</div>
    ${editingRooms ? roomNameHelp() : ""}
    <div class="rail-rooms" role="tablist" aria-orientation="vertical" aria-label="Rooms">
      ${order.includes("all") ? item("all") : ""}
      <div class="room-sort-rail" ${admin ? 'data-room-sort="vertical"' : ""}>${names.map((room) =>
        `<div class="rail-room-row${editingRooms ? " editing-rooms" : ""}" data-sort-room="${esc(room)}">${editingRooms ? roomNameField(room) + roomGrip(room) : item(room)}</div>`).join("")}</div>
      ${order.includes(OTHER) ? item(OTHER) : ""}
    </div>
    <div class="rail-foot">
      ${editingRooms ? `<button class="rail-item" data-add-room aria-expanded="${addingRoom}">${icon("plus")}<span>Add room</span></button>` : ""}
      ${addingRoom ? roomAddForm("rail-add-room", newRoomName) : ""}
      <button class="rail-item" data-add-device>${icon("plus")}<span>Add a device</span></button>
      <button class="rail-item" data-open-settings>${svg("settings")}<span>Settings</span></button>
    </div>`);
  updateRoomCounts($("#rail"), onCount);
  syncRoomSorters();
}

function renderDock() {
  document.querySelectorAll("#dock [data-nav]").forEach((b) =>
    b.setAttribute("aria-current", b.dataset.nav === store.view ? "page" : "false"));
}

function readNavFocus(el) {
  if (!el?.closest("#rail, #rooms, #room-tools, #dock")) return null;
  const kind = el.matches("[data-room-name]") ? "name" : el.matches("[data-room-add] input") ? "new"
    : el.hasAttribute("data-room-grip") ? "grip" : el.hasAttribute("data-edit-rooms") ? "edit"
      : el.hasAttribute("data-room-picker") || el.hasAttribute("data-room") ? "room"
        : el.hasAttribute("data-add-room") ? "add" : el.hasAttribute("data-nav") ? el.dataset.nav
          : el.hasAttribute("data-open-settings") ? "settings" : el.hasAttribute("data-add-device") ? "device" : null;
  return kind ? { kind, element: el, profile: store.me?.id, room: el.dataset.roomName ?? el.dataset.roomGrip ?? el.dataset.room ?? store.room,
    start: el.selectionStart, end: el.selectionEnd } : null;
}

function restoreNavFocus(focus, reveal = false) {
  if (!focus || focus.profile !== store.me?.id) return;
  const nav = wide() ? "#rail" : "#rooms", tools = wide() ? "#rail" : "#room-tools";
  const selector = focus.kind === "name" ? `${nav} [data-room-name="${CSS.escape(focus.room)}"]`
    : focus.kind === "grip" ? `${nav} [data-room-grip="${CSS.escape(focus.room)}"]`
      : focus.kind === "new" ? `${tools} [data-room-add] input`
        : focus.kind === "room" ? wide() ? `#rail [data-room="${CSS.escape(focus.room)}"]` : "[data-room-picker]"
          : focus.kind === "edit" ? `${tools} [data-edit-rooms]`
            : focus.kind === "add" ? `${tools} [data-add-room]`
              : `${wide() ? "#rail" : "#dock"} [${focus.kind === "settings" ? "data-open-settings"
                : focus.kind === "device" ? "data-add-device" : `data-nav="${focus.kind}"`}]`;
  const target = document.querySelector(selector);
  if (!target || !target.getClientRects().length) return;
  if (document.activeElement !== target) target.focus({ preventScroll: true });
  if (typeof focus.start === "number" && (target.selectionStart !== focus.start || target.selectionEnd !== focus.end)) {
    target.setSelectionRange(focus.start, focus.end);
  }
  if (reveal) target.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function renderNav(force = false) {
  if (store.me?.role !== "admin" || (addingProfile && addingProfile !== store.me.id)) {
    addingRoom = false; newRoomName = ""; addingProfile = null;
  }
  if (!force && (isSortingRooms() || isEditingRoomName() || addingRoom)) return;
  const focus = readNavFocus(document.activeElement);
  const order = tabOrder();
  if (store.room !== "all" && !order.includes(store.room)) { setRoom("all"); return; }   // its devices moved away
  renderTabs();
  renderRail();
  renderDock();
  restoreNavFocus(focus);
}

// Home keeps an accessible heading and visible status; rooms show their titles.
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
  // Still tappable (the panel's picture can be stale), but it stops looking like something is on.
  $("#all-off").classList.toggle("idle", !all.some(canTurnOff));
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
  if (!canNavigate()) return;
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
    roomTransition?.cancel();
    roomTransition = grid.animate([{ transform: `translate${wide() ? "Y" : "X"}(${dir * 24}px)`, opacity: 0.3 }, { transform: "none", opacity: 1 }],
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
  const status = roomStatus(list.length, on);
  // In "All" an empty room is one line with its own Add button, not a full empty page.
  const add = linked && !list.length
    ? `<button class="btn small" data-add-device aria-label="Add a device to ${name}">${icon("plus")}Add a device</button>` : "";
  return `<div class="room-head${linked ? "" : " single"}" data-head="${esc(r)}">${title}<span class="room-status">${status}</span>${
    offable ? `<button class="room-off" data-room-off="${esc(r)}">${icon("power")}Turn off</button>` : ""}
    ${list.length ? `<button class="btn small" data-edit-room="${esc(r)}" aria-label="Edit ${name} tiles">${svg("pencil")}Edit tiles</button>` : add}</div>`;
}

function updateHeads() {
  document.querySelectorAll(".room-head[data-head]").forEach((el) => {
    const tmp = document.createElement("div");
    tmp.innerHTML = roomHead(el.dataset.head, !el.classList.contains("single"));
    const next = tmp.firstElementChild;
    const status = el.querySelector(".room-status"), nextStatus = next.querySelector(".room-status");
    if (status.textContent !== nextStatus.textContent) status.textContent = nextStatus.textContent;
    const off = el.querySelector("[data-room-off]"), nextOff = next.querySelector("[data-room-off]");
    if (off && nextOff) syncAttributes(off, nextOff);
    else if (off) {
      const focused = document.activeElement === off;
      off.remove();
      if (focused) el.querySelector("[data-edit-room], .room-title")?.focus({ preventScroll: true });
    } else if (nextOff) el.insertBefore(nextOff, el.querySelector("[data-edit-room]"));
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
let renderedRooms = null;
function renderGrid() {
  const grid = $("#grid");
  if (grid.dataset.gridGesture) return;
  if (!store.devices.size && (store.room === "all" || store.me?.role !== "admin")) {
    renderedRooms = null;
    setMarkup(grid, store.me && store.me.role !== "admin"
      ? `<div class="empty"><h2>No devices yet</h2><p>Ask an admin to share some devices with your profile.</p></div>`
      : `<div class="empty"><h2>Add your first device</h2>
      <p>Plugs, lights and TVs on your Wi-Fi show up here.</p>
      <button class="btn primary" data-add-device>${icon("plus")}Add a device</button></div>`);
    return;
  }
  const room = store.room;
  const groups = room === "all" ? roomGroups() : [room];
  const key = JSON.stringify([store.me?.id, room, groups.map(roomLayoutKey)]);
  if (renderedRooms === key && grid.querySelector(".room-section")) {
    for (const id of new Set([...grid.querySelectorAll(".tile")].map(el => el.dataset.id))) updateTiles(id);
    updateHeads();
    return;
  }
  const focused = grid.contains(document.activeElement) ? document.activeElement : null;
  const focusedItem = focused?.closest(".layout-item");
  const focusAttr = focused && ["data-more", "data-quick-action", "data-act", "data-resize", "data-room-options"].find(name => focused.hasAttribute(name));
  const anchor = window.scrollY > grid.offsetTop ? [...grid.querySelectorAll(".layout-item")]
    .find(el => { const r = el.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; }) : null;
  const anchorTop = anchor?.getBoundingClientRect().top;
  const section = (r, linked) => `<section class="room-section" aria-label="${esc(roomLabel(r))}">${roomHead(r, linked)}${
    r === OTHER ? sortNudge() : ""}${devicesIn(r).length ? roomTiles(r) : linked ? "" : `<div class="empty room-empty">
      <h2>No devices in this room yet</h2><p>Add a device or choose this room in a device's settings.</p>
      <button class="btn primary" data-add-device>${icon("plus")}Add a device</button></div>`}</section>`;
  const html = room === "all" ? roomGroups().map((r) => section(r, true)).join("") : section(room, false);
  setMarkup(grid, html);
  renderedRooms = key;
  if (focusedItem) {
    const item = grid.querySelector(`[data-wid="${CSS.escape(focusedItem.dataset.wid)}"]`);
    const target = focusAttr ? item?.querySelector(`[${focusAttr}="${CSS.escape(focused.getAttribute(focusAttr))}"]`) : item;
    target?.focus({ preventScroll: true });
  }
  if (anchor) {
    const replacement = grid.querySelector(`[data-wid="${CSS.escape(anchor.dataset.wid)}"]`);
    if (replacement) window.scrollBy(0, replacement.getBoundingClientRect().top - anchorTop);
  }
}

// The backdrop behind the glass takes on the color of the lights that are on,
// so the whole screen gets warmer as the room does.
function renderAmbience() {
  const root = document.documentElement;
  applyTypography(store.settings.font_size);
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
  if (home) roomTransition?.cancel();
  document.documentElement.dataset.view = store.view;
  $("#home").hidden = !home;
  $("#grid").hidden = home;
  renderNav();
  renderTitle();
  if (home) renderHome({ enter });
  else {
    renderGrid();
    if (enter && !reduceMotion()) {
      roomTransition?.cancel();
      roomTransition = $("#grid").animate([{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "none" }],
                         { duration: 200, easing: "cubic-bezier(.2,.8,.2,1)" });
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
    if (isRoomEditing()) return;
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
  grid.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") swiped = false;
  });
  grid.addEventListener("click", (e) => {   // a swipe isn't a tap
    if (swiped) { swiped = false; e.stopImmediatePropagation(); e.preventDefault(); }
  }, { capture: true });
  bindTiles(grid, { enabled: () => !isRoomEditing() });

  grid.addEventListener("click", (e) => {
    if (isRoomEditing()) return;
    const edit = e.target.closest("[data-edit-room]");
    if (edit) {
      goRoom(edit.dataset.editRoom);
      return startRoomEditing(edit.dataset.editRoom);
    }
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
  document.addEventListener("focusin", e => {
    if (e.target !== document.body) navFocus = readNavFocus(e.target);
  });
  document.addEventListener("selectionchange", () => {
    const focused = readNavFocus(document.activeElement);
    if (focused) navFocus = focused;
  });
  document.addEventListener("pointerdown", e => {
    if (!e.target.closest("#rail, #rooms, #room-tools, #dock")) navFocus = null;
  }, { capture: true });
  $("#room-tools").addEventListener("change", e => {
    if (e.target.matches("[data-room-picker]")) { goRoom(e.target.value); e.target.value = store.room; }
  });
  document.addEventListener("input", e => {
    if (!e.target.matches("#rail [data-room-add] input, #room-tools [data-room-add] input")) return;
    newRoomName = e.target.value;
    document.querySelectorAll("#rail [data-room-add] input, #room-tools [data-room-add] input").forEach(input => {
      if (input !== e.target) input.value = newRoomName;
    });
  });
  // Navigation and shared buttons, wherever they are (rail, dock, tabs, empty states).
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (!t.closest("#app")) return;
    if (t.closest("[data-edit-rooms]") && canNavigate(true)) {
      addingRoom = false;
      newRoomName = "";
      const scope = t.closest("#rail") ? "#rail" : "#room-tools";
      if (await toggleRoomEditing(scope === "#rail" ? scope : "#rooms")) document.querySelector(`${scope} [data-edit-rooms]`)?.focus();
      return;
    }
    if (t.closest("[data-add-room]") && canNavigate()) {
      addingRoom = !addingRoom; addingProfile = store.me?.id; newRoomName = "";
      renderNav(true);
      if (addingRoom) $(`${wide() ? "#rail" : "#room-tools"} [data-room-add] input`)?.focus();
      return;
    }
    if (t.closest("[data-room-add-cancel]")) {
      addingRoom = false; newRoomName = ""; renderNav(true);
      return $(`${wide() ? "#rail" : "#room-tools"} [data-add-room]`)?.focus();
    }
    const nav = t.closest("[data-nav]");
    if (nav) {
      if (!canNavigate()) return;
      if (nav.dataset.nav === store.view && nav.dataset.nav === "rooms" && store.room !== "all") return goRoom("all");
      return setView(nav.dataset.nav);
    }
    const room = t.closest("#rooms [data-room], #rail [data-room]");
    if (room) return goRoom(room.dataset.room);
    if (t.closest("[data-open-settings]") && canNavigate()) return openSettings();
    if (t.closest("[data-add-device]") && canNavigate()) return openSettings("add");
  });
  $("#all-off").addEventListener("click", () => turnOff());   // always everything; rooms have their own button
  $("#open-frame").addEventListener("click", () => { closeSheet(); openFrame(); });
  $("#clock").addEventListener("click", showAmbient);
  $("#edit-home").addEventListener("click", startEditing);
  const addFromNav = async (e) => {
    const form = e.target.closest("[data-room-add]");
    if (!form) return;
    e.preventDefault();
    if (savingRooms || isSortingRooms() || !canLeaveRoomNames(true) || editing()) return;
    const profile = store.me?.id;
    const name = new FormData(form).get("room");
    const controls = [...document.querySelectorAll("#rail [data-room-add] :is(button,input), #room-tools [data-room-add] :is(button,input)")];
    savingRooms = true;
    controls.forEach(control => { control.disabled = true; });
    try {
      const room = await addRoom(name);
      if (profile !== store.me?.id) return;
      savingRooms = false;
      addingRoom = false; newRoomName = ""; renderNav(true); goRoom(room); toast(`${room} added`);
    } catch (err) {
      if (profile === store.me?.id) toast(err.message, true);
    } finally {
      savingRooms = false;
      controls.forEach(control => { control.disabled = false; });
      if (addingRoom && profile === store.me?.id) $(`${wide() ? "#rail" : "#room-tools"} [data-room-add] input`)?.focus();
    }
  };
  $("#rail").addEventListener("submit", addFromNav);
  $("#room-tools").addEventListener("submit", addFromNav);
  document.addEventListener("hp:edit-room", (e) => {
    if (!canNavigate()) return;
    closeSettings();
    goRoom(e.detail);
    startRoomEditing(e.detail);
  });
  matchMedia("(min-width: 768px)").addEventListener?.("change", () => {
    const focus = navFocus && { ...navFocus, start: navFocus.element?.selectionStart, end: navFocus.element?.selectionEnd };
    renderNav(); renderTitle();
    requestAnimationFrame(() => restoreNavFocus(focus, true));
  });
  matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", e => {
    if (e.matches) roomTransition?.cancel();
  });
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
    if (!(after > 0 && Date.now() - lastActivity > after * 1000) || isSettingsOpen() || editing() || isVoiceOpen()) return;
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
setupRoomEditor($("#grid"), renderGrid);
setupChrome();
setupVoice();
setupHome({ goRoom, showAmbient });
bindTiles($("#home"), { enabled: () => !isEditing(), onLongPress: () => startEditing() });
setupIdle();
setInterval(renderClock, 10_000);
setInterval(() => { applySky(); refreshWeather(); }, 60_000);

// Sign-in first (js/auth.js). Signed out, the panel keeps only its look (background,
// clock face) without keeping the previous profile's devices on screen.
function closeAll() {
  closeSheet();
  closeSettings();
  if (isEditing()) stopEditing();
  if (isRoomEditing()) stopRoomEditing();
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
