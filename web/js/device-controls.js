// Shared sheet labels and release-to-apply sliders. Device-specific layouts stay separate.
import { esc, icon, statusText } from "./util.js";

export function deviceHeading(d) {
  const s = d.state || {};
  const status = s.online === true && !s.needs_pairing && d.caps.includes("power") && typeof s.on !== "boolean"
    ? "Connected; power not reported" : statusText(d);
  return `<div class="device-head sheet-head">
    <div class="grow"><h2>${esc(d.name)}</h2><p role="status">${esc(status)}</p></div>
    <button class="icon-btn" data-close aria-label="Close device controls">${icon("close")}</button>
  </div>`;
}

export function powerControls(d) {
  const s = d.state || {};
  const toggle = (attr, title, known, state, action, glyph, disabled = false) => `
    <button class="speaker-toggle" ${attr} aria-pressed="${!!state}" ${!known || disabled ? "disabled" : ""}>
      ${icon(glyph)}<span><b>${title}: ${known ? state ? "On" : "Off" : "Unknown"}</b>
      <small>${known ? action : "Refresh the device status"}</small></span>
    </button>`;
  const power = d.caps.includes("power") ? toggle("data-power", "Power", typeof s.on === "boolean",
    s.on, s.on ? "Turn off" : "Turn on", "power") : "";
  // A device that is off can't say whether it is muted: leave the button out instead of "Unknown".
  const mute = d.caps.includes("mute") && !(s.on === false && typeof s.muted !== "boolean") ? toggle("data-mute", "Mute", typeof s.muted === "boolean",
    s.muted, s.muted ? "Unmute" : "Mute audio", s.muted ? "mute" : "vol", s.on === false) : "";
  return power || mute ? `<div class="device-power speaker-toggles">${power}${mute}</div>` : "";
}

export const relativeValue = (base, start, point, length, min = 0, max = 100, step = 1) =>
  Math.max(min, Math.min(max, Math.round((base + (point - start) / Math.max(1, length) * (max - min)) / step) * step));

const gestures = new Map();
export const controlGestureBusy = () => gestures.size > 0;
export function clearControlGestures() {
  for (const cancel of gestures.values()) cancel();
  gestures.clear();
}

export function bindRelativeRange(range, { value, preview, commit, idle }) {
  let drag = null, pointerChange = false;
  const show = (v) => { range.value = v; preview(v); };
  const cancel = () => { drag = null; show(value()); };
  for (const event of ["touchstart", "touchmove"]) range.addEventListener(event, (e) => e.preventDefault(), { passive: false });
  range.addEventListener("pointerdown", (e) => {
    if (range.disabled || e.button > 0 || gestures.size) return;
    e.preventDefault();
    range.focus({ preventScroll: true });
    range.setPointerCapture(e.pointerId);
    drag = { pointer: e.pointerId, base: value(), value: value(), x: e.clientX, y: e.clientY,
      width: range.getBoundingClientRect().width, moved: false, canceled: false };
    gestures.set(range, cancel);
  });
  range.addEventListener("pointermove", (e) => {
    if (!drag || drag.pointer !== e.pointerId) return;
    e.preventDefault();
    const dx = Math.abs(e.clientX - drag.x), dy = Math.abs(e.clientY - drag.y);
    if (!drag.moved && dy > 6 && dy > dx) drag.canceled = true;
    if (drag.canceled) return;
    if (dx > 6) drag.moved = true;
    if (drag.moved) {
      drag.value = relativeValue(drag.base, drag.x, e.clientX, drag.width,
        Number(range.min), Number(range.max), Number(range.step) || 1);
      show(drag.value);
    }
  });
  const finish = (e) => {
    if (!drag || drag.pointer !== e.pointerId) return;
    e.preventDefault();
    const done = drag;
    drag = null; gestures.delete(range);
    pointerChange = true;
    setTimeout(() => { pointerChange = false; }, 0);
    if (e.type === "pointerup" && !done.canceled && done.moved && done.value !== done.base) commit(done.value);
    else { show(value()); idle(); }
  };
  range.addEventListener("pointerup", finish);
  range.addEventListener("pointercancel", finish);
  range.addEventListener("lostpointercapture", finish);
  range.addEventListener("input", () => { if (!drag) preview(Number(range.value)); });
  range.addEventListener("change", () => {
    if (!drag && !pointerChange && range.isConnected && !range.closest(".closing")) commit(Number(range.value));
  });
}
