// The Home page: a grid of widgets — big clock, clocks for other places, weather,
// scenes and the rooms — and edit mode to arrange them. Devices aren't on Home:
// each room's card opens that room's page with its devices.
//
// The layout is one object (`home_layout`, checked by app/core/layout.py) kept in
// each profile, so everyone gets their own Home page on every screen they use.
// The server sends the signed-in profile's layout as settings.home_layout.
//
// Edit mode: grips move, corners resize, and Options configures or hides a widget.
// Cancel puts everything back; Done saves.

import { api } from "./api.js";
import { setMarkup, updateRoomCounts } from "./render.js";
import { notificationsWidget, refreshAttention } from "./notifications.js";
import { openDevice } from "./sheet.js";
import { store, devicesIn, roomGroups, OTHER } from "./store.js";
import { $, esc, icon, roomIfAmbiguous, toast } from "./util.js";
import { openSettings } from "./settings.js";
import { svg, roomIcon } from "./icons.js";
import { haptic, tileHtml } from "./tiles.js";
import { currentWeather, weatherStatus, refreshWeather } from "./sky.js";
import { watchWeatherEffects } from "./weather-effects.js";
import { weatherTile } from "./weather-tile.js";
import { photoTile, watchPhotoTiles } from "./photo-tile.js";
import { sizeChoices, sizeName, grip, columnsFor, arrange, remember, place, fits, placementStyle, gridStyle, bindGridEditor, watchGridWidth } from "./grid.js";

const SCENE_ICONS = ["sun", "moon", "film", "sparkle", "coffee", "door"];
const TYPE_NAMES = { clock: "Clock", notifications:"Notifications", zone: "Clock", weather: "Weather", scenes: "Scenes", rooms: "Rooms", photos: "Photos", favourites: "Favourites" };
export const MAX_FAVOURITES = 8;
let syncPhotoTiles = () => {};

// ---------- time zones ----------
export const US_ZONES = [
  ["America/New_York", "Eastern"], ["America/Chicago", "Central"], ["America/Denver", "Mountain"],
  ["America/Phoenix", "Arizona"], ["America/Los_Angeles", "Pacific"], ["America/Anchorage", "Alaska"],
  ["Pacific/Honolulu", "Hawaii"],
];
const ZONES = [["Asia/Kolkata", "India"], ...US_ZONES];
const screenZone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { return "UTC"; } };

// tz null = this screen's own zone if it's a US one, otherwise Eastern.
export function zoneOf(opts = {}) {
  if (opts.tz) return opts.tz;
  const z = screenZone();
  return US_ZONES.some(([id]) => id === z) ? z : "America/New_York";
}
const zoneName = (tz) => (ZONES.find(([id]) => id === tz) || [tz, tz.split("/").pop().replace(/_/g, " ")])[1];

// Minutes the zone is ahead of this screen right now.
export function zoneOffset(tz, now = new Date()) {
  const parts = (zone) => {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: zone, hourCycle: "h23",
      year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" })
      .formatToParts(now).map((x) => [x.type, x.value]));
    return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
  };
  return Math.round((parts(tz) - parts(screenZone())) / 60000);
}

function zoneLine(tz, now) {
  const mins = zoneOffset(tz, now);
  if (!mins) return "Same time as here";
  const h = Math.floor(Math.abs(mins) / 60), m = Math.abs(mins) % 60;
  const diff = `${mins > 0 ? "+" : "−"}${h}${m ? `:${String(m).padStart(2, "0")}` : ""} h`;
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(now);
  const here = new Intl.DateTimeFormat("en-CA").format(now);
  return `${diff}${day > here ? " · Tomorrow" : day < here ? " · Yesterday" : ""}`;
}

const fmt = (now, opts = {}) => now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: !store.settings.clock_24h, ...opts });
const splitTime = (s) => { const m = s.match(/^(.*?)\s?([AP]M)$/i); return m ? [m[1], m[2]] : [s, ""]; };

export function greeting(now = new Date()) {
  const h = now.getHours();
  return h >= 5 && h < 12 ? "Good morning" : h >= 12 && h < 17 ? "Good afternoon" : h >= 17 && h < 22 ? "Good evening" : "Good night";
}

