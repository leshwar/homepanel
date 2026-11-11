// TV (and richer speaker) remote for the device panel: a pad in the middle that switches
// between a D-pad, a touchpad for TVs with an on-screen pointer, and a number pad, with
// volume and channel rockers either side and round keys below. Apps, inputs, sound modes
// and the rarer keys are tabs beside it.
//
// Everything is drawn from the device's capabilities, so it works for any brand.

import { api } from "./api.js";
import { esc, icon, storage, toast } from "./util.js";
import { powerHero, chipChoices } from "./panel.js";

// True while a finger is on the touchpad: the sheet doesn't re-render under it.
export const remoteBusy = { active: false };

const has = (d, c) => d.caps.includes(c);

// ---------- centre modes ----------
const MODES = [
  { id: "dpad", label: "Buttons", ic: "dpad", ok: (d) => has(d, "remote") },
  { id: "touchpad", label: "Touchpad", ic: "touchpad", ok: (d) => has(d, "pointer") },
  { id: "numbers", label: "Numbers", text: "123", ok: (d) => has(d, "remote") },
];
const modesFor = (d) => MODES.filter((m) => m.ok(d));

export function modeOf(d) {
  const modes = modesFor(d);
  const saved = storage.get(`remote-mode:${d.id}`, "dpad");
  return (modes.find((m) => m.id === saved) || modes[0])?.id || null;
}
export function setMode(d, mode) {
  storage.set(`remote-mode:${d.id}`, mode);
  if (mode !== "touchpad") stopTilt();
}

// ---------- markup ----------
// The TV (or richer speaker) panel. Stage: volume on the left, the pad in the middle,
// channels on the right, then Back / Home / Play / Mute. Tabs: Apps, Inputs, Sound, Keys.
export function remotePanel(d) {
  const s = d.state || {};
  if (has(d, "power") && s.on !== true) {
    return { stage: powerHero(d, s.on === false ? "Turn it on to use the remote." : "Waiting for the device to report its power."), tabs: [] };
  }
  const mode = modeOf(d), modes = modesFor(d);
  const pad = mode ? `<div class="remote-pad">${padFor(d, mode)}</div>` : "";
  const stage = `<div class="remote" data-layout="${mode || "none"}">
      <div class="remote-row">${volume(d, s)}${pad}${channel(d)}</div>
      ${keyRow(d, s)}
      ${modes.length > 1 ? `<div class="seg remote-modes" role="group" aria-label="Remote layout">${modes.map((m) =>
        `<button data-mode="${m.id}" aria-pressed="${m.id === mode}">${m.ic ? icon(m.ic) : `<b>${m.text}</b>`}<span>${m.label}</span></button>`).join("")}</div>` : ""}
    </div>`;
  const apps = has(d, "apps") ? [...(d.meta?.apps || [])].sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name)) : [];
  const inputs = has(d, "inputs") ? d.meta?.inputs || [] : [];
  const sound = has(d, "sound_mode") ? d.meta?.sound_modes || [] : [];
  const tabs = [
    apps.length && { id: "apps", label: "Apps", html: `<div class="app-grid">${apps.map((a) =>
      `<button class="app-btn" data-app="${esc(a.id)}" aria-pressed="${s.app === a.id}"><span>${esc(a.name)}</span></button>`).join("")}</div>` },
    inputs.length && { id: "inputs", label: "Inputs", html: chipChoices(inputs, s.input, "data-input", { glyph: "input", label: "Input" }) },
    sound.length && { id: "sound", label: "Sound", html: chipChoices(sound, s.sound_mode, "data-sound-mode", { label: "Sound mode" }) },
    has(d, "remote") && { id: "keys", label: "Keys", html: `<div class="key-grid">${EXTRA_KEYS.map(([key, label, glyph]) =>
      `<button class="btn" data-key="${key}">${icon(glyph)}<span>${label}</span></button>`).join("")}</div>` },
  ].filter(Boolean);
  const prefer = s.app && apps.some((a) => a.id === s.app) ? "apps" : s.input && inputs.some((x) => x.id === s.input) ? "inputs" : null;
  return { stage, tabs, prefer };
}

const EXTRA_KEYS = [["MENU", "Menu", "menu"], ["SOURCE", "Input menu", "input"], ["INFO", "Info", "info"],
  ["CHANNEL_LIST", "Channel list", "list"], ["REWIND", "Rewind", "rew"], ["FORWARD", "Forward", "ff"], ["EXIT", "Exit", "exit"]];

