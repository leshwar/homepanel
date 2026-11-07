// Bottom sheet with the full controls for one device. Lights get a big brightness
// pill, a color wheel and a warm-to-cool slider; TVs get the remote (remote.js);
// robot vacuums get their own layout (vacuum.js). Controls come from the device's caps.

import { api } from "./api.js";
import { store, command } from "./store.js";
import { $, esc, icon, glowVar, isMedia, kelvinToRgb, toast } from "./util.js";
import { openSettings } from "./settings.js";
import { remoteBody, attachRemote, remoteClick, remoteBusy, startRepeat, stopTilt, cancelRemoteInteraction, onRemoteChange } from "./remote.js";
import { deviceHeading, powerControls, controlGestureBusy, clearControlGestures } from "./device-controls.js";
import { setMarkup, invalidateMarkup } from "./render.js";
import { purifierBody } from "./purifier.js";

import { vacuumBody, picked } from "./vacuum.js";
import { effectsBody, effectsClick, attachEffects, effectsBusy, keepEffects } from "./effects.js";
import { simpleSpeaker, speakerTop, speakerBody, attachSpeaker, speakerBusy, clearSpeakerInteraction } from "./speaker.js";
const sheetState = { shownId: null, missed: false, force: false };
const pressedPointers = new Set();
let pendingClick = null;

let currentId = null;
let dragging = null;
let cancelLightDrag = () => {};
let returnFocus = null;

const KMIN = 2200, KMAX = 6500;
const WHITE_PRESETS = [{ k: 2700, name: "Warm white" }, { k: 4000, name: "Neutral white" }, { k: 6000, name: "Daylight" }];
const COLOR_PRESETS = [
  { c: "#ff5a3c", name: "Red" }, { c: "#ffa53c", name: "Amber" }, { c: "#5ee07a", name: "Green" },
  { c: "#3fd6d0", name: "Teal" }, { c: "#4f7bff", name: "Blue" }, { c: "#a35cff", name: "Purple" }, { c: "#ff5cb8", name: "Pink" },
];

export const isSheetOpen = () => !$("#sheet").hidden;

let closing = null;
export function openDevice(id) {
  cancelLightDrag(); clearControlGestures(); cancelRemoteInteraction();
  pressedPointers.clear();
  pendingClick = null;
  sheetState.missed = false; sheetState.force = false;
  if (!isSheetOpen()) returnFocus = document.activeElement;
  clearSpeakerInteraction();
  clearTimeout(closing);
  $("#sheet").classList.remove("closing"); $("#scrim").classList.remove("closing");
  currentId = id;
  render(true);
  $("#scrim").hidden = false;
  $("#sheet").hidden = false;
  $("#sheet").focus?.();
}

export function closeSheet() {
  cancelLightDrag(); clearControlGestures(); cancelRemoteInteraction();
  pressedPointers.clear();
  pendingClick = null;
  clearSpeakerInteraction();
  currentId = null;
  const sheet = $("#sheet"), scrim = $("#scrim");
  if (sheet.hidden) return;
  sheet.classList.add("closing"); scrim.classList.add("closing");   // slides away (shell.css), then hides
  clearTimeout(closing);
  closing = setTimeout(() => {
    sheet.hidden = true; scrim.hidden = true;
    sheet.classList.remove("closing"); scrim.classList.remove("closing");
    if (returnFocus?.isConnected) returnFocus.focus?.({ preventScroll: true });
  }, matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 220);
}

// Closing: forget what was shown and stop aiming by tilt (watched, so closeSheet stays simple).
new MutationObserver(() => { if ($("#sheet").hidden) { sheetState.shownId = null; stopTilt(); } })
  .observe($("#sheet"), { attributes: true, attributeFilter: ["hidden"] });

export function refreshSheet(id, force = false) {
  if (!currentId) return;
  if (id && id !== currentId) return;
  if (pendingClick || pressedPointers.size || dragging || controlGestureBusy() || remoteBusy.active || effectsBusy() || speakerBusy()) {
    sheetState.missed = true; sheetState.force ||= force; return;
  }
  force ||= sheetState.force;
  sheetState.force = false;
  sheetState.missed = false;
  if (!store.devices.has(currentId)) return closeSheet();
  render(force);
}
onRemoteChange(() => refreshSheet(), () => { if (sheetState.missed) refreshSheet(); });