// ---------- layout ----------
let draft = null;          // a copy being edited; null when not editing
let editingProfile = null, saving = false, selected = null, entryLayout = null;
let renderedLayout = null;
export const isEditing = () => !!draft;
const layout = () => draft || store.settings.home_layout || { version: 4, widgets: [] };
const items = () => layout().widgets;
const clone = (o) => JSON.parse(JSON.stringify(o));
const columns = () => columnsFor($("#home").clientWidth);
const placed = (w) => ({ ...w, ...arrange(items(), columns()).get(w.id) });
let cancelGesture = () => {};
let syncWeatherEffects = () => {};

// ---------- widgets ----------
const isOn = (d) => !!d.state?.on && d.state?.online !== false;
const updateCounts = (el) => updateRoomCounts(el, (r) => devicesIn(r).filter(isOn).length);

function clockWidget(w, now) {
  const [t, ampm] = splitTime(fmt(now));
  return `<button class="w-fill w-clock" data-ambient aria-label="Show the resting clock">
      <span class="w-greet widget-heading" data-greet>${esc(greeting(now))}</span>
      <span class="w-time"><span data-time>${esc(t)}</span><small data-ampm>${esc(ampm)}</small></span>
      <span class="w-date" data-date>${esc(now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" }))}</span>
    </button>`;
}

function zoneWidget(w, now) {
  const tz = zoneOf(w.options);
  let time;
  try { time = fmt(now, { timeZone: tz }); } catch { time = "--:--"; }
  const [t, ampm] = splitTime(time);
  const label = w.options?.label || zoneName(tz);
  const region = zoneName(tz);
  return `<div class="w-fill w-zone" data-zone="${esc(tz)}">
      <span class="w-label widget-heading">${esc(label)}${region !== label ? ` <em>${esc(region)}</em>` : ""}</span>
      <span class="w-time small"><span data-time>${esc(t)}</span><small data-ampm>${esc(ampm)}</small></span>
      <span class="w-sub" data-zone-line>${esc(zoneLine(tz, now))}</span>
    </div>`;
}

function weatherWidget() {
  const wx = currentWeather();
  const state = weatherStatus() === "updating" ? "ready" : weatherStatus();
  if (state !== "ready" || !wx) {
    const message = state === "loading" ? "Loading weather..." : state === "unavailable"
      ? "Weather is unavailable. Check the connection and try again."
      : "Show the weather here and let the background follow the sky.";
    return `<div class="w-fill w-weather off" data-weather-status="${state}">
        <span class="w-label widget-heading">Weather</span>
        <p role="status">${message}</p>
        ${state === "loading" ? "" : state === "unavailable"
          ? `<button class="btn small" data-retry-weather>Retry weather</button>`
          : `<button class="btn small" data-setup-weather>${store.settings.weather_enabled ? "Set location" : "Turn on weather"}</button>`}
      </div>`;
  }
  return weatherTile(wx, { place: store.settings.place_name || "", h24: !!store.settings.clock_24h });
}

function scenesWidget() {
  const items = store.scenes.map((s) =>
    `<button class="scene" data-scene="${esc(s.id)}">${icon(SCENE_ICONS.includes(s.icon) ? s.icon : "sparkle")}<span>${esc(s.name)}</span></button>`);
  if (store.devices.size) items.push(`<button class="scene add" data-new-scene>${icon("plus")}<span>New scene</span></button>`);
  // Nothing saved yet: say what a scene is, so the tile isn't a lone button.
  const hint = !store.scenes.length && store.devices.size
    ? `<p class="w-hint">Save device settings as a scene.</p>` : "";
  return `<div class="w-fill w-scenes"><span class="w-label widget-heading">Scenes</span><div class="w-scene-list">${items.join("")}</div>${hint}</div>`;
}

