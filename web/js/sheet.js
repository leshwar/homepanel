// Bottom sheet with full controls for one device: brightness, color, or a TV / speaker remote.

import { api } from "./api.js";
import { store, command } from "./store.js";
import { $, esc, icon, glowVar, isMedia, kindIcon, statusText, throttle, toast } from "./util.js";
import { openSettings } from "./settings.js";

let currentId = null;
let dragging = false;

const WHITES = [2200, 2700, 3500, 4500, 6000];
const COLORS = ["#ff4d3d", "#ff9a3c", "#ffd84d", "#5ee07a", "#3fd6d0", "#4f7bff", "#9b5cff", "#ff5cb8"];
const KELVIN_SWATCH = { 2200: "#ffb46b", 2700: "#ffc98c", 3500: "#ffe2bf", 4500: "#fff1e2", 6000: "#eef3ff" };

export const isSheetOpen = () => !$("#sheet").hidden;

let closing = null;
export function openDevice(id) {
  clearTimeout(closing);
  $("#sheet").classList.remove("closing"); $("#scrim").classList.remove("closing");
  currentId = id;
  render();
  $("#scrim").hidden = false;
  $("#sheet").hidden = false;
  $("#sheet").focus?.();
}

export function closeSheet() {
  currentId = null;
  const sheet = $("#sheet"), scrim = $("#scrim");
  if (sheet.hidden) return;
  sheet.classList.add("closing"); scrim.classList.add("closing");   // slides away (shell.css), then hides
  clearTimeout(closing);
  closing = setTimeout(() => {
    sheet.hidden = true; scrim.hidden = true;
    sheet.classList.remove("closing"); scrim.classList.remove("closing");
  }, matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 190);
}

export function refreshSheet(id) {
  if (!currentId || dragging) return;
  if (id && id !== currentId) return;
  if (!store.devices.has(currentId)) return closeSheet();
  render();
}

const hex = ({ r, g, b }) => "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");

function render() {
  const d = store.devices.get(currentId);
  if (!d) return;
  const s = d.state || {};
  const on = !!s.on;
  const has = (c) => d.caps.includes(c);
  let body = "";

  if (s.needs_pairing) {
    body += `<div class="note">${esc(s.error || "This device needs to be paired.")}
      ${d.kind === "tv" ? "<br>Turn the TV on, tap Pair, then accept the prompt on the TV screen." : ""}</div>
      <button class="btn primary" data-pair>${icon("link")}Pair now</button>`;
  } else if (s.online === false) {
    body += `<div class="note warn">${esc(s.error || "This device isn't responding.")}
      Check that it has power and is on the same Wi-Fi as the panel.</div>
      <button class="btn" data-refresh>${icon("search")}Try again</button>`;
  }

  if (isMedia(d)) body += tvBody(d);
  else if (has("clean")) body += vacuumBody(d);
  else {
    if (has("brightness")) {
      body += `<div class="section-label"><span>Brightness</span><b id="bri-val">${on ? (s.brightness ?? 100) + "%" : "Off"}</b></div>
        <div class="slider" id="bri" role="slider" aria-label="Brightness" aria-valuemin="1" aria-valuemax="100"
             aria-valuenow="${s.brightness ?? 0}" tabindex="0">
          <div class="slider-fill" style="width:${on ? s.brightness ?? 100 : 0}%"></div>${icon("sun")}
        </div>`;
    }
    if (has("color_temp")) {
      body += `<div class="section-label"><span>White</span></div><div class="swatches">${WHITES.map((k) => {
        const sel = on && s.color_mode === "temp" && s.color_temp && Math.abs(s.color_temp - k) < 350;
        return `<button class="swatch" style="background:${KELVIN_SWATCH[k]}" data-kelvin="${k}" aria-pressed="${!!sel}" aria-label="${k} kelvin"></button>`;
      }).join("")}</div>`;
    }
    if (has("color")) {
      const cur = s.color ? hex(s.color) : "";
      body += `<div class="section-label"><span>Color</span></div><div class="swatches">${COLORS.map((c) =>
        `<button class="swatch" style="background:${c}" data-color="${c}" aria-pressed="${on && s.color_mode === "color" && cur === c}" aria-label="Color ${c}"></button>`).join("")}</div>`;
    }
    if (s.power_w != null) body += `<div class="section-label"><span>Energy</span></div><div id="energy">${energyHtml(d, s)}</div>`;
  }

  $("#sheet").innerHTML = `
    <div class="grab"></div>
    <div class="sheet-head" style="--glow:${glowVar(d)}">
      ${has("power") ? `<button class="power-big ${on ? "on" : ""}" data-power aria-label="Turn ${on ? "off" : "on"}" aria-pressed="${on}">${icon("power")}</button>`
        : `<div class="power-big ${on ? "on" : ""}" aria-hidden="true">${icon(kindIcon(d))}</div>`}
      <div class="grow"><h2>${esc(d.name)}</h2><p>${esc(statusText(d))}</p></div>
      <button class="icon-btn" data-close aria-label="Close">${icon("close")}</button>
    </div>
    <div style="--glow:${glowVar(d)}">${body}</div>
    <div class="meta-line"><span>${esc(d.room || "No room")}. ${esc(d.adapter_name)}${d.meta?.model ? `, ${esc(d.meta.model)}` : ""}</span>
      <button class="link" data-edit>Edit device</button></div>`;

  if (s.power_w != null) loadEnergy(d.id);
  const mapImg = $("#sheet .vac-map img");
  if (mapImg) {
    mapImg.addEventListener("error", () => mapImg.parentNode.classList.add("empty"));
    mapImg.addEventListener("load", () => mapImg.parentNode.classList.remove("empty"));
  }
  const bri = $("#bri");
  if (bri) attachSlider(bri, (v, final) => {
    $("#bri-val").textContent = `${v}%`;
    if (final) command(d.id, "brightness", v, { on: true, brightness: v });
    else sendLive(d.id, v);
  });
  const vol = $("#vol");
  if (vol) attachSlider(vol, (v, final) => {
    $("#vol-val").textContent = v;
    if (final) command(d.id, "volume", v, { volume: v });
  });
}

