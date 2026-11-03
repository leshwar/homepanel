// Bottom sheet with full controls for one device: brightness, color, or a TV remote.

import { api } from "./api.js";
import { store, command } from "./store.js";
import { $, esc, icon, glowVar, statusText, throttle, toast } from "./util.js";
import { openSettings } from "./settings.js";

let currentId = null;
let dragging = false;

const WHITES = [2200, 2700, 3500, 4500, 6000];
const COLORS = ["#ff4d3d", "#ff9a3c", "#ffd84d", "#5ee07a", "#3fd6d0", "#4f7bff", "#9b5cff", "#ff5cb8"];
const KELVIN_SWATCH = { 2200: "#ffb46b", 2700: "#ffc98c", 3500: "#ffe2bf", 4500: "#fff1e2", 6000: "#eef3ff" };

export const isSheetOpen = () => !$("#sheet").hidden;

export function openDevice(id) {
  currentId = id;
  render();
  $("#scrim").hidden = false;
  $("#sheet").hidden = false;
  $("#sheet").focus?.();
}

export function closeSheet() {
  currentId = null;
  $("#scrim").hidden = true;
  $("#sheet").hidden = true;
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

  if (d.kind === "tv") body += tvBody(d);
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
      <button class="power-big ${on ? "on" : ""}" data-power aria-label="Turn ${on ? "off" : "on"}" aria-pressed="${on}">${icon("power")}</button>
      <div class="grow"><h2>${esc(d.name)}</h2><p>${esc(statusText(d))}</p></div>
      <button class="icon-btn" data-close aria-label="Close">${icon("close")}</button>
    </div>
    <div style="--glow:${glowVar(d)}">${body}</div>
    <div class="meta-line"><span>${esc(d.room || "No room")}. ${esc(d.adapter_name)}${d.meta?.model ? `, ${esc(d.meta.model)}` : ""}</span>
      <button class="link" data-edit>Edit device</button></div>`;

  if (s.power_w != null) loadEnergy(d.id);
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

function tvBody(d) {
  const s = d.state || {};
  const on = !!s.on;
  if (!on) return `<div class="note">The TV is off. Tap the power button to turn it on.</div>`;
  const apps = d.meta?.apps || [];
  const inputs = d.meta?.inputs || [];
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
      `<button class="chip" data-input="${esc(x.id)}" aria-pressed="${s.input === x.id}">${esc(x.name)}</button>`).join("")}</div>` : ""}`;
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
  if (t("[data-key]")) return command(d.id, "key", t("[data-key]").dataset.key);
  if (t("[data-act]")) return command(d.id, t("[data-act]").dataset.act);
  if (t("[data-mute]")) { const m = !d.state?.muted; return command(d.id, "mute", m, { muted: m }); }
  if (t("[data-app]")) { const a = t("[data-app]").dataset.app; return command(d.id, "launch_app", a, { app: a }); }
  if (t("[data-input]")) { const i = t("[data-input]").dataset.input; return command(d.id, "set_input", i, { input: i, app: null }); }
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