function roomsWidget() {
  const groups = roomGroups();
  const rows = groups.map((r) =>
    `<button class="w-room" data-go-room="${esc(r)}">${roomIcon(r)}<span>${esc(r === OTHER ? "Other" : r)}</span>
      <b class="count" data-room-count="${esc(r)}" hidden></b></button>`);
  return `<div class="w-fill w-rooms"><span class="w-label widget-heading">Rooms</span><div class="w-room-list">${
    rows.join("") || `<p>Add devices and rooms to see them here.</p>`}</div></div>`;
}

// The devices a Favourites widget shows: the chosen ones that still exist (in the order
// chosen), or, when none were chosen, the first few the person can use.
export function favouriteDevices(options, devices, max = MAX_FAVOURITES) {
  const all = [...devices];
  const chosen = (options?.devices || []).map((id) => all.find((d) => d.id === id)).filter(Boolean);
  const usable = (d) => d.caps.includes("power") || d.caps.includes("clean");
  return (chosen.length ? chosen : all.filter(usable)).slice(0, max);
}

// True when a Favourites widget on screen no longer lists the devices it should
// (one was added, removed or shared). State changes alone never make it stale.
export function favouritesStale() {
  return layout().widgets.some((w) => {
    if (w.hidden || w.type !== "favourites") return false;
    const box = document.querySelector(`#home .widget[data-wid="${CSS.escape(w.id)}"]`);
    if (!box) return false;
    const shown = [...box.querySelectorAll(".tile")].map((el) => el.dataset.id).join();
    return shown !== favouriteDevices(w.options, store.devices.values()).map((d) => d.id).join();
  });
}

function favouritesWidget(w) {
  const list = favouriteDevices(w.options, store.devices.values());
  const rows = list.map((d) => tileHtml(d, { ctx: "home", sub: roomIfAmbiguous(d, list) }));
  return `<div class="w-fill w-favs"><span class="w-label widget-heading">Favourites</span><div class="w-fav-list">${
    rows.join("") || `<p>Add a device to see it here.</p>`}</div></div>`;
}

function widgetBody(w, now) {
  switch (w.type) {
    case "clock": return clockWidget(w, now);
    case "notifications": return notificationsWidget();
    case "zone": return zoneWidget(w, now);
    case "weather": return weatherWidget();
    case "scenes": return scenesWidget();
    case "rooms": return roomsWidget();
    case "photos": return photoTile();
    case "favourites": return favouritesWidget(w);
    default: return null;                     // e.g. an old "device" widget: devices are on the Rooms pages now
  }
}

const widgetName = (w) => {
  if (w.type === "zone") return `${w.options?.label || zoneName(zoneOf(w.options))} clock`;
  return TYPE_NAMES[w.type] || "Widget";
};

function chrome(w) {
  const name = esc(widgetName(w));
  return `${grip(name,saving)}<button class="w-resize" data-resize aria-label="Resize ${name} (now ${sizeName(w.size)}); use arrow keys" ${saving ? "disabled" : ""}>${svg("resize")}</button>`;
}

function widgetHtml(w, i, now) {
  const body = widgetBody(w, now);
  if (body == null) return "";
  return `<div class="widget layout-item t-${w.type}${Number(w.size.split("x")[1]) <= 3 ? " short-tile" : ""}" data-wid="${esc(w.id)}"
    ${isEditing() ? `tabindex="0" aria-label="Move ${esc(widgetName(w))} with arrow keys"` : ""}
    style="--i:${i};${placementStyle(w)}">${body}${isEditing() ? chrome(w) : ""}</div>`;
}

