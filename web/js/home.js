// The Home page: a grid of widgets — big clock, clocks for other places, weather,
// scenes and the rooms — and edit mode to arrange them. Devices aren't on Home:
// each room's card opens that room's page with its devices.
//
// The layout is one object (`home_layout`, checked by app/core/layout.py) kept in
// each profile, so everyone gets their own Home page on every screen they use.
// The server sends the signed-in profile's layout as settings.home_layout.
//
// Edit mode (long-press the page, or the pencil): widgets wiggle; hold one and drag
// to move it, drag its corner (or tap it) to resize, "…" for more, "−" to hide.
// Cancel puts everything back; Done saves.

import { api } from "./api.js";
import { setMarkup, updateRoomCounts } from "./render.js";
import { store, devicesIn, roomGroups, OTHER } from "./store.js";
import { $, esc, icon, toast } from "./util.js";
import { openSettings } from "./settings.js";
import { svg, roomIcon } from "./icons.js";
import { haptic } from "./tiles.js";
import { currentWeather } from "./sky.js";
import { weatherIcon } from "./clockfaces.js";
import { SIZES, SIZE_NAMES, columnsFor, arrange, remember, place, fits, placementStyle, gridStyle, bindGridEditor, watchGridWidth } from "./grid.js";

const SCENE_ICONS = ["sun", "moon", "film", "sparkle", "coffee", "door"];
const TYPE_NAMES = { clock: "Clock", zone: "Clock", weather: "Weather", scenes: "Scenes", rooms: "Rooms" };

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
export const isEditing = () => !!draft;
const layout = () => draft || store.settings.home_layout || { version: 3, widgets: [] };
const clone = (o) => JSON.parse(JSON.stringify(o));
const columns = () => columnsFor($("#home").clientWidth);
const placed = (w) => ({ ...w, ...arrange(layout().widgets, columns()).get(w.id) });
let cancelGesture = () => {};

// ---------- widgets ----------
const isOn = (d) => !!d.state?.on && d.state?.online !== false;
const updateCounts = (el) => updateRoomCounts(el, (r) => devicesIn(r).filter(isOn).length);

function clockWidget(w, now) {
  const [t, ampm] = splitTime(fmt(now));
  return `<button class="w-fill w-clock" data-ambient aria-label="Show the resting clock">
      <span class="w-greet" data-greet>${esc(greeting(now))}</span>
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
      <span class="w-label">${esc(label)}${region !== label ? ` <em>${esc(region)}</em>` : ""}</span>
      <span class="w-time small"><span data-time>${esc(t)}</span><small data-ampm>${esc(ampm)}</small></span>
      <span class="w-sub" data-zone-line>${esc(zoneLine(tz, now))}</span>
    </div>`;
}

function weatherWidget() {
  const wx = currentWeather();
  if (!wx) {
    return `<div class="w-fill w-weather off">
        <span class="w-label">Weather</span>
        <p>Show the weather here and let the background follow the sky.</p>
        <button class="btn small" data-setup-weather>Turn on weather</button>
      </div>`;
  }
  const place = store.settings.place_name || "";
  return `<div class="w-fill w-weather">
      <span class="w-label">${esc(place || "Weather")}</span>
      <span class="w-wx">${weatherIcon(wx.condition, wx.is_day)}<b>${esc(wx.temperature)}°</b></span>
      <span class="w-sub">${esc(wx.label)}${wx.high != null ? ` · H ${esc(wx.high)}° L ${esc(wx.low)}°` : ""}</span>
    </div>`;
}

function scenesWidget() {
  const items = store.scenes.map((s) =>
    `<button class="scene" data-scene="${esc(s.id)}">${icon(SCENE_ICONS.includes(s.icon) ? s.icon : "sparkle")}<span>${esc(s.name)}</span></button>`);
  if (store.devices.size) items.push(`<button class="scene add" data-new-scene>${icon("plus")}<span>New scene</span></button>`);
  return `<div class="w-fill w-scenes"><span class="w-label">Scenes</span><div class="w-scene-list">${items.join("")}</div></div>`;
}

function roomsWidget() {
  const groups = roomGroups();
  const rows = groups.map((r) =>
    `<button class="w-room" data-go-room="${esc(r)}">${roomIcon(r)}<span>${esc(r === OTHER ? "Other" : r)}</span>
      <b class="count" data-room-count="${esc(r)}" hidden></b></button>`);
  return `<div class="w-fill w-rooms"><span class="w-label">Rooms</span><div class="w-room-list">${
    rows.join("") || `<p>Add devices and rooms to see them here.</p>`}</div></div>`;
}

