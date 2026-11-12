// The light panel. Stage: one tall brightness bar, filled in the lamp's own colour.
// Tabs: Color (wheel + presets), White (warm-to-cool strip + presets), then whatever
// effects the light lists (effects.js). Everything comes from the device's caps.
//
// Safety, unchanged from the first design: a tap never changes anything; a drag
// previews while the finger is down and sends one command on release.

import { store, command } from "./store.js";
import { esc, icon, kelvinToRgb } from "./util.js";
import { effectTabs } from "./effects.js";
import { powerHero } from "./panel.js";

const KMIN = 2200, KMAX = 6500;
const WHITE_PRESETS = [{ k: 2700, name: "Warm white" }, { k: 4000, name: "Neutral white" }, { k: 6000, name: "Daylight" }];
const COLOR_PRESETS = [
  { c: "#ff5a3c", name: "Red" }, { c: "#ffa53c", name: "Amber" }, { c: "#ffe14d", name: "Yellow" }, { c: "#5ee07a", name: "Green" },
  { c: "#3fd6d0", name: "Teal" }, { c: "#4f7bff", name: "Blue" }, { c: "#a35cff", name: "Purple" }, { c: "#ff5cb8", name: "Pink" },
];

const has = (d, c) => d.caps.includes(c);
export const isLight = (d) => d.kind === "light" || has(d, "brightness") || has(d, "color") || has(d, "color_temp");

const hex = ({ r, g, b }) => "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
export const rgbOf = (c) => ({ r: parseInt(c.slice(1, 3), 16), g: parseInt(c.slice(3, 5), 16), b: parseInt(c.slice(5, 7), 16) });
export const tempWord = (k) => (k < 3000 ? "Warm" : k < 4500 ? "Neutral" : "Cool");
const clampK = (k) => Math.max(KMIN, Math.min(KMAX, k));

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
const rgbOfKelvin = (k) => { const [r, g, b] = kelvinToRgb(k); return { r, g, b }; };
function glowFromRgb({ r, g, b }) {
  const max = Math.max(r, g, b, 1);
  return [r, g, b].map((v) => Math.round((v / max) * 255)).join(" ");
}

// ---------- markup ----------
function brightnessBar(d, s) {
  const on = s.on !== false;
  const known = Number.isFinite(s.brightness);
  const level = on ? s.brightness ?? 0 : 0;
  const value = !known ? "Not reported" : on ? `${level}%` : "Off";
  const tone = `${on ? "on" : ""} ${level >= 86 ? "high" : ""} ${level >= 16 ? "lit" : ""}`;
  return `<div class="light-stage">
    <div class="pill ${tone}" id="bri" role="slider" tabindex="${known ? 0 : -1}" aria-label="Brightness" aria-disabled="${!known}"
      aria-valuemin="${has(d, "power") ? 0 : 1}" aria-valuemax="100" aria-valuenow="${level}" aria-valuetext="${value}">
      <div class="pill-fill" style="height:${level}%"></div>
      <output class="pill-val" id="bri-val">${value}</output>
      <span class="pill-icon">${icon(on ? "bulb" : "power")}</span>
    </div>
    ${known ? "" : `<button class="btn small" data-refresh>Refresh status</button>`}
  </div>`;
}

function colorPane(s) {
  const colorOn = s.on !== false && s.color_mode === "color" && s.color;
  const pos = colorOn ? wheelPos(s.color) : { x: 50, y: 50 };
  const current = s.color ? hex(s.color) : "";
  return `<div class="color-pane">
    <div class="wheel" id="wheel" role="slider" tabindex="0" aria-label="Color" aria-valuetext="${colorOn ? hex(s.color) : "None"}">
      <i class="wheel-thumb ${colorOn ? "" : "idle"}" style="left:${pos.x}%;top:${pos.y}%;${colorOn ? `background:${hex(s.color)}` : ""}"></i>
    </div>
    <div class="presets" role="group" aria-label="Colors">${COLOR_PRESETS.map((c) => `<button class="swatch" data-color="${c.c}"
      style="--sw:${c.c}" aria-label="${c.name}" aria-pressed="${!!(colorOn && current === c.c)}"></button>`).join("")}</div>
  </div>`;
}

