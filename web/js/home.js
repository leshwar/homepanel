// The Home page: a grid of widgets — big clock, clocks for other places, weather,
// scenes, rooms and device shortcuts — and edit mode to arrange them.
//
// The layout is one object in panel settings (`home_layout`, checked by
// app/core/layout.py), so every screen shows the same Home page.
//
// Edit mode (long-press the page, or the pencil): widgets wiggle; hold one and drag
// to move it, drag its corner (or tap it) to resize, "…" for more, "−" to hide.
// Cancel puts everything back; Done saves.

import { api } from "./api.js";
import { store, devicesIn, roomGroups, OTHER } from "./store.js";
import { $, esc, icon, isMedia, toast } from "./util.js";
import { openSettings } from "./settings.js";
import { svg, roomIcon } from "./icons.js";
import { tileHtml, haptic } from "./tiles.js";
import { currentWeather } from "./sky.js";
import { weatherIcon } from "./clockfaces.js";

const SCENE_ICONS = ["sun", "moon", "film", "sparkle", "coffee", "door"];
const SIZES = ["1x1", "2x1", "2x2"];
const SIZE_NAMES = { "1x1": "Small", "2x1": "Wide", "2x2": "Large" };
const TYPE_NAMES = { clock: "Clock", zone: "Clock", weather: "Weather", scenes: "Scenes", rooms: "Rooms", device: "Device" };

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
const layout = () => draft || store.settings.home_layout || { version: 1, widgets: [] };
const clone = (o) => JSON.parse(JSON.stringify(o));

// ---------- widgets ----------
const isOn = (d) => !!d.state?.on && d.state?.online !== false;

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
  const rows = groups.map((r) => {
    const on = devicesIn(r).filter(isOn).length;
    return `<button class="w-room" data-go-room="${esc(r)}">${roomIcon(r)}<span>${esc(r === OTHER ? "Other" : r)}</span>${
      on ? `<b class="count" aria-label="${on} on">${on}</b>` : ""}</button>`;
  });
  return `<div class="w-fill w-rooms"><span class="w-label">Rooms</span><div class="w-room-list">${
    rows.join("") || `<p>Add devices and rooms to see them here.</p>`}</div></div>`;
}

function deviceWidget(w) {
  const d = store.devices.get(w.options?.device_id);
  if (!d) return null;                       // removed since: leave it out
  return tileHtml(d, { size: w.size, ctx: "home", sub: d.room || "" });
}

function widgetBody(w, now) {
  switch (w.type) {
    case "clock": return clockWidget(w, now);
    case "zone": return zoneWidget(w, now);
    case "weather": return weatherWidget();
    case "scenes": return scenesWidget();
    case "rooms": return roomsWidget();
    case "device": return deviceWidget(w);
    default: return null;
  }
}

const widgetName = (w) => {
  if (w.type === "device") return store.devices.get(w.options?.device_id)?.name || "Device";
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
  return `<div class="widget t-${w.type} s-${w.size}" data-wid="${esc(w.id)}" style="--i:${i}">${body}${isEditing() ? chrome(w) : ""}</div>`;
}

export function renderHome({ enter = false } = {}) {
  const el = $("#home");
  if (!el) return;
  const now = new Date();
  const visible = layout().widgets.filter((w) => !w.hidden);
  el.classList.toggle("editing", isEditing());
  el.innerHTML = `<div class="home-grid">${visible.map((w, i) => widgetHtml(w, i, now)).join("")}</div>${
    !visible.length ? `<div class="empty"><h2>Your Home page is empty</h2><p>Add the clock, weather or your favourite devices.</p>
      <button class="btn primary" data-edit-home>${svg("pencil")}Edit Home page</button></div>` : ""}${
    isEditing() ? editBar() : ""}`;
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
    if (box && body != null) box.innerHTML = body;
  }
}

// ---------- edit mode ----------
function editBar() {
  return `<div class="editbar" role="toolbar" aria-label="Edit Home page">
      <span class="editbar-hint">Hold to move · drag a corner to resize</span>
      <button class="btn small" data-add-widget>${icon("plus")}Add</button>
      <button class="btn small" data-edit-cancel>Cancel</button>
      <button class="btn small primary" data-edit-done>Done</button>
    </div>`;
}