function widgetBody(w, now) {
  switch (w.type) {
    case "clock": return clockWidget(w, now);
    case "zone": return zoneWidget(w, now);
    case "weather": return weatherWidget();
    case "scenes": return scenesWidget();
    case "rooms": return roomsWidget();
    default: return null;                     // e.g. an old "device" widget: devices are on the Rooms pages now
  }
}

const widgetName = (w) => {
  if (w.type === "zone") return `${w.options?.label || zoneName(zoneOf(w.options))} clock`;
  return TYPE_NAMES[w.type] || "Widget";
};

function chrome(w) {
  const name = esc(widgetName(w));
  return `<button class="w-badge w-hide" data-hide aria-label="Hide ${name}">${svg("hide")}</button>
    <button class="w-badge w-menu" data-menu aria-label="${name} options">${svg("dots")}</button>
    <button class="w-resize" data-resize aria-label="Change size of ${name} (now ${SIZE_NAMES[w.size]})">${svg("resize")}</button>`;
}

function widgetHtml(w, i, now) {
  const body = widgetBody(w, now);
  if (body == null) return "";
  return `<div class="widget layout-item t-${w.type} s-${w.size}" data-wid="${esc(w.id)}"
    ${isEditing() ? `tabindex="0" aria-label="Move ${esc(widgetName(w))} with arrow keys"` : ""}
    style="--i:${i};${placementStyle(w)}">${body}${isEditing() ? chrome(w) : ""}</div>`;
}