function padFor(d, mode) {
  if (mode === "touchpad") {
    return `<div class="touchpad" id="touchpad" role="application" aria-label="Touchpad: drag to move the pointer, tap to click, two fingers to scroll">
        <span class="touchpad-hint">${icon("touchpad")}Drag to move · tap to click</span>
        <i class="touch-spot" aria-hidden="true"></i>
        ${canTilt() ? `<button class="tilt-btn" data-tilt aria-pressed="${tilt?.id === d.id}">${icon("tilt")}<span>${tilt?.id === d.id ? "Aiming" : "Aim"}</span></button>` : ""}
      </div>`;
  }
  if (mode === "numbers") {
    const n = (k) => `<button class="num" data-key="${k}">${k}</button>`;
    return `<div class="numpad" role="group" aria-label="Number pad">
        ${["1", "2", "3", "4", "5", "6", "7", "8", "9"].map(n).join("")}
        <button class="num small" data-key="INFO">Info</button>${n("0")}<button class="num small" data-key="OK">OK</button>
      </div>`;
  }
  return `<div class="dpad" role="group" aria-label="Navigation">
      <button class="up" data-key="UP" data-repeat aria-label="Up">${icon("up")}</button>
      <button class="left" data-key="LEFT" data-repeat aria-label="Left">${icon("left")}</button>
      <button class="ok" data-key="OK">OK</button>
      <button class="right" data-key="RIGHT" data-repeat aria-label="Right">${icon("right")}</button>
      <button class="down" data-key="DOWN" data-repeat aria-label="Down">${icon("down")}</button>
    </div>`;
}

const volume = (d, s) => (has(d, "volume") ? `<div class="rocker" role="group" aria-label="Volume">
    <button data-act="volume_up" data-repeat aria-label="Volume up">${icon("plus")}</button>
    <span>${Number.isFinite(s.volume) ? `<b>${s.volume}</b>` : ""}Vol</span>
    <button data-act="volume_down" data-repeat aria-label="Volume down">${icon("minus")}</button></div>` : "");

const channel = (d) => (has(d, "channel") ? `<div class="rocker" role="group" aria-label="Channel">
    <button data-act="channel_up" data-repeat aria-label="Channel up">${icon("up")}</button>
    <span>Ch</span>
    <button data-act="channel_down" data-repeat aria-label="Channel down">${icon("down")}</button></div>` : "");

// Round keys under the pad. Mute lives here, next to the volume it silences.
function keyRow(d, s) {
  const nav = has(d, "remote"), media = nav || has(d, "media");
  const key = (attrs, glyph, label, pressed = null) => `<button class="rkey" ${attrs} aria-label="${label}"
    ${pressed == null ? "" : `aria-pressed="${pressed}"`}>${icon(glyph)}<span>${label}</span></button>`;
  const keys = [
    nav && key('data-key="BACK"', "back", "Back"),
    nav && key('data-key="HOME"', "home", "Home"),
    media && key("data-playpause", "playpause", "Play / pause"),
    has(d, "mute") && typeof s.muted === "boolean" && key("data-mute", s.muted ? "mute" : "vol", s.muted ? "Unmute" : "Mute", s.muted),
  ].filter(Boolean);
  return keys.length ? `<div class="remote-keys">${keys.join("")}</div>` : "";
}

// Well-known streaming apps first (by name), then the rest A–Z.
const POPULAR = ["youtube", "netflix", "prime video", "disney", "apple tv", "max", "hulu", "spotify", "plex", "twitch"];
const rank = (name) => {
  const n = name.toLowerCase();
  const i = POPULAR.findIndex((p) => n.includes(p));
  return i < 0 ? POPULAR.length : i;
};

// ---------- behaviour ----------
const lastPlay = new Map();   // per TV: we can't read play state, so Play/Pause alternates (pause first)

// Wire up the parts that need more than a click. Called after every render.
export function attachRemote(root, d) {
  const pad = root.querySelector("#touchpad");
  if (pad) attachTouchpad(pad, d);
}

