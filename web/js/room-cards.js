// Content-sized room cards; the free-layout tiles and full device panels stay separate.
import { store, command } from "./store.js";
import { esc, icon, statusText, needsAttention, wornPart, toast } from "./util.js";
import { vacuumStatus } from "./vacuum-status.js";
import { bindRelativeRange } from "./device-controls.js";
import { setMarkup, syncAttributes } from "./render.js";

const has = (d, cap) => d.caps.includes(cap);
const level = value => Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : null;
const unavailable = d => d.state?.online !== true || d.state?.needs_pairing;
const cancels = new Map();
const bound = new WeakSet();
export const cardHeld = el => el.dataset.rangeHeld === "true";
export function cancelCardGestures() {
  for (const [range, cancel] of cancels) { cancel(); if (!range.isConnected) cancels.delete(range); }
}

export function cardStatus(d) {
  const s = d.state || {};
  if (s.needs_pairing) return "Needs pairing";
  if (s.online !== true) return s.online === false ? "Offline" : "Connecting...";
  if (has(d, "clean")) {
    const status = vacuumStatus(s);
    return needsAttention(d) && status.phase !== "attention" ? "Maintenance due" : status.label;
  }
  if (has(d, "power") && typeof s.on !== "boolean") return "Power not reported";
  if (d.kind === "light" && s.on && ["color", "temp", "segments"].includes(s.color_mode)) {
    return `${{color:"Color",temp:"White",segments:"Segments"}[s.color_mode]}${Number.isFinite(s.brightness) ? ` · ${s.brightness}%` : ""}`;
  }
  return statusText(d);
}

function details(d) {
  const s = d.state || {};
  if (unavailable(d)) return s.error || (s.needs_pairing ? "Open controls to pair." : "Open controls to check the connection.");
  if (has(d, "clean")) {
    const status = vacuumStatus(s);
    const problem = s.problem || (needsAttention(d) ? `${wornPart(s)?.name || "Device"} needs attention.` : "");
    return [problem, Number.isFinite(s.battery) ? `Battery ${s.battery}%` : "", status.metrics].filter(Boolean).join(" · ");
  }
  if (s.problem) return s.problem;
  if (needsAttention(d)) return `${wornPart(s)?.name || "Device"} needs attention.`;
  if (d.kind === "purifier") return [has(d,"air_quality") && s.pm25 != null ? `PM2.5 ${s.pm25}` : "",
    has(d,"filter_life") && s.filter_life != null ? `Filter ${s.filter_life}%` : ""].filter(Boolean).join(" · ");
  return "";
}

function controls(d, busy) {
  const s = d.state || {}, disabled = busy || unavailable(d);
  if (has(d, "brightness")) {
    const value = level(s.brightness);
    return `<label class="card-range"><span>Brightness <output>${value == null ? "Not reported" : `${value}%`}</output></span>
      <input type="range" min="1" max="100" step="1" value="${value ?? 1}" data-card-range="brightness"
        aria-label="${esc(d.name)} brightness" aria-valuetext="${value == null ? "Not reported" : `${value}%`}" ${disabled || value == null ? "disabled" : ""}></label>`;
  }
  if (d.kind === "speaker") {
    const value = level(s.volume), off = has(d, "power") && s.on !== true;
    const volume = has(d, "volume_level") ? `<label class="card-range volume"><span>Volume <output>${value == null ? "Not reported" : `${value}%`}</output></span>
      <input type="range" min="0" max="100" step="1" value="${value ?? 0}" data-card-range="volume"
        aria-label="${esc(d.name)} volume" aria-valuetext="${value == null ? "Not reported" : `${value}%`}" ${disabled || off || value == null ? "disabled" : ""}></label>`
      : has(d, "volume") ? `<div class="card-stepper"><button data-act="volume_down" aria-label="${esc(d.name)} volume down" ${disabled || off ? "disabled" : ""}>${icon("minus")}</button>
        <output>${value == null ? "Volume" : value}</output><button data-act="volume_up" aria-label="${esc(d.name)} volume up" ${disabled || off ? "disabled" : ""}>${icon("plus")}</button></div>` : "";
    return `${volume}${has(d, "mute") && typeof s.muted === "boolean" ? `<button class="card-mute" data-act="mute" data-value="${!s.muted}"
      aria-pressed="${s.muted}" aria-label="${s.muted ? "Unmute" : "Mute"} ${esc(d.name)}" ${disabled || off ? "disabled" : ""}>${icon(s.muted ? "mute" : "vol")}</button>` : ""}`;
  }
  if (has(d, "clean") && !unavailable(d)) {
    const status = vacuumStatus(s);
    return status.active ? `<div class="card-progress" role="progressbar" aria-label="Cleaning progress"
      aria-valuetext="${esc(status.label)} Completion not reported."><span>${esc(status.label)} · Completion not reported</span></div>` : "";
  }
  return "";
}