export function renderHome({ enter = false } = {}) {
  const el = $("#home");
  if (!el) return;
  const now = new Date();
  const positions = arrange(layout().widgets, columns());
  const visible = layout().widgets.filter((w) => !w.hidden).map((w) => ({ ...w, ...positions.get(w.id) }));
  el.classList.toggle("editing", isEditing());
  el.innerHTML = `<div class="home-grid layout-grid" style="${gridStyle(layout().widgets, columns(), isEditing())}">${visible.map((w, i) => widgetHtml(w, i, now)).join("")}</div>${
    !visible.length ? `<div class="empty"><h2>Your Home page is empty</h2><p>Add the clock, weather, scenes or your rooms.</p>
      <button class="btn primary" data-edit-home>${svg("pencil")}Edit Home page</button></div>` : ""}${
    isEditing() ? editBar() : ""}`;
  // Seed the owned region before its first live count update, so even that
  // update keeps the room buttons (and their focus/scroll position) intact.
  for (const w of visible.filter((w) => w.type === "rooms")) {
    const box = el.querySelector(`.widget[data-wid="${CSS.escape(w.id)}"]`);
    setMarkup(box, roomsWidget() + (isEditing() ? chrome(w) : ""));
  }
  updateCounts(el);
  if (enter && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    el.querySelectorAll(".widget").forEach((w, i) => w.animate(
      [{ opacity: 0, transform: "translateY(10px) scale(.98)" }, { opacity: 1, transform: "none" }],
      { duration: 240, delay: Math.min(i, 10) * 25, easing: "cubic-bezier(.2,.8,.2,1)", fill: "backwards" }));
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
export function refreshHomeParts(types = ["rooms", "weather", "scenes"]) {
  const el = $("#home");
  if (!el || el.hidden || isEditing()) return;
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
}

// ---------- edit mode ----------
function editBar() {
  return `<div class="editbar" role="toolbar" aria-label="Edit Home page">
      <span class="editbar-hint">Hold to move into free space · corner to resize</span>
      <button class="btn small" data-add-widget>${icon("plus")}Add</button>
      <button class="btn small" data-edit-cancel>Cancel</button>
      <button class="btn small primary" data-edit-done>Done</button>
    </div>`;
}

export function startEditing() {
  if (isEditing()) return;
  draft = clone(store.settings.home_layout || { version: 3, widgets: [] });
  draft.widgets = draft.widgets.filter((w) => w.type !== "device");   // devices live on the Rooms pages
  remember(draft.widgets, columns());
  haptic(18);
  renderHome();
}

export function stopEditing() {
  cancelGesture();
  draft = null;
  closeMenu();
  renderHome();
}

async function saveEditing() {
  const next = draft;
  const profile = store.me?.id;
  try {
    const s = await api.saveLayout(next);     // this profile's own Home page
    if (draft !== next || store.me?.id !== profile) return;
    store.settings = { ...store.settings, ...s };
    stopEditing();
    toast("Home page saved");
  } catch (e) { toast(e.message, true); }
}

const find = (id) => draft.widgets.find((w) => w.id === id);

function setSize(id, size) {
  const w = find(id);
  if (!w) return;
  const p = arrange(draft.widgets, columns()).get(id);
  if (!place(draft.widgets, columns(), id, { ...p, size })) return toast("Not enough free space. Move the tile first or choose a smaller size.", true);
  renderHome();
}

function move(id, dx, dy) {
  const p = arrange(draft.widgets, columns()).get(id);
  if (!place(draft.widgets, columns(), id, { ...p, x: p.x + dx, y: p.y + dy })) return toast("Choose an empty space inside the grid.", true);
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
  openMenu(`<h3>${esc(widgetName(w))}</h3>
    <div class="seg" role="radiogroup" aria-label="Size">${SIZES.map((s) =>
      `<button role="radio" aria-checked="${w.size === s}" data-size-pick="${s}" data-wid="${esc(id)}">${SIZE_NAMES[s]}</button>`).join("")}</div>
    ${zones}
    <div class="wmenu-row">
      <button class="btn small" data-move="-1,0" data-wid="${esc(id)}">Left</button>
      <button class="btn small" data-move="1,0" data-wid="${esc(id)}">Right</button>
      <button class="btn small" data-move="0,-1" data-wid="${esc(id)}">Up</button>
      <button class="btn small" data-move="0,1" data-wid="${esc(id)}">Down</button>
    </div>
    <p>Column ${w.x + 1}, row ${w.y + 1}. Changes apply to this ${columns()}-column layout.</p>
    <button class="btn small danger" data-hide-id="${esc(id)}">${svg("hide")}Hide from Home</button>
    <button class="btn small primary" data-menu-close>Close</button>`, `${widgetName(w)} options`);
}

function addMenu() {
  const hidden = draft.widgets.filter((w) => w.hidden);
  openMenu(`<h3>Add to Home</h3>
    ${hidden.length ? `<p class="group-label">Hidden widgets</p><div class="wmenu-list">${hidden.map((w) =>
      `<button class="chip" data-unhide="${esc(w.id)}">${icon("plus")}${esc(widgetName(w))}</button>`).join("")}</div>` : ""}
    <p class="group-label">Clock for another place</p>
    <div class="wmenu-list"><button class="chip" data-add-zone>${icon("plus")}Clock</button></div>
    <button class="btn small primary" data-menu-close>Close</button>`, "Add to Home");
}

function addWidget(w) {
  const existing = find(w.id);
  if (existing) {
    for (const cols of [2, 4, 6]) {
      const others = [...arrange(draft.widgets, cols).values()];
      if (existing.positions?.[cols] && !fits(existing.positions[cols], others, cols)) delete existing.positions[cols];
    }
    existing.hidden = false;
  }
  else draft.widgets.push(w);
  remember(draft.widgets, columns());
  closeMenu();
  renderHome();
  $(`#home .widget[data-wid="${CSS.escape(w.id)}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// ---------- events ----------
export function setupHome({ goRoom, showAmbient }) {
  const el = $("#home");
  cancelGesture = bindGridEditor(el, { enabled: isEditing, items: () => draft.widgets,
    render: renderHome, error: (message) => toast(message, true) });
  watchGridWidth(el, () => { cancelGesture(); renderHome(); });

  el.addEventListener("click", async (e) => {
    const t = e.target;
    if (isEditing()) {
      if (t.closest("[data-edit-done]")) return saveEditing();
      if (t.closest("[data-edit-cancel]")) return stopEditing();
      if (t.closest("[data-add-widget]")) return addMenu();
      const box = t.closest(".widget");
      if (!box) return;
      if (t.closest("[data-hide]")) { find(box.dataset.wid).hidden = true; return renderHome(); }
      if (t.closest("[data-menu]")) return widgetMenu(box.dataset.wid);
      return;                                  // widgets don't act while editing
    }
    if (t.closest("[data-edit-home]")) return startEditing();
    if (t.closest("[data-ambient]")) return showAmbient();
    if (t.closest("[data-setup-weather]")) return openSettings("location", "weather");
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
    if (!t.closest(".wmenu-wrap") || !isEditing()) return;
    if (t.closest("[data-menu-close]")) return closeMenu();
    const size = t.closest("[data-size-pick]");
    if (size) { setSize(size.dataset.wid, size.dataset.sizePick); return widgetMenu(size.dataset.wid); }
    const mv = t.closest("[data-move]");
    if (mv) { move(mv.dataset.wid, ...mv.dataset.move.split(",").map(Number)); return widgetMenu(mv.dataset.wid); }
    const hide = t.closest("[data-hide-id]");
    if (hide) { find(hide.dataset.hideId).hidden = true; closeMenu(); return renderHome(); }
    const un = t.closest("[data-unhide]");
    if (un) return addWidget(find(un.dataset.unhide));
    if (t.closest("[data-add-zone]")) {
      return addWidget({ id: `zone-${Date.now().toString(36)}`, type: "zone", size: "1x1", hidden: false,
                         options: { tz: null, label: "US" } });
    }
  });
  document.addEventListener("change", (e) => {
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