// ---------- energy ----------
let energy = { id: null, at: 0, data: null };

function energyHtml(d, s) {
  const e = energy.id === d.id ? energy.data : null;
  const stats = `<div class="energy-stats">
      <div><b>${s.power_w} W</b><span>Using now</span></div>
      ${e ? `<div><b>${e.today_kwh.toFixed(2)}</b><span>kWh today</span></div>
             <div><b>${e.week_kwh.toFixed(1)}</b><span>kWh this week</span></div>` : ""}
    </div>`;
  if (!e) return stats;
  const max = Math.max(...e.days.map((x) => x.kwh), 0.001);
  const bars = e.days.map((x, i) => {
    const day = new Date(x.date + "T12:00:00").toLocaleDateString([], { weekday: "short" });
    return `<div class="bar ${i === e.days.length - 1 ? "today" : ""}" title="${x.kwh} kWh">
      <i style="height:${Math.max(2, (x.kwh / max) * 100)}%"></i><span>${i === e.days.length - 1 ? "Today" : day}</span></div>`;
  }).join("");
  return stats + `<div class="bars" role="img" aria-label="Energy per day for the last 7 days">${bars}</div>`;
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
  } catch { /* history is optional */ }
}

const sendLive = throttle((id, v) => api.command(id, "brightness", v).catch(() => {}), 350);

// Rooms picked for "Clean selected rooms", per vacuum. Kept while the sheet re-renders.
const pickedRooms = new Map();
const picked = (id) => { if (!pickedRooms.has(id)) pickedRooms.set(id, new Set()); return pickedRooms.get(id); };

const optionChips = (list, current, attr) => `<div class="chips">${list.map((o) =>
  `<button class="chip" ${attr}="${esc(String(o.id))}" aria-pressed="${String(current) === String(o.id)}">${esc(o.name)}</button>`).join("")}</div>`;