export function renderHome({ enter = false } = {}) {
  const el = $("#home");
  if (!el) return;
  if (draft && editingProfile !== store.me?.id) {
    cancelGesture(); draft=null; editingProfile=null; selected=null; closeMenu();
    delete document.documentElement.dataset.layoutEditing;
  }
  if (el.dataset.gridGesture) return;
  const key = JSON.stringify([store.me?.id, layout(), columns(), isEditing(), saving]);
  if (renderedLayout === key && el.querySelector(".home-grid")) {
    tickHome();
    refreshHomeParts();
    syncPhotoTiles();
    return;
  }
  renderedLayout = key;
  const now = new Date();
  const focus = el.contains(document.activeElement) ? document.activeElement : null;
  const focusId = focus?.closest(".widget")?.dataset.wid;
  const focusResize = focus?.hasAttribute("data-resize");
  const focusGrip = focus?.hasAttribute("data-grip");
  const scroll = window.scrollY;
  const list = items();
  const positions = arrange(list, columns());
  const visible = list.filter((w) => !w.hidden).map((w) => ({ ...w, ...positions.get(w.id) }));
  el.classList.toggle("editing", isEditing());
  el.innerHTML = `<div class="home-grid layout-grid" style="${gridStyle(list, columns(), isEditing())}">${visible.map((w, i) => widgetHtml(w, i, now)).join("")}</div>${
    !visible.length ? `<div class="empty"><h2>Your Home page is empty</h2><p>Add the clock, weather, scenes or your rooms.</p>
      <button class="btn primary" data-edit-home>${svg("pencil")}Edit Home page</button></div>` : ""}${
    isEditing() ? editBar() : ""}`;
  // Seed each owned region so an unchanged snapshot keeps its animation/focus.
  for (const w of visible) {
    const box = el.querySelector(`.widget[data-wid="${CSS.escape(w.id)}"]`);
    if (box) setMarkup(box, widgetBody(w, now) + (isEditing() ? chrome(w) : ""));
  }
  updateCounts(el);
  refreshAttention(el);
  if (isEditing()) {
    el.querySelectorAll(".widget > .w-fill").forEach(content=>{content.inert=true;content.setAttribute("aria-disabled","true");});
    selectWidget(selected);
    if (focusId) {
      const box=el.querySelector(`.widget[data-wid="${CSS.escape(focusId)}"]`);
      (focusResize ? box?.querySelector("[data-resize]") : focusGrip ? box?.querySelector("[data-grip]") : box)?.focus({preventScroll:true});
    }
  }
  window.scrollTo({top:scroll});
  syncWeatherEffects();
  syncPhotoTiles();
  if (enter && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    el.querySelectorAll(".widget").forEach((w, i) => w.animate(
      [{ opacity: 0, transform: "translateY(10px) scale(.98)" }, { opacity: 1, transform: "none" }],
      { duration: 200, delay: Math.min(i, 6) * 20, easing: "cubic-bezier(.2,.8,.2,1)", fill: "backwards" }));
  }
}

// Called every 10 s: just the clock texts, no re-render.
export function tickHome(now = new Date()) {
  const el = $("#home");
  if (!el || el.hidden) return;
  el.querySelectorAll(".w-clock").forEach((c) => {
    const [t, ampm] = splitTime(fmt(now));
    c.querySelector("[data-time]").textContent = t;
    c.querySelector("[data-ampm]").textContent = ampm;
    c.querySelector("[data-greet]").textContent = greeting(now);
    c.querySelector("[data-date]").textContent = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  });
  el.querySelectorAll(".w-zone").forEach((z) => {
    const [t, ampm] = splitTime(fmt(now, { timeZone: z.dataset.zone }));
    z.querySelector("[data-time]").textContent = t;
    z.querySelector("[data-ampm]").textContent = ampm;
    z.querySelector("[data-zone-line]").textContent = zoneLine(z.dataset.zone, now);
  });
}

// Something about rooms or weather changed: redraw those widgets only.
export function refreshHomeParts(types = ["rooms", "weather", "scenes", "photos", "favourites"]) {
  const el = $("#home");
  if (!el || el.hidden || isEditing()) return;
  refreshAttention(el);
  const now = new Date();
  for (const w of layout().widgets) {
    if (w.hidden || !types.includes(w.type)) continue;
    const box = el.querySelector(`.widget[data-wid="${CSS.escape(w.id)}"]`);
    const body = widgetBody(w, now);
    if (box && body != null) {
      setMarkup(box, body);
      if (w.type === "rooms") updateCounts(box);
    }
  }
  syncWeatherEffects();
  syncPhotoTiles();
}