export function compactBody(d, quick, picture, busy) {
  const s = d.state || {}, status = busy ? "Updating..." : cardStatus(d);
  const safeQuick = quick && !(has(d, "clean") && (s.problem || s.cleaning?.status === "attention") && quick.value === "start");
  return `<div class="card-header">${picture}
    <button class="tile-open" data-more aria-label="${esc(d.name)}, ${esc(status)}. Open controls">
      <span class="tile-name">${esc(d.name)}</span><span class="tile-status">${esc(status)}</span></button>
    ${safeQuick ? `<button class="tile-quick" data-quick-action="${quick.action}" data-value="${quick.value}"
      aria-label="${esc(quick.label)}: ${esc(d.name)}" title="${esc(quick.label)}" ${quick.disabled ? "disabled" : ""}>${icon(quick.glyph)}</button>` : ""}
    </div><p class="card-detail" ${details(d) ? "" : "hidden"}>${esc(details(d))}</p>
    <div class="card-controls">${controls(d, busy)}</div>`;
}

export function syncCompact(old, next) {
  syncAttributes(old, next);
  for (const selector of [".tile-open", ".tile-name", ".tile-status", ".card-detail"]) {
    const a = old.querySelector(selector), b = next.querySelector(selector);
    syncAttributes(a, b);
    if (selector !== ".tile-open" && a.textContent !== b.textContent) a.textContent = b.textContent;
  }
  for (const selector of [".tile-icon", ".tile-quick"]) {
    const a = old.querySelector(selector), b = next.querySelector(selector);
    if (a && b) {
      syncAttributes(a, b);
      if (a.innerHTML !== b.innerHTML) a.innerHTML = b.innerHTML;
    } else if (a) {
      const focused = a === document.activeElement;
      a.remove();
      if (focused) old.querySelector("[data-more]").focus({ preventScroll: true });
    } else if (b) old.querySelector(".card-header").append(b);
  }
  const a = old.querySelector(".card-controls"), b = next.querySelector(".card-controls");
  const range = a.querySelector("[data-card-range]"), nextRange = b.querySelector("[data-card-range]");
  if (range && nextRange && range.dataset.cardRange === nextRange.dataset.cardRange) {
    syncAttributes(range, nextRange);
    range.value = nextRange.value;
    a.querySelector("output").textContent = b.querySelector("output").textContent;
    const mute = a.querySelector("[data-act]"), nextMute = b.querySelector("[data-act]");
    if (mute && nextMute) { syncAttributes(mute, nextMute); if (mute.innerHTML !== nextMute.innerHTML) mute.innerHTML = nextMute.innerHTML; }
    else if (mute) mute.remove();
    else if (nextMute) a.append(nextMute);
  } else if (a.innerHTML !== b.innerHTML) {
    const focus = a.contains(document.activeElement);
    setMarkup(a, b.innerHTML);
    if (focus) old.querySelector("[data-more]").focus({ preventScroll: true });
  }
}

export function attachCardRanges(root, update) {
  for (const [range] of cancels) if (!range.isConnected) cancels.delete(range);
  for (const range of root.querySelectorAll("[data-card-range]")) {
    if (bound.has(range)) continue;
    bound.add(range);
    const tile = range.closest(".tile"), id = tile.dataset.id, action = range.dataset.cardRange;
    let profile = null;
    range.addEventListener("pointerdown", () => { if (!range.disabled) { tile.dataset.rangeHeld = "true"; profile = store.me?.id; } });
    const latest = () => store.devices.get(id);
    const idle = () => { delete tile.dataset.rangeHeld; update(id); };
    const cancel = bindRelativeRange(range, {
      value: () => level(latest()?.state?.[action]) ?? Number(range.value),
      preview: value => { range.closest("label").querySelector("output").textContent = `${value}%`; range.setAttribute("aria-valuetext", `${value}%`); },
      commit: async value => {
        const d = latest();
        if (!d || (profile != null && profile !== store.me?.id)) return idle();
        if (unavailable(d) || store.busy.has(id) || !has(d,action === "volume" ? "volume_level" : "brightness")
            || (action === "volume" && has(d, "power") && d.state.on !== true)) {
          toast("This control is no longer available. Open the device to check its status.", true); return idle();
        }
        const focused = document.activeElement === range, owner = store.me?.id;
        delete tile.dataset.rangeHeld;
        await command(id, action, value, { [action]: value, ...(action === "brightness" ? {on: true} : {}) });
        idle();
        if (focused && owner === store.me?.id && range.isConnected && !root.closest("[hidden]")) range.focus({preventScroll:true});
      }, idle,
    });
    cancels.set(range, () => { cancel(); delete tile.dataset.rangeHeld; });
  }
}