// Robot vacuum: map, rooms, the main button that does the obvious next thing, settings and parts.
function vacuumBody(d) {
  const s = d.state || {};
  const a = s.activity;
  const m = d.meta || {};
  const rooms = m.rooms || [];
  const chosen = picked(d.id);
  for (const id of [...chosen]) if (!rooms.some((r) => String(r.id) === id)) chosen.delete(id);
  const main = a === "cleaning" ? { clean: "pause", label: "Pause", ic: "pause" }
    : a === "paused" ? { clean: "resume", label: "Keep cleaning", ic: "play" }
    : { clean: "start", label: "Start cleaning", ic: "play" };
  const optimistic = { start: "cleaning", resume: "cleaning", pause: "paused" }[main.clean];
  const last = s.last_clean;
  return `
    ${s.problem ? `<div class="note warn">${esc(s.problem)}</div>` : ""}
    ${hasCap(d, "map") ? `<div class="vac-map"><img src="${api.mapUrl(d.id, s.map_rev || 0)}" alt="Map of your home"><span>The map shows up after the first clean.</span></div>` : ""}
    ${hasCap(d, "rooms") && rooms.length ? `<div class="section-label"><span>Rooms</span>
        <b>${chosen.size ? `${chosen.size} picked` : "Tap rooms to pick"}</b></div>
      <div class="chips">${rooms.map((r) => `<button class="chip" data-room-pick="${esc(String(r.id))}"
        aria-pressed="${chosen.has(String(r.id))}">${esc(r.name)}</button>`).join("")}</div>
      ${chosen.size ? `<div class="btn-row vacuum-ctl"><button class="btn primary" data-clean-rooms>${icon("play")}Clean ${chosen.size === 1 ? "this room" : `these ${chosen.size} rooms`}</button></div>` : ""}` : ""}
    ${s.battery != null ? `<div class="section-label"><span>Battery</span><b>${s.battery}%</b></div>
      <div class="meter" role="meter" aria-label="Battery" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${s.battery}">
        <div class="meter-fill" style="width:${s.battery}%"></div></div>` : ""}
    <div class="btn-row vacuum-ctl">
      <button class="btn primary" data-clean="${main.clean}" data-activity="${optimistic}">${icon(main.ic)}${main.label}</button>
      ${hasCap(d, "dock") && a !== "docked" && a !== "returning"
        ? `<button class="btn" data-dock>${icon("home")}Back to dock</button>` : ""}
      ${a === "paused" ? `<button class="btn" data-clean="stop" data-activity="idle">Stop</button>` : ""}
    </div>
    ${hasCap(d, "suction") && m.suction_levels?.length ? `<div class="section-label"><span>Suction</span></div>
      ${optionChips(m.suction_levels, s.suction, "data-suction")}` : ""}
    ${hasCap(d, "clean_mode") && m.clean_modes?.length ? `<div class="section-label"><span>Mode</span></div>
      ${optionChips(m.clean_modes, s.clean_mode, "data-clean-mode")}` : ""}
    ${(hasCap(d, "station") && m.station_actions?.length) || hasCap(d, "locate") ? `<div class="section-label"><span>Station and more</span></div>
      <div class="btn-row vacuum-more">
        ${hasCap(d, "station") ? (m.station_actions || []).map((o) =>
          `<button class="btn" data-station="${esc(String(o.id))}">${esc(o.name)}</button>`).join("") : ""}
        ${hasCap(d, "locate") ? `<button class="btn" data-locate>${icon("vol")}Find my vacuum</button>` : ""}
      </div>` : ""}
    ${last && (last.area_m2 != null || last.minutes != null) ? `<div class="section-label"><span>Last clean</span>
      <b>${[last.area_m2 != null ? `${last.area_m2} m²` : "", last.minutes != null ? `${last.minutes} min` : ""].filter(Boolean).join(", ")}</b></div>` : ""}
    ${s.parts?.length ? `<details class="vac-parts"><summary class="section-label"><span>Parts</span>
        <b>${s.parts[0].percent <= 10 ? `${esc(s.parts[0].name)} needs replacing` : "All good"}</b></summary>
      ${s.parts.map((p) => `<div class="part"><span>${esc(p.name)}</span>
        <div class="meter small"><div class="meter-fill ${p.percent <= 10 ? "low" : ""}" style="width:${p.percent}%"></div></div>
        <b>${p.percent}%</b></div>`).join("")}</details>` : ""}`;
}
const hasCap = (d, c) => d.caps.includes(c);

function tvBody(d) {
  const s = d.state || {};
  const on = !!s.on;
  if (!on) return `<div class="note">${d.kind === "tv" ? "The TV" : "The speaker"} is off. Tap the power button to turn it on.</div>`;
  const apps = d.meta?.apps || [];
  const inputs = d.meta?.inputs || [];
  const modes = d.meta?.sound_modes || [];
  const has = (c) => d.caps.includes(c);
  const nav = has("remote");
  const media = has("media") || nav;
  return `
    ${nav || has("volume") ? `<div class="remote">
      ${has("volume") ? `<div class="rocker">
        <button data-act="volume_up" aria-label="Volume up">${icon("plus")}</button><span>VOL</span>
        <button data-act="volume_down" aria-label="Volume down">${icon("minus")}</button>
      </div>` : "<div></div>"}
      ${nav ? `<div class="dpad" role="group" aria-label="Navigation">
        <button class="up" data-key="UP" aria-label="Up">${icon("up")}</button>
        <button class="left" data-key="LEFT" aria-label="Left">${icon("left")}</button>
        <button class="ok" data-key="OK">OK</button>
        <button class="right" data-key="RIGHT" aria-label="Right">${icon("right")}</button>
        <button class="down" data-key="DOWN" aria-label="Down">${icon("down")}</button>
      </div>` : "<div></div>"}
      ${has("channel") ? `<div class="rocker">
        <button data-act="channel_up" aria-label="Channel up">${icon("up")}</button><span>CH</span>
        <button data-act="channel_down" aria-label="Channel down">${icon("down")}</button>
      </div>` : "<div></div>"}
    </div>` : ""}
    <div class="remote-row">
      ${nav ? `<button class="round" data-key="BACK" aria-label="Back">${icon("back")}</button>
      <button class="round" data-key="HOME" aria-label="Home">${icon("home")}</button>` : ""}
      ${has("mute") ? `<button class="round ${s.muted ? "active" : ""}" data-mute aria-label="Mute" aria-pressed="${!!s.muted}">${icon(s.muted ? "mute" : "vol")}</button>` : ""}
      ${media ? `<button class="round" data-key="PLAY" aria-label="Play">${icon("play")}</button>
      <button class="round" data-key="PAUSE" aria-label="Pause">${icon("pause")}</button>` : ""}
    </div>
    ${has("volume_level") && s.volume != null ? `
      <div class="section-label"><span>Volume</span><b id="vol-val">${s.volume}</b></div>
      <div class="slider" id="vol" role="slider" aria-label="Volume" aria-valuenow="${s.volume}" tabindex="0">
        <div class="slider-fill" style="width:${s.volume}%"></div>${icon("vol")}</div>` : ""}
    ${apps.length ? `<div class="section-label"><span>Apps</span></div><div class="chips">${apps.slice(0, 12).map((a) =>
      `<button class="chip" data-app="${esc(a.id)}" aria-pressed="${s.app === a.id}">${esc(a.name)}</button>`).join("")}</div>` : ""}
    ${inputs.length ? `<div class="section-label"><span>Inputs</span></div><div class="chips">${inputs.map((x) =>
      `<button class="chip" data-input="${esc(x.id)}" aria-pressed="${s.input === x.id}">${esc(x.name)}</button>`).join("")}</div>` : ""}
    ${has("sound_mode") && modes.length ? `<div class="section-label"><span>Sound mode</span></div><div class="chips">${modes.map((m) =>
      `<button class="chip" data-sound-mode="${esc(m.id)}" aria-pressed="${s.sound_mode === m.id}">${esc(m.name)}</button>`).join("")}</div>` : ""}`;
}