const hex = ({ r, g, b }) => "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
const rgbOf = (c) => ({ r: parseInt(c.slice(1, 3), 16), g: parseInt(c.slice(3, 5), 16), b: parseInt(c.slice(5, 7), 16) });
const has = (d, c) => d.caps.includes(c);
const isLight = (d) => d.kind === "light" || has(d, "brightness") || has(d, "color") || has(d, "color_temp");

function render(force = false) {
  const d = store.devices.get(currentId);
  if (!d) return;
  const s = d.state || {};
  const sheet = $("#sheet");
  const tv = isMedia(d);              // TVs and speakers share the remote
  const speaker = simpleSpeaker(d);
  const vac = has(d, "clean");
  let notes = "";

  if (s.needs_pairing) {
    notes += `<div class="note">${esc(s.error || "This device needs to be paired.")}
      ${d.kind === "tv" ? "<br>Turn the TV on, tap Pair, then accept the prompt on the TV screen." : ""}</div>
      <button class="btn primary" data-pair>${icon("link")}Pair now</button>`;
  } else if (s.online === false) {
    notes += `<div class="note warn">${esc(s.error || "This device isn't responding.")}
      Check its power and connection. For account-connected devices, check the device's app and account sign-in.</div>
      <button class="btn" data-refresh>${icon("search")}Try again</button>`;
  }
  const blocked = !!s.needs_pairing || s.online === false;

  let body = notes;
  if (!blocked) {
    if (!speaker) body += powerControls(d);
    if (tv) body += speaker ? speakerBody(d) : remoteBody(d);
    else if (vac) body += vacuumBody(d);
    else if (d.kind === "purifier") body += purifierBody(d);
    else if (isLight(d)) body += lightBody(d);
    else if (!has(d, "power")) body += '<p class="control-help">No controls are reported for this device.</p>';
    if (!speaker && ((has(d, "power") && typeof s.on !== "boolean")
      || ["brightness", "color_temp"].some(cap => has(d, cap) && !Number.isFinite(s[cap])))) {
      body += '<button class="btn" data-refresh>Refresh status</button>';
    }
    if (!tv && s.power_w != null) body += `<div class="section-label"><span>Energy</span></div><div id="energy">${energyHtml(d, s)}</div>`;
  }

  // keep scroll positions (sheet, app pages) across re-renders of the same device
  const same = sheetState.shownId === d.id;
  if (!same) stopTilt();
  sheetState.shownId = d.id;
  const keep = same ? { top: sheet.scrollTop, pages: $("#sheet [data-keep-scroll]")?.scrollLeft || 0 } : { top: 0, pages: 0 };
  const focused = same && sheet.contains(document.activeElement) ? document.activeElement : null;
  const focusAttribute = focused && [...focused.attributes].find(a => a.name.startsWith("data-") && a.name !== "data-repeat");
  const focusKey = focused?.id ? `#${CSS.escape(focused.id)}`
    : focusAttribute ? `[${focusAttribute.name}="${CSS.escape(focusAttribute.value)}"]`
      : focused?.tagName === "SUMMARY" && focused.parentElement.dataset.controlSection
        ? `[data-control-section="${focused.parentElement.dataset.controlSection}"] > summary` : null;
  const sections = same ? new Map([...sheet.querySelectorAll("details[data-control-section]")].map(el => [el.dataset.controlSection, el.open])) : new Map();
  const advancedOpen = same && !!sheet.querySelector(".speaker-advanced")?.open;
  const head = speaker ? speakerTop(d) : deviceHeading(d);
  sheet.classList.toggle("sheet-tv", tv && !speaker);
  sheet.classList.toggle("sheet-speaker", speaker);
  sheet.classList.toggle("sheet-vac", !tv && vac);
  sheet.classList.toggle("sheet-light", !tv && !vac && isLight(d));
  sheet.classList.toggle("sheet-purifier", d.kind === "purifier");
  sheet.style.setProperty("--glow", glowVar(d));
  sheet.dataset.deviceId = d.id;
  sheet.setAttribute("aria-label", `${d.name} controls`);
  keepEffects(sheet, same);
  const markup = `
    <div class="grab" aria-hidden="true"></div>
    ${head}
    <div class="sheet-body">${body}</div>
    <div class="meta-line"><span>${esc(d.room || "No room")}. ${esc(d.adapter_name)}${d.meta?.model ? `, ${esc(d.meta.model)}` : ""}</span>
      <button class="link" data-edit>Edit device</button></div>`;
  if (!same || force) invalidateMarkup(sheet);
  if (!setMarkup(sheet, markup)) return;
  sheet.scrollTop = keep.top;
  const pages = $("#sheet [data-keep-scroll]");
  if (pages) pages.scrollLeft = keep.pages;
  if (advancedOpen && sheet.querySelector(".speaker-advanced")) sheet.querySelector(".speaker-advanced").open = true;
  for (const section of sheet.querySelectorAll("details[data-control-section]")) {
    if (sections.has(section.dataset.controlSection)) section.open = sections.get(section.dataset.controlSection);
  }

  if (!tv && s.power_w != null) loadEnergy(d.id);
  const mapImg = $("#sheet .vac-map img");
  if (mapImg) {
    const finishMap = (available) => {
      mapImg.parentNode.classList.remove("loading");
      mapImg.parentNode.classList.toggle("empty", !available);
      mapImg.parentNode.setAttribute("aria-busy", "false");
      if (!available) mapImg.nextElementSibling.textContent = "Map unavailable. Refresh status or check the device's app.";
    };
    mapImg.addEventListener("error", () => finishMap(false));
    mapImg.addEventListener("load", () => finishMap(true));
    if (mapImg.complete) finishMap(mapImg.naturalWidth > 0);
  }
  if (speaker && !blocked) attachSpeaker(sheet, d, () => refreshSheet(d.id, true));
  else if (tv) attachRemote(sheet, d);
  if (focusKey) sheet.querySelector(focusKey)?.focus({ preventScroll: true });
  if (!blocked && isLight(d)) {
    attachLight(d);
    attachEffects(sheet, d, () => refreshSheet(d.id, true));
  }
}

