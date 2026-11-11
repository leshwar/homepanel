// The device panel: a sheet that opens from a tile with everything one device can do.
// panel.js gives every device the same shape (header with a switch, one large "stage"
// control, tabs for the rest); the stage and tabs come from the device's kind and caps:
// light.js, remote.js (TVs), speaker.js, vacuum.js, purifier.js, or a big power button.
//
// Opening a panel never sends a command. This file owns opening and closing, redrawing
// without disturbing a finger that is down, and the clicks.

import { api } from "./api.js";
import { store, command } from "./store.js";
import { $, esc, icon, glowVar, isMedia, toast } from "./util.js";
import { openSettings } from "./settings.js";
import { panelHead, panelBody, powerHero, setTab, tabKey } from "./panel.js";
import { isLight, lightPanel, attachLight, lightBusy, cancelLightDrag, rgbOf } from "./light.js";
import { remotePanel, attachRemote, remoteClick, remoteBusy, startRepeat, stopTilt, cancelRemoteInteraction, onRemoteChange } from "./remote.js";
import { controlGestureBusy, clearControlGestures } from "./device-controls.js";
import { setMarkup, invalidateMarkup } from "./render.js";
import { purifierPanel } from "./purifier.js";
import { vacuumPanel, picked } from "./vacuum.js";
import { effectsClick, attachEffects, effectsBusy, keepEffects } from "./effects.js";
import { simpleSpeaker, speakerPanel, attachSpeaker, speakerBusy, clearSpeakerInteraction } from "./speaker.js";

const sheetState = { shownId: null, missed: false, force: false };
const pressedPointers = new Set();
let pendingClick = null;
let currentId = null;
let returnFocus = null;

export const isSheetOpen = () => !$("#sheet").hidden;

function dropInteractions() {
  cancelLightDrag(); clearControlGestures(); cancelRemoteInteraction(); clearSpeakerInteraction();
  pressedPointers.clear();
  pendingClick = null;
}

let closing = null;
export function openDevice(id) {
  dropInteractions();
  sheetState.missed = false; sheetState.force = false;
  if (!isSheetOpen()) returnFocus = document.activeElement;
  clearTimeout(closing);
  $("#sheet").classList.remove("closing"); $("#scrim").classList.remove("closing");
  currentId = id;
  render(true);
  $("#scrim").hidden = false;
  $("#sheet").hidden = false;
  $("#sheet").focus?.();
}