// A big, forgiving touch slider. onChange(value, isFinal).
function attachSlider(el, onChange) {
  const fill = el.querySelector(".slider-fill");
  const min = Number(el.getAttribute("aria-valuemin") || 0);
  const at = (x) => {
    const r = el.getBoundingClientRect();
    return Math.max(min, Math.min(100, Math.round(((x - r.left) / r.width) * 100)));
  };
  let v = Number(el.getAttribute("aria-valuenow") || 0);
  const set = (nv, final) => { v = nv; fill.style.width = `${v}%`; el.setAttribute("aria-valuenow", v); onChange(v, final); };
  el.addEventListener("pointerdown", (e) => {
    dragging = true;
    el.setPointerCapture(e.pointerId);
    set(at(e.clientX), false);
  });
  el.addEventListener("pointermove", (e) => { if (dragging && el.hasPointerCapture(e.pointerId)) set(at(e.clientX), false); });
  const end = (e) => {
    if (!dragging) return;
    dragging = false;
    set(at(e.clientX), true);
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", () => { dragging = false; });
  el.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowUp") { e.preventDefault(); set(Math.min(100, v + 5), true); }
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") { e.preventDefault(); set(Math.max(min, v - 5), true); }
  });
}

// ---------- events ----------
$("#scrim").addEventListener("click", closeSheet);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isSheetOpen()) closeSheet(); });

$("#sheet").addEventListener("click", async (e) => {
  const d = store.devices.get(currentId);
  if (!d) return;
  const t = (sel) => e.target.closest(sel);
  if (t("[data-close]")) return closeSheet();
  if (t("[data-edit]")) { const id = d.id; closeSheet(); return openSettings("device", id); }
  if (t("[data-power]")) { const on = !d.state?.on; return command(d.id, "power", on, { on }); }
  if (t("[data-kelvin]")) { const k = +t("[data-kelvin]").dataset.kelvin; return command(d.id, "color_temp", k, { on: true, color_temp: k, color_mode: "temp" }); }
  if (t("[data-color]")) {
    const c = t("[data-color]").dataset.color;
    const rgb = { r: parseInt(c.slice(1, 3), 16), g: parseInt(c.slice(3, 5), 16), b: parseInt(c.slice(5, 7), 16) };
    return command(d.id, "color", c, { on: true, color: rgb, color_mode: "color" });
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
  if (t("[data-key]")) return command(d.id, "key", t("[data-key]").dataset.key);
  if (t("[data-act]")) return command(d.id, t("[data-act]").dataset.act);
  if (t("[data-mute]")) { const m = !d.state?.muted; return command(d.id, "mute", m, { muted: m }); }
  if (t("[data-app]")) { const a = t("[data-app]").dataset.app; return command(d.id, "launch_app", a, { app: a }); }
  if (t("[data-input]")) { const i = t("[data-input]").dataset.input; return command(d.id, "set_input", i, { input: i, app: null }); }
  if (t("[data-sound-mode]")) { const m = t("[data-sound-mode]").dataset.soundMode; return command(d.id, "set_sound_mode", m, { sound_mode: m }); }
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