// ---------- lights ----------
function lightBody(d) {
  const s = d.state || {};
  const on = s.on !== false;
  const dim = has(d, "brightness");
  const brightnessKnown = Number.isFinite(s.brightness);
  const level = on ? (dim ? s.brightness ?? 0 : 100) : 0;
  const colorOn = on && s.color_mode === "color" && s.color;
  const tempOn = on && s.color_mode !== "color" && s.color_temp;
  const temperatureKnown = Number.isFinite(s.color_temp);
  const k = Math.max(KMIN, Math.min(KMAX, s.color_temp || 3000));
  const kPct = ((k - KMIN) / (KMAX - KMIN)) * 100;

  const tone = `${on ? "on" : ""} ${level >= 86 ? "high" : ""} ${level >= 16 ? "lit" : ""}`;
  const value = !brightnessKnown ? "Not reported" : on ? `${level}%` : "Off";
  const pill = dim ? `<div class="pill-wrap"><h3>Brightness</h3><output class="control-value" id="bri-val">${value}</output>
    <div class="pill ${tone}" id="bri" role="slider" tabindex="${brightnessKnown ? 0 : -1}"
      aria-label="Brightness" aria-disabled="${!brightnessKnown}" aria-valuemin="${has(d, "power") ? 0 : 1}" aria-valuemax="100"
      aria-valuenow="${level}" aria-valuetext="${value}">
      <div class="pill-fill" style="height:${level}%"></div>
      <span class="pill-icon">${icon(on ? "bulb" : "power")}</span>
    </div><p class="hint">${brightnessKnown ? "Drag up or down.<br>Release to apply." : "No level reported."}</p></div>` : "";

  let side = "";
  if (has(d, "color")) {
    const pos = colorOn ? wheelPos(s.color) : { x: 50, y: 50 };
    side = `<div class="wheel-wrap"><h3>Color</h3><div class="wheel" id="wheel" role="slider" tabindex="0" aria-label="Color"
        aria-valuetext="${colorOn ? hex(s.color) : "None"}">
        <i class="wheel-thumb ${colorOn ? "" : "idle"}" style="left:${pos.x}%;top:${pos.y}%;${colorOn ? `background:${hex(s.color)}` : ""}"></i>
      </div></div>`;
  } else if (has(d, "color_temp")) {
    side = `<div class="pill-wrap"><h3>White tone</h3><div class="pill temp" id="ct" role="slider" tabindex="${temperatureKnown ? 0 : -1}" aria-label="White temperature"
        aria-disabled="${!temperatureKnown}" aria-valuemin="${KMIN}" aria-valuemax="${KMAX}" aria-valuenow="${k}" aria-valuetext="${temperatureKnown ? `${k} kelvin` : "Not reported"}">
        <i class="temp-thumb ${tempOn ? "" : "idle"}" style="--p:${kPct}"></i>
        <b class="pill-val">${temperatureKnown ? tempWord(k) : "Unknown"}</b><span class="pill-icon">${icon("warm")}</span>
      </div><p class="hint">Drag warm to cool.<br>Release to apply.</p></div>`;
  }

  const strip = has(d, "color") && has(d, "color_temp") ? `
    <div class="section-label"><span>White</span><b id="ct-val">${tempOn ? tempWord(k) : ""}</b></div>
    <div class="temp-strip" id="ct" role="slider" tabindex="${temperatureKnown ? 0 : -1}" aria-label="White temperature"
      aria-disabled="${!temperatureKnown}" aria-valuemin="${KMIN}" aria-valuemax="${KMAX}" aria-valuenow="${k}" aria-valuetext="${temperatureKnown ? `${k} kelvin` : "Not reported"}">
      <i class="temp-thumb ${tempOn ? "" : "idle"}" style="--p:${kPct}"></i></div>
    <div class="temp-ends" aria-hidden="true"><span>Warm</span><span>Cool</span></div>
    <p class="hint">Drag to adjust; release to apply.</p>` : "";

  const whites = has(d, "color_temp") ? WHITE_PRESETS.slice(0, has(d, "color") ? 2 : 3) : [];
  const colors = has(d, "color") ? COLOR_PRESETS.slice(0, has(d, "color_temp") ? 4 : 6) : [];
  const cur = s.color ? hex(s.color) : "";
  const presets = whites.length + colors.length ? `<div class="presets" role="group" aria-label="Presets">
      ${whites.map((w) => `<button class="swatch" data-kelvin="${w.k}" style="--sw:rgb(${kelvinToRgb(w.k).join(" ")})"
        aria-label="${w.name}" aria-pressed="${!!(tempOn && Math.abs(s.color_temp - w.k) < 300)}"></button>`).join("")}
      ${colors.map((c) => `<button class="swatch" data-color="${c.c}" style="--sw:${c.c}" aria-label="${c.name}"
        aria-pressed="${!!(colorOn && cur === c.c)}"></button>`).join("")}</div>` : "";

  const more = strip + presets;
  return `<div class="light ${strip ? "wide" : ""}"><div class="light-ctl">${pill}${side}</div>${more ? `<div class="light-more">${more}</div>` : ""}</div>`
    + effectsBody(d);
}