// Clicks inside the remote. Returns true when handled.
export function remoteClick(e, d, send) {
  const t = (sel) => e.target.closest(sel);
  if (t("[data-repeat]") && repeat.fired) { repeat.fired = false; return true; }   // the hold already sent it
  if (t("[data-mode]")) { setMode(d, t("[data-mode]").dataset.mode); return "render"; }
  if (t("[data-tilt]")) { toggleTilt(d); return true; }
  if (t("[data-playpause]")) {
    const key = lastPlay.get(d.id) === "PAUSE" ? "PLAY" : "PAUSE";
    lastPlay.set(d.id, key);
    send("key", key);
    return true;
  }
  if (t("[data-key]")) { tick(); send("key", t("[data-key]").dataset.key); return true; }
  if (t("[data-act]")) { tick(); send(t("[data-act]").dataset.act); return true; }
  return false;
}

const tick = () => navigator.vibrate?.(8);

// Press and hold arrows, volume and channel to repeat.
const repeat = { timer: 0, fired: false, pointer: null, x: 0, y: 0 };
export function startRepeat(e, send) {
  const b = e.target.closest("[data-repeat]");
  if (!b || b.disabled || e.button > 0) return;
  b.setPointerCapture(e.pointerId);
  Object.assign(repeat, { pointer: e.pointerId, x: e.clientX, y: e.clientY });
  remoteBusy.active = true;
  repeat.fired = false;
  clearTimeout(repeat.timer);
  const fire = () => {
    repeat.fired = true;
    tick();
    if (b.dataset.key) send("key", b.dataset.key); else send(b.dataset.act);
    repeat.timer = setTimeout(fire, 160);
  };
  repeat.timer = setTimeout(fire, 450);
}
export const stopRepeat = () => {
  clearTimeout(repeat.timer);
  if (repeat.pointer !== null) { repeat.pointer = null; remoteBusy.active = false; setTimeout(idle, 0); }
};
addEventListener("pointerup", stopRepeat);
addEventListener("pointercancel", stopRepeat);
addEventListener("pointermove", e => {
  if (e.pointerId === repeat.pointer && Math.hypot(e.clientX - repeat.x, e.clientY - repeat.y) > 8) {
    repeat.fired = true;
    stopRepeat();
  }
});

// ---------- pointer: batched moves ----------
// One request in flight at a time; moves that arrive meanwhile are added up and sent
// together, at most every SEND_MS. That keeps the TV's pointer smooth without
// flooding the panel or the TV.
const SEND_MS = 30;

class PointerSender {
  constructor(id) { Object.assign(this, { id, dx: 0, dy: 0, wheel: 0, clicks: 0, busy: false, timer: 0, last: 0, warned: false }); }
  move(dx, dy) { this.dx += dx; this.dy += dy; this.kick(); }
  scroll(dy) { this.wheel += dy; this.kick(); }
  click() { this.clicks += 1; this.kick(); }
  pending() { return Math.trunc(this.dx) || Math.trunc(this.dy) || Math.trunc(this.wheel) || this.clicks; }
  kick() {
    if (this.busy || this.timer || !this.pending()) return;
    const wait = Math.max(0, SEND_MS - (performance.now() - this.last));
    this.timer = setTimeout(() => { this.timer = 0; this.flush(); }, wait);
  }
  next() {
    const dx = Math.trunc(this.dx), dy = Math.trunc(this.dy);
    if (dx || dy) { this.dx -= dx; this.dy -= dy; return { dx, dy }; }     // move before a click
    if (this.clicks) { this.clicks -= 1; return { click: true }; }
    const w = Math.trunc(this.wheel);
    if (w) { this.wheel -= w; return { scroll: w }; }
    return null;
  }
  async flush() {
    const value = this.next();
    if (!value) return;
    this.busy = true;
    this.last = performance.now();
    try {
      await api.pointer(this.id, value);
    } catch (err) {
      Object.assign(this, { dx: 0, dy: 0, wheel: 0, clicks: 0 });
      if (!this.warned) { this.warned = true; toast(err.message, true); setTimeout(() => (this.warned = false), 4000); }
    } finally {
      this.busy = false;
    }
    this.kick();
  }
}
const senders = new Map();
export const pointerFor = (id) => { if (!senders.has(id)) senders.set(id, new PointerSender(id)); return senders.get(id); };
let cancelPad = () => {};
export function cancelRemoteInteraction() {
  stopRepeat(); stopTilt(); cancelPad();
  repeat.fired = false;
  for (const sender of senders.values()) {
    clearTimeout(sender.timer);
    Object.assign(sender, { timer: 0, dx: 0, dy: 0, wheel: 0, clicks: 0 });
  }
  addEventListener("blur", cancelRemoteInteraction);
}