export function closeSheet() {
  dropInteractions();
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

// A live update arrived. Redraw unless a finger is down or a gesture is running; then
// remember that we missed one and catch up as soon as the person lets go.
export function refreshSheet(id, force = false) {
  if (!currentId) return;
  if (id && id !== currentId) return;
  if (pendingClick || pressedPointers.size || lightBusy() || controlGestureBusy() || remoteBusy.active || effectsBusy() || speakerBusy()) {
    sheetState.missed = true; sheetState.force ||= force; return;
  }
  force ||= sheetState.force;
  sheetState.force = false;
  sheetState.missed = false;
  if (!store.devices.has(currentId)) return closeSheet();
  render(force);
}
onRemoteChange(() => refreshSheet(), () => { if (sheetState.missed) refreshSheet(); });

const has = (d, c) => d.caps.includes(c);

// Which panel a device gets. Media first: a TV with a colour cap is still a TV.
export function panelKind(d) {
  if (isMedia(d)) return simpleSpeaker(d) ? "speaker" : "remote";
  if (has(d, "clean")) return "vacuum";
  if (d.kind === "purifier") return "purifier";
  if (isLight(d)) return "light";
  return "switch";
}

// A plug, a switch or anything else that only turns on and off: one big button,
// with its energy use when it reports watts.
function switchPanel(d) {
  const s = d.state || {};
  const energyBlock = s.power_w != null ? `<div class="energy" id="energy">${energyHtml(d, s)}</div>` : "";
  if (!has(d, "power")) return { stage: `<p class="stage-hint">No controls are reported for this device.</p>${energyBlock}`, tabs: [] };
  return { stage: powerHero(d) + energyBlock, tabs: [] };
}

const PANELS = { light: lightPanel, remote: remotePanel, speaker: speakerPanel, vacuum: vacuumPanel, purifier: purifierPanel, switch: switchPanel };

function blockedNote(d, s) {
  if (s.needs_pairing) {
    return `<div class="note">${esc(s.error || "This device needs to be paired.")}
      ${d.kind === "tv" ? "<br>Turn the TV on, tap Pair, then accept the prompt on the TV screen." : ""}</div>
      <button class="btn primary" data-pair>${icon("link")}Pair now</button>`;
  }
  return `<div class="note warn">${esc(s.error || "This device isn't responding.")}
    Check its power and connection. For account-connected devices, check the device's app and account sign-in.</div>
    <button class="btn" data-refresh>${icon("search")}Try again</button>`;
}

function render(force = false) {
  const d = store.devices.get(currentId);
  if (!d) return;
  const s = d.state || {};
  const sheet = $("#sheet");
  const kind = panelKind(d);
  const blocked = !!s.needs_pairing || s.online === false;
  const body = blocked ? `<div class="panel solo"><div class="panel-stage">${blockedNote(d, s)}</div></div>` : panelBody(d, PANELS[kind](d));

  // Keep the scroll position and the focused control across redraws of the same device.
  const same = sheetState.shownId === d.id;
  if (!same) stopTilt();
  sheetState.shownId = d.id;
  const top = same ? sheet.scrollTop : 0;
  const focused = same && sheet.contains(document.activeElement) ? document.activeElement : null;
  const focusAttribute = focused && [...focused.attributes].find((a) => a.name.startsWith("data-") && a.name !== "data-repeat");
  const focusKey = focused?.id ? `#${CSS.escape(focused.id)}`
    : focusAttribute ? `[${focusAttribute.name}="${CSS.escape(focusAttribute.value)}"]` : null;
  sheet.dataset.kind = kind;
  sheet.dataset.deviceId = d.id;
  sheet.style.setProperty("--glow", glowVar(d));
  sheet.setAttribute("aria-label", `${d.name} controls`);
  keepEffects(sheet, same);
  const markup = `<div class="grab" aria-hidden="true"></div>${panelHead(d, { controls: !blocked })}${body}`;
  if (!same || force) invalidateMarkup(sheet);
  if (!setMarkup(sheet, markup)) return;
  sheet.scrollTop = top;
  // On a phone the tab row scrolls sideways: keep the chosen tab in view.
  const bar = sheet.querySelector(".panel-tabs"), chosen = bar?.querySelector('[aria-selected="true"]');
  if (chosen && (chosen.offsetLeft < bar.scrollLeft || chosen.offsetLeft + chosen.offsetWidth > bar.scrollLeft + bar.clientWidth)) {
    bar.scrollLeft = chosen.offsetLeft - 8;
  }

  if (!blocked) {
    const idle = (redraw = true) => refreshSheet(d.id, redraw);
    if (kind === "light") { attachLight(sheet, d, (redraw) => refreshSheet(undefined, redraw)); attachEffects(sheet, d, idle); }
    else if (kind === "remote") attachRemote(sheet, d);
    else if (kind === "speaker") attachSpeaker(sheet, d, idle);
    else if (kind === "vacuum") watchMap(sheet);
    if (sheet.querySelector("#energy")) loadEnergy(d.id);
  }
  if (focusKey) sheet.querySelector(focusKey)?.focus({ preventScroll: true });
}

// The vacuum's map is a picture from the device: say so plainly when it can't be loaded.
function watchMap(sheet) {
  const img = sheet.querySelector(".vac-map img");
  if (!img) return;
  const done = (available) => {
    img.parentNode.classList.remove("loading");
    img.parentNode.classList.toggle("empty", !available);
    img.parentNode.setAttribute("aria-busy", "false");
    if (!available) img.nextElementSibling.textContent = "Map unavailable. Refresh status or check the device's app.";
  };
  img.addEventListener("error", () => done(false));
  img.addEventListener("load", () => done(true));
  if (img.complete) done(img.naturalWidth > 0);
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
  const control = e.target.closest("button");
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
$("#sheet").addEventListener("keydown", (e) => {
  const tab = tabKey(e);
  if (!tab || !currentId) return;
  setTab(currentId, tab);
  render();
  $(`#sheet [data-tab="${CSS.escape(tab)}"]`)?.focus({ preventScroll: true });
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isSheetOpen()) closeSheet(); });
$("#sheet").addEventListener("keydown", (e) => {
  if (e.key !== "Tab") return;
  const items = [...$("#sheet").querySelectorAll('button:not([disabled]):not([tabindex="-1"]), input:not([disabled]), a[href], [tabindex="0"]')]
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
  if (t("[data-tab]")) { setTab(d.id, t("[data-tab]").dataset.tab); return render(); }
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