const tempWord = (k) => (k < 3000 ? "Warm" : k < 4500 ? "Neutral" : "Cool");

function rgbToHs({ r, g, b }) {
  const max = Math.max(r, g, b), min = Math.min(r, g, b), c = max - min;
  let h = 0;
  if (c) h = max === r ? ((g - b) / c) % 6 : max === g ? (b - r) / c + 2 : (r - g) / c + 4;
  return { h: (h * 60 + 360) % 360, s: max ? c / max : 0 };
}
function hsToHex(h, s) {
  const f = (n) => { const k = (n + h / 60) % 6; return Math.round(255 * (1 - s * Math.max(0, Math.min(k, 4 - k, 1)))); };
  return hex({ r: f(5), g: f(3), b: f(1) });
}
function wheelPos(rgb) {
  const { h, s } = rgbToHs(rgb);
  const rad = (h * Math.PI) / 180;
  return { x: 50 + 50 * s * Math.sin(rad), y: 50 - 50 * s * Math.cos(rad) };
}

// Pointer drag helper: calls move(x, y, rect, final) with client coordinates, tap() for a short
// touch that didn't move. Holds re-renders while the finger is down.
function drag(el, { move, tap }) {
  let start = null;
  el.addEventListener("pointerdown", (e) => {
    if (e.button > 0 || dragging || el.getAttribute("aria-disabled") === "true") return;
    e.preventDefault();
    try { el.setPointerCapture(e.pointerId); } catch { /* not a real pointer (tests) */ }
    el.focus({ preventScroll: true });
    cancelLightDrag = () => { start = null; dragging = null; };
    start = { pointer: e.pointerId, x: e.clientX, y: e.clientY, moved: false, rect: el.getBoundingClientRect() };
    dragging = start;
  });
  el.addEventListener("pointermove", (e) => {
    if (!start || start.pointer !== e.pointerId) return;
    if (!start.moved && Math.hypot(e.clientX - start.x, e.clientY - start.y) < 6) return;
    start.moved = true;
    move(e.clientX, e.clientY, start, false);
  });
  const end = async (e) => {
    if (!start || start.pointer !== e.pointerId) return;
    const s = start;
    start = null;
    if (e.type === "pointerup") {
      if (tap && !s.moved) await tap(e.clientX, e.clientY, s);
      else if (s.moved) await move(e.clientX, e.clientY, s, true);
    }
    if (dragging === s) { dragging = null; refreshSheet(undefined, true); }
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  el.addEventListener("lostpointercapture", end);
}

function attachLight(dev) {
  // Handlers read the live device: updates can replace it while the sheet stays the same.
  const d = { id: dev.id, get state() { return (store.devices.get(dev.id) || dev).state || {}; } };
  const s = d.state;
  const sheet = $("#sheet");
  const bri = $("#bri");
  if (bri) {
    const fill = bri.querySelector(".pill-fill"), val = $("#bri-val");
    const shown = (v) => {
      fill.style.height = `${v}%`;
      val.textContent = v ? `${v}%` : "Off";
      bri.classList.toggle("on", v > 0);
      bri.classList.toggle("high", v >= 86);
      bri.classList.toggle("lit", v >= 16);
      bri.setAttribute("aria-valuenow", v);
      bri.setAttribute("aria-valuetext", v ? `${v}%` : "Off");
    };
    drag(bri, {
      move: (x, y, st, final) => {
        if (st.base == null) st.base = d.state?.on === false ? 0 : d.state.brightness;
        const v = Math.max(has(dev, "power") ? 0 : 1, Math.min(100, Math.round(st.base + ((st.y - y) / st.rect.height) * 100)));
        shown(v);
        if (final) {
          if (v === 0) return command(d.id, "power", false, { on: false });
          return command(d.id, "brightness", v, { on: true, brightness: v });
        }
      },
    });
    bri.addEventListener("keydown", (e) => {
      if (bri.getAttribute("aria-disabled") === "true") return;
      const cur = d.state?.on === false ? 0 : d.state.brightness;
      const step = { ArrowUp: 10, ArrowRight: 10, ArrowDown: -10, ArrowLeft: -10 }[e.key];
      if (!step && !["Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const v = Math.max(has(dev, "power") ? 0 : 1, Math.min(100, e.key === "Home" ? 0 : e.key === "End" ? 100 : cur + step));
      shown(v);
      if (v === 0) command(d.id, "power", false, { on: false });
      else command(d.id, "brightness", v, { on: true, brightness: v });
    });
  }

  const wheel = $("#wheel");
  if (wheel) {
    const thumb = wheel.querySelector(".wheel-thumb");
    let last = s.color ? hex(s.color) : "#ffffff";
    const pick = (x, y, st, final) => {
      const r = st.rect, cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      let dx = x - cx, dy = y - cy;
      const dist = Math.hypot(dx, dy), max = r.width / 2;
      if (dist > max) { dx *= max / dist; dy *= max / dist; }
      const h = ((Math.atan2(dx, -dy) * 180) / Math.PI + 360) % 360;
      const raw = Math.min(1, Math.hypot(dx, dy) / max);
      const sat = raw > 0.93 ? 1 : raw;          // the outer rim snaps to the pure color
      last = hsToHex(h, sat);
      thumb.classList.remove("idle");
      thumb.style.left = `${50 + (dx / max) * 50}%`;
      thumb.style.top = `${50 + (dy / max) * 50}%`;
      thumb.style.background = last;
      const rgb = rgbOf(last);
      sheet.style.setProperty("--glow", glowFromRgb(rgb));
      if (final) return command(d.id, "color", last, { on: true, color: rgb, color_mode: "color" });
    };
    drag(wheel, { move: pick, tap: (x, y, st) => pick(x, y, st, true) });
    wheel.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 15, ArrowUp: 15, ArrowLeft: -15, ArrowDown: -15 }[e.key];
      if (!step) return;
      e.preventDefault();
      const { h } = rgbToHs(rgbOf(last));
      last = hsToHex((h + step + 360) % 360, 1);
      command(d.id, "color", last, { on: true, color: rgbOf(last), color_mode: "color" });
    });
  }

  for (const ct of document.querySelectorAll("#sheet #ct")) {
    const thumb = ct.querySelector(".temp-thumb");
    const vertical = ct.classList.contains("pill");
    const set = (k, final) => {
      const pct = ((k - KMIN) / (KMAX - KMIN)) * 100;
      thumb.classList.remove("idle");
      thumb.style.setProperty("--p", pct);
      ct.setAttribute("aria-valuenow", k);
      ct.setAttribute("aria-valuetext", `${k} kelvin`);
      const word = vertical ? ct.querySelector(".pill-val") : $("#ct-val");
      if (word) word.textContent = tempWord(k);
      sheet.style.setProperty("--glow", glowFromRgb(rgbOfKelvin(k)));
      if (final) return command(d.id, "color_temp", k, { on: true, color_temp: k, color_mode: "temp" });
    };
    drag(ct, {
      move: (x, y, st, final) => {
        const r = st.rect;
        if (st.base == null) st.base = d.state?.color_temp || 3000;
        const change = vertical ? (st.y - y) / r.height : (x - st.x) / r.width;
        return set(Math.round(Math.max(KMIN, Math.min(KMAX, st.base + change * (KMAX - KMIN)))), final);
      },
    });
    ct.addEventListener("keydown", (e) => {
      if (ct.getAttribute("aria-disabled") === "true") return;
      const step = { ArrowRight: 300, ArrowUp: 300, ArrowLeft: -300, ArrowDown: -300 }[e.key];
      if (!step && !["Home", "End"].includes(e.key)) return;
      e.preventDefault();
      set(Math.max(KMIN, Math.min(KMAX, e.key === "Home" ? KMIN : e.key === "End" ? KMAX : d.state.color_temp + step)), true);
    });
  }
}