export function startEditing() {
  if (isEditing()) return;
  draft = clone(store.settings.home_layout || { version: 1, widgets: [] });
  haptic(18);
  renderHome();
}

function stopEditing() {
  draft = null;
  closeMenu();
  renderHome();
}

async function saveEditing() {
  const next = draft;
  try {
    const s = await api.saveSettings({ home_layout: next });
    store.settings = { ...store.settings, ...s };
    stopEditing();
    toast("Home page saved");
  } catch (e) { toast(e.message, true); }
}

const find = (id) => draft.widgets.find((w) => w.id === id);

function setSize(id, size) {
  const w = find(id);
  if (!w || w.size === size) return;
  w.size = size;
  const box = $(`#home .widget[data-wid="${CSS.escape(id)}"]`);
  if (box) {
    box.classList.remove(...SIZES.map((s) => `s-${s}`));
    box.classList.add(`s-${size}`);
    const body = widgetBody(w, new Date());
    if (body != null) box.innerHTML = body + chrome(w);
  }
}

function move(id, step) {
  const list = draft.widgets.filter((w) => !w.hidden);
  const i = list.findIndex((w) => w.id === id), j = i + step;
  if (i < 0 || j < 0 || j >= list.length) return;
  [list[i], list[j]] = [list[j], list[i]];
  draft.widgets = [...list, ...draft.widgets.filter((w) => w.hidden)];
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
  const w = find(id);
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
      <button class="btn small" data-move="-1" data-wid="${esc(id)}">${icon("left")}Move earlier</button>
      <button class="btn small" data-move="1" data-wid="${esc(id)}">Move later${icon("right")}</button>
    </div>
    <button class="btn small danger" data-hide-id="${esc(id)}">${svg("hide")}Hide from Home</button>
    <button class="btn small primary" data-menu-close>Close</button>`, `${widgetName(w)} options`);
}

function addMenu() {
  const hidden = draft.widgets.filter((w) => w.hidden);
  const shown = new Set(draft.widgets.filter((w) => w.type === "device").map((w) => w.options.device_id));
  const devices = [...store.devices.values()].filter((d) => !shown.has(d.id)).sort((a, b) => a.name.localeCompare(b.name));
  openMenu(`<h3>Add to Home</h3>
    ${hidden.length ? `<p class="group-label">Hidden widgets</p><div class="wmenu-list">${hidden.map((w) =>
      `<button class="chip" data-unhide="${esc(w.id)}">${icon("plus")}${esc(widgetName(w))}</button>`).join("")}</div>` : ""}
    <p class="group-label">Clock for another place</p>
    <div class="wmenu-list"><button class="chip" data-add-zone>${icon("plus")}Clock</button></div>
    ${devices.length ? `<p class="group-label">Devices</p><div class="wmenu-list">${devices.map((d) =>
      `<button class="chip" data-add-device-widget="${esc(d.id)}">${icon("plus")}${esc(d.name)}</button>`).join("")}</div>` : ""}
    <button class="btn small primary" data-menu-close>Close</button>`, "Add to Home");
}

function addWidget(w) {
  const existing = find(w.id);
  if (existing) existing.hidden = false;
  else draft.widgets.push(w);
  closeMenu();
  renderHome();
  $(`#home .widget[data-wid="${CSS.escape(w.id)}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// --- hold to move ---
let drag = null;
function setupDrag(el) {
  el.addEventListener("pointerdown", (e) => {
    if (!isEditing() || e.button > 0 || e.target.closest("button, select")) return;
    const box = e.target.closest(".widget");
    if (!box) return;
    drag = { box, id: box.dataset.wid, x: e.clientX, y: e.clientY, started: false };
    drag.timer = setTimeout(() => {
      if (!drag) return;
      const r = box.getBoundingClientRect();
      Object.assign(drag, { started: true, grabX: drag.x - r.left, grabY: drag.y - r.top });
      box.classList.add("dragging");
      haptic(12);
    }, 220);
  });
  window.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (!drag.started) {
      if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 10) { clearTimeout(drag.timer); drag = null; }  // a scroll
      return;
    }
    const grid = el.querySelector(".home-grid");
    const hit = document.elementFromPoint(e.clientX, e.clientY)?.closest(".widget");
    if (hit && hit !== drag.box && grid.contains(hit)) {
      const boxes = [...grid.children];
      grid.insertBefore(drag.box, boxes.indexOf(drag.box) < boxes.indexOf(hit) ? hit.nextSibling : hit);
    }
    const g = grid.getBoundingClientRect();
    const tx = e.clientX - g.left - drag.grabX - drag.box.offsetLeft;
    const ty = e.clientY - g.top - drag.grabY - drag.box.offsetTop;
    drag.box.style.transform = `translate(${tx}px, ${ty}px) scale(1.04)`;
  });
  const drop = () => {
    if (!drag) return;
    clearTimeout(drag.timer);
    const { box, started } = drag;
    drag = null;
    if (!started) return;
    box.classList.remove("dragging");
    box.style.transform = "";
    const order = [...el.querySelectorAll(".home-grid > .widget")].map((b) => b.dataset.wid);
    draft.widgets.sort((a, b) => (a.hidden - b.hidden) || order.indexOf(a.id) - order.indexOf(b.id));
    box.classList.add("dropped");
    setTimeout(() => box.classList.remove("dropped"), 260);
  };
  window.addEventListener("pointerup", drop);
  window.addEventListener("pointercancel", drop);
  // Once a drag has started, the page mustn't scroll under the finger.
  el.addEventListener("touchmove", (e) => { if (drag?.started) e.preventDefault(); }, { passive: false });
}