function whitePane(s) {
  const known = Number.isFinite(s.color_temp);
  const tempOn = s.on !== false && s.color_mode !== "color" && s.color_temp;
  const k = clampK(s.color_temp || 3000);
  return `<div class="white-pane">
    <div class="pane-bar"><span class="pane-help">Warm</span><b id="ct-val">${tempOn ? tempWord(k) : known ? "" : "Not reported"}</b><span class="pane-help">Cool</span></div>
    <div class="temp-strip" id="ct" role="slider" tabindex="${known ? 0 : -1}" aria-label="White temperature" aria-disabled="${!known}"
      aria-valuemin="${KMIN}" aria-valuemax="${KMAX}" aria-valuenow="${k}" aria-valuetext="${known ? `${k} kelvin` : "Not reported"}">
      <i class="temp-thumb ${tempOn ? "" : "idle"}" style="--p:${((k - KMIN) / (KMAX - KMIN)) * 100}"></i></div>
    <div class="presets labeled" role="group" aria-label="Whites">${WHITE_PRESETS.map((w) => `<button class="swatch-chip" data-kelvin="${w.k}"
      aria-pressed="${!!(tempOn && Math.abs(s.color_temp - w.k) < 300)}"><i style="--sw:rgb(${kelvinToRgb(w.k).join(" ")})"></i>${w.name}</button>`).join("")}</div>
  </div>`;
}

export function lightPanel(d) {
  const s = d.state || {};
  const tabs = [
    has(d, "color") && { id: "color", label: "Color", html: colorPane(s) },
    has(d, "color_temp") && { id: "white", label: "White", html: whitePane(s) },
    ...effectTabs(d),
  ].filter(Boolean);
  // Open on what the light is doing now.
  const prefer = { effect: "scenes", music: "music", segments: "segments", color: "color", temp: "white" }[s.color_mode] || null;
  return {
    stage: has(d, "brightness") ? brightnessBar(d, s) : has(d, "power") ? powerHero(d) : "",
    tabs, prefer,
    note: d.meta?.hint ? `<div class="note">${esc(d.meta.hint)}</div>` : "",
  };
}

// ---------- behaviour ----------
let dragging = null;
let cancel = () => {};
export const lightBusy = () => !!dragging;
export function cancelLightDrag() { cancel(); }