const rgbOfKelvin = (k) => { const [r, g, b] = kelvinToRgb(k); return { r, g, b }; };
function glowFromRgb({ r, g, b }) {
  const max = Math.max(r, g, b, 1);
  return [r, g, b].map((v) => Math.round((v / max) * 255)).join(" ");
}

// ---------- energy ----------
let energy = { id: null, at: 0, data: null };

function energyHtml(d, s) {
  const e = energy.id === d.id ? energy.data : null;
  const failure = energy.id === d.id && energy.error
    ? `<p class="note warn">${esc(energy.error)}${e ? " Showing the last available history." : ""}</p><button class="btn" data-energy-refresh>Retry history</button>` : "";
  const stats = `<div class="energy-stats">
      <div><b>${s.power_w} W</b><span>Using now</span></div>
      ${e ? `<div><b>${e.today_kwh.toFixed(2)}</b><span>kWh today</span></div>
             <div><b>${e.week_kwh.toFixed(1)}</b><span>kWh this week</span></div>` : ""}
    </div>`;
  if (!e) return stats + failure;
  const max = Math.max(...e.days.map((x) => x.kwh), 0.001);
  const bars = e.days.map((x, i) => {
    const day = new Date(x.date + "T12:00:00").toLocaleDateString([], { weekday: "short" });
    return `<div class="bar ${i === e.days.length - 1 ? "today" : ""}" title="${x.kwh} kWh">
      <i style="height:${Math.max(2, (x.kwh / max) * 100)}%"></i><span>${i === e.days.length - 1 ? "Today" : day}</span></div>`;
  }).join("");
  return stats + `<div class="bars" role="img" aria-label="Energy per day for the last 7 days">${bars}</div>` + failure;
}