// ---------- edit mode ----------
function editBar() {
  return `<div class="editbar" role="toolbar" aria-label="Edit Home page">
      <span class="editbar-hint">Drag a grip to move; drag a corner to resize</span>
      <button class="btn small" data-widget-options ${!selected || saving ? "disabled" : ""}>Options</button>
      <button class="btn small" data-add-widget ${saving ? "disabled" : ""}>${icon("plus")}Add</button>
      <button class="btn small" data-edit-cancel ${saving ? "disabled" : ""}>Cancel</button>
      <button class="btn small primary" data-edit-done ${saving ? "disabled" : ""}>${saving ? "Saving..." : "Done"}</button>
    </div>`;
}

function selectWidget(id) {
  const el=$("#home");
  selected=items().some(w=>w.id===id && !w.hidden) ? id : null;
  el.querySelectorAll(".widget").forEach(box=>box.classList.toggle("edit-selected",box.dataset.wid===selected));
  const button=el.querySelector("[data-widget-options]");
  if (button) {
    button.disabled=!selected || saving;
    button.setAttribute("aria-label",selected ? `${widgetName(find(selected))} options` : "Select a widget for options");
  }
}

export function startEditing() {
  if (isEditing()) return;
  editingProfile=store.me?.id;
  selected=null;
  entryLayout=clone(store.settings.home_layout || {version:4,widgets:[]});
  draft = clone(entryLayout);
  remember(items(), columns());
  document.documentElement.dataset.layoutEditing="home";
  haptic(18);
  renderHome();
}

export function stopEditing() {
  cancelGesture();
  draft = null;
  editingProfile=null;selected=null;
  entryLayout=null;
  delete document.documentElement.dataset.layoutEditing;
  closeMenu();
  renderHome();
}

async function saveEditing() {
  if (saving || !draft) return;
  const next = draft;
  const profile = editingProfile;
  saving=true;renderHome();
  try {
    const s = await api.saveLayout(next, entryLayout);
    if (draft !== next || store.me?.id !== profile) return;
    store.settings = { ...store.settings, ...s };
    stopEditing();
    toast("Home page saved");
  } catch (e) { toast(e.message, true); }
  finally { saving=false;renderHome(); }
}

const find = (id) => draft.widgets.find((w) => w.id === id);

function setSize(id, size) {
  const w = find(id);
  if (!w) return;
  const p = arrange(items(), columns()).get(id);
  if (!place(items(), columns(), id, { ...p, size })) return toast("Not enough free space. Move the tile first or choose a smaller size.", true);
  renderHome();
}

// --- the "…" menu and the Add list share one small dialog ---
function openMenu(html, label) {
  closeMenu();
  const wrap = document.createElement("div");
  wrap.className = "wmenu-wrap";
  wrap.innerHTML = `<div class="wmenu-scrim" data-menu-close></div>
    <div class="wmenu" role="dialog" aria-modal="true" aria-label="${esc(label)}">${html}</div>`;
  document.body.append(wrap);
  wrap.querySelector("button, select")?.focus();
}
function closeMenu() { document.querySelector(".wmenu-wrap")?.remove(); }

function widgetMenu(id) {
  const raw = find(id);
  const w = raw && placed(raw);
  if (!w) return;
  const zones = w.type === "zone" ? `
    <label class="field"><span>Time zone</span><select data-zone-pick="${esc(id)}">
      ${ZONES.map(([tz, name]) => `<option value="${tz}" ${zoneOf(w.options) === tz ? "selected" : ""}>${
        tz === "Asia/Kolkata" ? "India" : `US · ${name}`}</option>`).join("")}
    </select></label>` : "";
  const chosen = w.options?.devices || [];
  const favs = w.type === "favourites" ? `
    <p class="group-label">Devices to show (up to ${MAX_FAVOURITES}). None chosen = the first few.</p>
    <div class="wmenu-list fav-pick">${[...store.devices.values()].map((d) => `
      <label class="chip"><input type="checkbox" data-fav-pick="${esc(id)}" value="${esc(d.id)}" ${chosen.includes(d.id) ? "checked" : ""}>${
        esc(d.name)}${d.room ? ` <small>${esc(d.room)}</small>` : ""}</label>`).join("") || "<p>No devices yet.</p>"}</div>` : "";
  openMenu(`<h3>${esc(widgetName(w))}</h3>
    <div class="seg" role="radiogroup" aria-label="Size">${sizeChoices(w,columns()).map((s) =>
      `<button role="radio" aria-checked="${w.size === s}" data-size-pick="${s}" data-wid="${esc(id)}">${sizeName(s)}</button>`).join("")}</div>
    ${zones}${favs}
    <p>Arrow keys on the grip move one cell. Arrow keys on the corner change width and height.</p>
    <p>Column ${w.x + 1}, row ${w.y + 1}. Changes apply to this ${columns()}-column layout.</p>
    <button class="btn small danger" data-hide-id="${esc(id)}">${svg("hide")}Hide from Home</button>
    <button class="btn small primary" data-menu-close>Close</button>`, `${widgetName(w)} options`);
}