// Pointer drag: move(x, y, start, final) while the finger moves and once on release;
// tap(x, y, start) for a touch that didn't move. onIdle(redraw) when the finger is up.
function drag(el, { move, tap }, onIdle) {
  let start = null;
  el.addEventListener("pointerdown", (e) => {
    if (e.button > 0 || dragging || el.getAttribute("aria-disabled") === "true") return;
    e.preventDefault();
    try { el.setPointerCapture(e.pointerId); } catch { /* not a real pointer (tests) */ }
    el.focus({ preventScroll: true });
    cancel = () => { start = null; dragging = null; };
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
    if (dragging === s) { dragging = null; onIdle(s.moved || !!tap); }
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  el.addEventListener("lostpointercapture", end);
}

export function attachLight(sheet, dev, onIdle) {
  // Handlers read the live device: updates can replace it while the panel stays the same.
  const d = { id: dev.id, get state() { return (store.devices.get(dev.id) || dev).state || {}; } };
  const floor = has(dev, "power") ? 0 : 1;

  const bri = sheet.querySelector("#bri");
  if (bri) {
    const fill = bri.querySelector(".pill-fill"), val = bri.querySelector("#bri-val");
    const shown = (v) => {
      fill.style.height = `${v}%`;
      val.textContent = v ? `${v}%` : "Off";
      bri.classList.toggle("on", v > 0);
      bri.classList.toggle("high", v >= 86);
      bri.classList.toggle("lit", v >= 16);
      bri.setAttribute("aria-valuenow", v);
      bri.setAttribute("aria-valuetext", v ? `${v}%` : "Off");
    };
    const send = (v) => (v === 0 ? command(d.id, "power", false, { on: false }) : command(d.id, "brightness", v, { on: true, brightness: v }));
    drag(bri, {
      move: (x, y, st, final) => {
        if (st.base == null) st.base = d.state.on === false ? 0 : d.state.brightness;
        const v = Math.max(floor, Math.min(100, Math.round(st.base + ((st.y - y) / st.rect.height) * 100)));
        shown(v);
        if (final) return send(v);
      },
    }, onIdle);
    bri.addEventListener("keydown", (e) => {
      if (bri.getAttribute("aria-disabled") === "true") return;
      const cur = d.state.on === false ? 0 : d.state.brightness;
      const step = { ArrowUp: 10, ArrowRight: 10, ArrowDown: -10, ArrowLeft: -10 }[e.key];
      if (!step && !["Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const v = Math.max(floor, Math.min(100, e.key === "Home" ? 0 : e.key === "End" ? 100 : cur + step));
      shown(v);
      send(v);
    });
  }

  const wheel = sheet.querySelector("#wheel");
  if (wheel) {
    const thumb = wheel.querySelector(".wheel-thumb");
    let last = d.state.color ? hex(d.state.color) : "#ffffff";
    const pick = (x, y, st, final) => {
      const r = st.rect, cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      let dx = x - cx, dy = y - cy;
      const dist = Math.hypot(dx, dy), max = r.width / 2;
      if (dist > max) { dx *= max / dist; dy *= max / dist; }
      const h = ((Math.atan2(dx, -dy) * 180) / Math.PI + 360) % 360;
      const raw = Math.min(1, Math.hypot(dx, dy) / max);
      last = hsToHex(h, raw > 0.93 ? 1 : raw);          // the outer rim snaps to the pure colour
      thumb.classList.remove("idle");
      thumb.style.left = `${50 + (dx / max) * 50}%`;
      thumb.style.top = `${50 + (dy / max) * 50}%`;
      thumb.style.background = last;
      const rgb = rgbOf(last);
      sheet.style.setProperty("--glow", glowFromRgb(rgb));
      if (final) return command(d.id, "color", last, { on: true, color: rgb, color_mode: "color" });
    };
    drag(wheel, { move: pick, tap: (x, y, st) => pick(x, y, st, true) }, onIdle);
    wheel.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 15, ArrowUp: 15, ArrowLeft: -15, ArrowDown: -15 }[e.key];
      if (!step) return;
      e.preventDefault();
      last = hsToHex((rgbToHs(rgbOf(last)).h + step + 360) % 360, 1);
      command(d.id, "color", last, { on: true, color: rgbOf(last), color_mode: "color" });
    });
  }

  const ct = sheet.querySelector("#ct");
  if (ct) {
    const thumb = ct.querySelector(".temp-thumb"), word = sheet.querySelector("#ct-val");
    const set = (k, final) => {
      thumb.classList.remove("idle");
      thumb.style.setProperty("--p", ((k - KMIN) / (KMAX - KMIN)) * 100);
      ct.setAttribute("aria-valuenow", k);
      ct.setAttribute("aria-valuetext", `${k} kelvin`);
      if (word) word.textContent = tempWord(k);
      sheet.style.setProperty("--glow", glowFromRgb(rgbOfKelvin(k)));
      if (final) return command(d.id, "color_temp", k, { on: true, color_temp: k, color_mode: "temp" });
    };
    drag(ct, {
      move: (x, y, st, final) => {
        if (st.base == null) st.base = d.state.color_temp || 3000;
        return set(Math.round(clampK(st.base + ((x - st.x) / st.rect.width) * (KMAX - KMIN))), final);
      },
    }, onIdle);
    ct.addEventListener("keydown", (e) => {
      if (ct.getAttribute("aria-disabled") === "true") return;
      const step = { ArrowRight: 300, ArrowUp: 300, ArrowLeft: -300, ArrowDown: -300 }[e.key];
      if (!step && !["Home", "End"].includes(e.key)) return;
      e.preventDefault();
      set(clampK(e.key === "Home" ? KMIN : e.key === "End" ? KMAX : d.state.color_temp + step), true);
    });
  }
}