async function loadEnergy(id) {
  if (energy.id === id && Date.now() - energy.at < 60_000) return;
  energy = { id, at: Date.now(), data: energy.id === id ? energy.data : null };
  try {
    const data = await api.energy(id);
    if (energy.id !== id) return;
    energy.data = data;
    const d = store.devices.get(id);
    const el = $("#energy");
    if (d && el && currentId === id) el.innerHTML = energyHtml(d, d.state || {});
  } catch (error) {
    if (energy.id !== id) return;
    energy.error = error.message;
    const d = store.devices.get(id), el = $("#energy");
    if (d && el && currentId === id) el.innerHTML = energyHtml(d, d.state || {});
  }
}

// ---------- events ----------
$("#scrim").addEventListener("click", closeSheet);
$("#sheet").addEventListener("pointerdown", e => {
  if (e.button > 0) return;
  pressedPointers.add(e.pointerId);
  const control = e.target.closest("button, summary");
  pendingClick = control?.matches(":disabled") ? null : control;
}, { capture: true });
for (const event of ["pointerup", "pointercancel"]) addEventListener(event, e => {
  pressedPointers.delete(e.pointerId);
  const box = pendingClick?.getBoundingClientRect();
  if (event === "pointercancel" || (box && (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom))) {
    pendingClick = null;
  }
  if (!pendingClick) setTimeout(() => { if (sheetState.missed) refreshSheet(); }, 0);
});
addEventListener("blur", () => {
  pendingClick = null;
  pressedPointers.clear();
  cancelLightDrag();
  clearControlGestures();
  refreshSheet(undefined, true);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isSheetOpen()) closeSheet(); });