// --- drag a corner to resize (a tap steps through the sizes) ---
function setupResize(el) {
  let rs = null;
  el.addEventListener("pointerdown", (e) => {
    const h = e.target.closest("[data-resize]");
    if (!h || !isEditing()) return;
    e.preventDefault();
    e.stopPropagation();
    const box = h.closest(".widget");
    const grid = el.querySelector(".home-grid");
    const cs = getComputedStyle(grid);
    const col = parseFloat(cs.gridTemplateColumns.split(" ")[0]) || 150;
    const row = parseFloat(cs.gridAutoRows) || col;
    const r = box.getBoundingClientRect();
    rs = { box, id: box.dataset.wid, left: r.left, top: r.top, col, row, x: e.clientX, y: e.clientY, moved: false };
    h.setPointerCapture?.(e.pointerId);
  });
  el.addEventListener("pointermove", (e) => {
    if (!rs) return;
    if (Math.hypot(e.clientX - rs.x, e.clientY - rs.y) > 8) rs.moved = true;
    if (!rs.moved) return;
    const wide = e.clientX - rs.left > rs.col * 1.4;
    const tall = e.clientY - rs.top > rs.row * 1.4;
    setSize(rs.id, tall ? "2x2" : wide ? "2x1" : "1x1");
  });
  const end = () => {
    if (!rs) return;
    const { id, moved } = rs;
    rs = null;
    if (!moved) {
      const w = find(id);
      if (w) setSize(id, SIZES[(SIZES.indexOf(w.size) + 1) % SIZES.length]);
    }
    haptic(8);
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
}

// ---------- events ----------
export function setupHome({ goRoom, showAmbient }) {
  const el = $("#home");
  setupDrag(el);
  setupResize(el);

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
    if (mv) { move(mv.dataset.wid, Number(mv.dataset.move)); return widgetMenu(mv.dataset.wid); }
    const hide = t.closest("[data-hide-id]");
    if (hide) { find(hide.dataset.hideId).hidden = true; closeMenu(); return renderHome(); }
    const un = t.closest("[data-unhide]");
    if (un) return addWidget(find(un.dataset.unhide));
    if (t.closest("[data-add-zone]")) {
      return addWidget({ id: `zone-${Date.now().toString(36)}`, type: "zone", size: "1x1", hidden: false,
                         options: { tz: null, label: "US" } });
    }
    const dev = t.closest("[data-add-device-widget]");
    if (dev) {
      const id = dev.dataset.addDeviceWidget;
      return addWidget({ id: `dev-${id}`.slice(0, 64), type: "device", size: isMedia(store.devices.get(id) || {}) ? "2x1" : "1x1",
                         hidden: false, options: { device_id: id } });
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