function addMenu() {
  const hidden = items().filter((w) => w.hidden);
  openMenu(`<h3>Add to Home</h3>
    ${hidden.length ? `<p class="group-label">Hidden widgets</p><div class="wmenu-list">${hidden.map((w) =>
      `<button class="chip" data-unhide="${esc(w.id)}">${icon("plus")}${esc(widgetName(w))}</button>`).join("")}</div>` : ""}
    <p class="group-label">Clock for another place</p>
    <div class="wmenu-list"><button class="chip" data-add-zone>${icon("plus")}Clock</button></div>
    ${store.devices.size ? `<p class="group-label">Shortcuts</p>
      <div class="wmenu-list"><button class="chip" data-add-favourites>${icon("plus")}Favourites</button></div>` : ""}
    ${!draft.widgets.some(w => w.type === "photos") ? `<p class="group-label">Photo library</p>
      <div class="wmenu-list"><button class="chip" data-add-photos>${icon("plus")}Photos</button></div>` : ""}
    <div class="wmenu-list">${["clock","notifications"].filter(type=>!draft.widgets.some(w=>w.type===type)).map(type=>
      `<button class="chip" data-add-type="${type}">${icon("plus")}${TYPE_NAMES[type]}</button>`).join("")}</div>
    <button class="btn small primary" data-menu-close>Close</button>`, "Add to Home");
}

function addWidget(w) {
  const existing = find(w.id);
  if (existing) {
    const projected=items().find(item=>item.id===w.id);
    for (const cols of [2, 4, 6]) {
      const others = [...arrange(items(), cols).values()];
      if (projected.positions?.[cols] && !fits(projected.positions[cols], others, cols)) {
        const positions={...projected.positions};delete positions[cols];projected.positions=positions;
      }
    }
    existing.hidden = false;
  }
  else draft.widgets.push(w);
  remember(items(), columns());
  closeMenu();
  renderHome();
  $(`#home .widget[data-wid="${CSS.escape(w.id)}"]`)?.scrollIntoView({
    block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
  });
}