$("#sheet").addEventListener("keydown", (e) => {
  if (e.key !== "Tab") return;
  const items = [...$("#sheet").querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), summary, a[href], [tabindex="0"]')]
    .filter(el => el.getClientRects().length && el.getAttribute("aria-disabled") !== "true");
  const first = items[0], last = items.at(-1);
  if (e.shiftKey && (document.activeElement === first || document.activeElement === $("#sheet"))) {
    e.preventDefault(); last?.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault(); first?.focus();
  }
});

// Remote keys don't change what the sheet shows, so they skip the optimistic update.
const sendKey = (d) => (action, value) => api.command(d.id, action, value).catch((err) => toast(err.message, true));

$("#sheet").addEventListener("pointerdown", (e) => {
  const d = store.devices.get(currentId);
  if (d && isMedia(d)) startRepeat(e, sendKey(d));
});

$("#sheet").addEventListener("click", async (e) => {
  const d = store.devices.get(currentId);
  if (!d) return;
  const t = (sel) => e.target.closest(sel);
  if (t("[data-close]")) return closeSheet();
  if (t("[data-edit]")) { const id = d.id; closeSheet(); return openSettings("device", id); }
  if (t("[data-energy-refresh]")) { energy.at = 0; return loadEnergy(d.id); }
  if (t("[data-power]")) { const on = !d.state?.on; return command(d.id, "power", on, { on }); }
  if (t("[data-mute]")) { const m = !d.state?.muted; return command(d.id, "mute", m, { muted: m }); }
  if (t("[data-fan-mode]")) {
    const value = t("[data-fan-mode]").dataset.fanMode;
    return command(d.id, "set_fan_mode", value, { on: true, fan_mode: value });
  }
  if (t("[data-fan-speed]")) {
    const value = t("[data-fan-speed]").dataset.fanSpeed;
    return command(d.id, "set_fan_speed", value, { on: true, fan_mode: "manual", fan_speed: value });
  }
  if (t("[data-app]")) { const a = t("[data-app]").dataset.app; return command(d.id, "launch_app", a, { app: a, input: null }); }
  if (t("[data-input]")) { const i = t("[data-input]").dataset.input; return command(d.id, "set_input", i, { input: i, app: null }); }
  if (t("[data-sound-mode]")) { const m = t("[data-sound-mode]").dataset.soundMode; return command(d.id, "set_sound_mode", m, { sound_mode: m }); }
  if (isMedia(d)) {
    const r = remoteClick(e, d, sendKey(d));
    if (r === "render") return render();
    if (r) return;
  }
  if (isLight(d)) {
    const r = effectsClick(e, d);
    if (r === "render") return render();
    if (r) return;
  }
  if (t("[data-kelvin]")) { const k = +t("[data-kelvin]").dataset.kelvin; return command(d.id, "color_temp", k, { on: true, color_temp: k, color_mode: "temp" }); }
  if (t("[data-color]")) {
    const c = t("[data-color]").dataset.color;
    return command(d.id, "color", c, { on: true, color: rgbOf(c), color_mode: "color" });
  }
  if (t("[data-clean]")) {
    const b = t("[data-clean]"); const activity = b.dataset.activity;
    return command(d.id, "clean", b.dataset.clean, { activity, on: activity === "cleaning" });
  }
  if (t("[data-dock]")) return command(d.id, "dock", null, { activity: "returning", on: true });
  if (t("[data-room-pick]")) {
    const id = t("[data-room-pick]").dataset.roomPick; const set = picked(d.id);
    set.has(id) ? set.delete(id) : set.add(id);
    return render();
  }
  if (t("[data-rooms-clear]")) { picked(d.id).clear(); return render(); }
  if (t("[data-clean-rooms]")) {
    const ids = [...picked(d.id)].map((x) => (/^\d+$/.test(x) ? Number(x) : x));
    picked(d.id).clear();
    return command(d.id, "clean_rooms", ids, { activity: "cleaning", on: true });
  }
  if (t("[data-suction]")) { const v = t("[data-suction]").dataset.suction; return command(d.id, "set_suction", v, { suction: v }); }
  if (t("[data-clean-mode]")) { const v = t("[data-clean-mode]").dataset.cleanMode; return command(d.id, "set_clean_mode", v, { clean_mode: v }); }
  if (t("[data-station]")) {
    const b = t("[data-station]");
    if (await command(d.id, "station", b.dataset.station)) toast(`${b.textContent.trim()}: sent to the station`);
    return;
  }
  if (t("[data-locate]")) { if (await command(d.id, "locate")) toast("Your vacuum is making a sound"); return; }
  if (t("[data-pair]")) {
    const b = t("[data-pair]");
    b.disabled = true; b.textContent = "Waiting for the device…";
    try { await api.pair(d.id); toast(`${d.name} is paired`); } catch (err) { toast(err.message, true); }
    return render();
  }
  if (t("[data-refresh]")) {
    try { await api.refresh(d.id); } catch (err) { toast(err.message, true); }
  }
});

// Touch browsers may dispatch click after pointerup; retain the target until then.
$("#sheet").addEventListener("click", () => {
  pendingClick = null;
  setTimeout(() => { if (sheetState.missed) refreshSheet(); }, 0);
});
$("#sheet").addEventListener("contextmenu", () => {
  pendingClick = null;
  pressedPointers.clear();
  setTimeout(() => { if (sheetState.missed) refreshSheet(); }, 0);
});