// Faster finger, further pointer (like a laptop touchpad).
const accel = (dist) => 1.6 + Math.min(2.4, dist / 10);

function attachTouchpad(pad, d) {
  const sender = pointerFor(d.id);
  const spot = pad.querySelector(".touch-spot");
  const pts = new Map();
  cancelPad = () => { pts.clear(); remoteBusy.active = false; pad.classList.remove("touching"); };
  let moved = 0, downAt = 0, multi = false;
  const show = (e) => {
    const r = pad.getBoundingClientRect();
    spot.style.transform = `translate(${e.clientX - r.left}px, ${e.clientY - r.top}px)`;
  };
  pad.addEventListener("pointerdown", (e) => {
    if (e.target.closest("[data-tilt]")) return;
    e.preventDefault();
    try { pad.setPointerCapture(e.pointerId); } catch { /* not a real pointer (tests) */ }
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 1) { moved = 0; downAt = performance.now(); multi = false; } else multi = true;
    remoteBusy.active = true;
    pad.classList.add("touching");
    show(e);
  });
  pad.addEventListener("pointermove", (e) => {
    const p = pts.get(e.pointerId);
    if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    p.x = e.clientX; p.y = e.clientY;
    moved += Math.abs(dx) + Math.abs(dy);
    if (pts.size >= 2) sender.scroll(-dy * 1.5 / pts.size);      // natural scrolling: fingers up, page down
    else if (!multi) { const f = accel(Math.hypot(dx, dy)); sender.move(dx * f, dy * f); }
    show(e);
  });
  const end = (e) => {
    if (!pts.delete(e.pointerId)) return;
    if (pts.size) return;
    remoteBusy.active = false;
    pad.classList.remove("touching");
    setTimeout(() => idle(), 0);             // catch up on anything that changed meanwhile
    if (e.type === "pointerup" && !multi && moved < 10 && performance.now() - downAt < 350) {
      sender.click();
      tick();
      pad.classList.remove("clicked"); void pad.offsetWidth; pad.classList.add("clicked");
    }
  };
  pad.addEventListener("pointerup", end);
  pad.addEventListener("pointercancel", end);
}

// ---------- pointer: aim by tilting the phone ----------
let tilt = null;   // { id, handler, last, alive }
const TILT_PX_PER_DEGREE = 28;

function canTilt() {
  return "DeviceOrientationEvent" in window && matchMedia("(pointer: coarse)").matches;
}

async function toggleTilt(d) {
  if (tilt) { stopTilt(); return rerender(); }
  const ask = window.DeviceOrientationEvent?.requestPermission;      // iPhone and iPad ask first
  if (typeof ask === "function") {
    let answer = "denied";
    try { answer = await ask.call(DeviceOrientationEvent); } catch { /* treated as denied */ }
    if (answer !== "granted") return toast("Allow motion access to aim by tilting your phone.", true);
  }
  const sender = pointerFor(d.id);
  const t = { id: d.id, last: null, alive: false };
  t.handler = (e) => {
    if (e.alpha == null || e.beta == null) return;
    t.alive = true;
    if (t.last) {
      let da = e.alpha - t.last.a;                     // turn left/right (wraps at 360)
      if (da > 180) da -= 360;
      if (da < -180) da += 360;
      const db = e.beta - t.last.b;                    // tip up/down
      if (Math.abs(da) < 20 && Math.abs(db) < 20) sender.move(-da * TILT_PX_PER_DEGREE, -db * TILT_PX_PER_DEGREE);
    }
    t.last = { a: e.alpha, b: e.beta };
  };
  addEventListener("deviceorientation", t.handler);
  tilt = t;
  rerender();
  setTimeout(() => {
    if (tilt === t && !t.alive) { stopTilt(); rerender(); toast("This screen can't sense tilting. Use the touchpad instead.", true); }
  }, 1500);
}

export function stopTilt() {
  if (!tilt) return;
  removeEventListener("deviceorientation", tilt.handler);
  tilt = null;
}

let rerender = () => {};
let idle = () => {};
export const onRemoteChange = (fn, whenIdle) => { rerender = fn; idle = whenIdle; };