// ---------- events ----------
export function setupHome({ goRoom, showAmbient }) {
  const el = $("#home");
  syncWeatherEffects = watchWeatherEffects(el);
  syncPhotoTiles = watchPhotoTiles(el, isEditing);
  cancelGesture = bindGridEditor(el, { enabled: () => isEditing() && !saving, items,
    render: renderHome, error: (message) => toast(message, true) });
  watchGridWidth(el, () => { cancelGesture(); renderHome(); });
  addEventListener("resize",()=>{cancelGesture();renderHome();});
  el.addEventListener("focusin",e=>{if(isEditing()) selectWidget(e.target.closest(".widget")?.dataset.wid || selected);});
  el.addEventListener("pointerdown",e=>{if(isEditing()) selectWidget(e.target.closest(".widget")?.dataset.wid || selected);});
  el.addEventListener("keydown",e=>{
    if (isEditing() && !saving && e.target.matches(".widget") && ["Enter"," "].includes(e.key)) {
      e.preventDefault();selectWidget(e.target.dataset.wid);widgetMenu(selected);
    }
  });

  el.addEventListener("click", async (e) => {
    const t = e.target;
    if (isEditing()) {
      if (saving) return;
      if (t.closest("[data-edit-done]")) return saveEditing();
      if (t.closest("[data-edit-cancel]")) return stopEditing();
      if (t.closest("[data-add-widget]")) return addMenu();
      if (t.closest("[data-widget-options]") && selected) return widgetMenu(selected);
      const box = t.closest(".widget");
      if (!box) return;
      selectWidget(box.dataset.wid);
      return;                                  // widgets don't act while editing
    }
    if (t.closest("[data-edit-home]")) return startEditing();
    if (t.closest("[data-ambient]")) return showAmbient();
    const attention = t.closest("[data-attention]");
    if (attention) return openDevice(attention.dataset.attention);
    if (t.closest("[data-setup-weather]")) return openSettings("location", "weather");
    if (t.closest("[data-photo-settings]")) return openSettings("photo-library");
    if (t.closest("[data-retry-weather]")) return refreshWeather(true);
    if (t.closest("[data-new-scene]")) return openSettings("scene-new");
    const room = t.closest("[data-go-room]");
    if (room) return goRoom(room.dataset.goRoom);
    const sc = t.closest("[data-scene]");
    if (sc) {
      sc.classList.add("running");
      try {
        const r = await api.runScene(sc.dataset.scene);
        const name = store.scenes.find((s) => s.id === sc.dataset.scene)?.name || "Scene";
        toast(r.failed.length ? `${name}: ${r.failed.length} device(s) didn't respond` : `${name} is on`, !!r.failed.length);
      } catch (err) { toast(err.message, true); }
      sc.classList.remove("running");
    }
  });

  // The menu and Add dialogs live on <body>.
  document.addEventListener("click", (e) => {
    const t = e.target;
    if (!t.closest(".wmenu-wrap") || !isEditing() || saving) return;
    if (t.closest("[data-menu-close]")) return closeMenu();
    const size = t.closest("[data-size-pick]");
    if (size) { setSize(size.dataset.wid, size.dataset.sizePick); return widgetMenu(size.dataset.wid); }
    const hide = t.closest("[data-hide-id]");
    if (hide) { find(hide.dataset.hideId).hidden = true; closeMenu(); return renderHome(); }
    const un = t.closest("[data-unhide]");
    if (un) return addWidget(find(un.dataset.unhide));
    if (t.closest("[data-add-zone]")) {
      return addWidget({ id: `zone-${Date.now().toString(36)}`, type: "zone", size: "1x3", hidden: false,
                         options: { tz: null, label: "US" } });
    }
    if (t.closest("[data-add-favourites]")) {
      return addWidget({ id: `favs-${Date.now().toString(36)}`, type: "favourites", size: "2x6", hidden: false,
                         options: { devices: [] } });
    }
    if (t.closest("[data-add-photos]")) {
      return addWidget({ id: `photos-${Date.now().toString(36)}`, type: "photos", size: "2x6", hidden: false, options: {} });
    }
    const added=t.closest("[data-add-type]");
    if (added) {
      const type=added.dataset.addType, id=find(type) ? `${type}-${Date.now().toString(36)}` : type;
      return addWidget({id,type,size:"2x4",hidden:false,options:{}});
    }
  });
  document.addEventListener("change", (e) => {
    const fav = e.target.closest("[data-fav-pick]");
    if (fav && isEditing()) {
      const w = find(fav.dataset.favPick);
      const picked = [...fav.closest(".fav-pick").querySelectorAll("input:checked")].map((box) => box.value);
      if (picked.length > MAX_FAVOURITES) {
        fav.checked = false;
        return toast(`Favourites can show up to ${MAX_FAVOURITES} devices.`, true);
      }
      // Keep the order they were chosen in: earlier picks stay first.
      const before = (w.options?.devices || []).filter((id) => picked.includes(id));
      w.options = { devices: [...before, ...picked.filter((id) => !before.includes(id))] };
      return renderHome();
    }
    const sel = e.target.closest("[data-zone-pick]");
    if (!sel || !isEditing()) return;
    const w = find(sel.dataset.zonePick);
    w.options = { tz: sel.value, label: sel.value === "Asia/Kolkata" ? "India" : "US" };
    renderHome();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.querySelector(".wmenu-wrap")) closeMenu();
  });
}
