// Device tiles, used by the Rooms view and by device widgets on the Home page.
//
// Tap = the obvious thing: switch it on or off. Devices that shouldn't be switched
// by a stray tap (TVs) or have no on/off (e.g. a robot vacuum) open their controls
// instead: TVs and sound bars (media), and anything without power (a robot vacuum).
// Long-press or the "…" button always opens the controls.

import { store, command } from "./store.js";
import { esc, icon, isMedia, glowVar, statusText, toast } from "./util.js";
import { openDevice } from "./sheet.js";
import { deviceIcon, svg } from "./icons.js";
import { devicePicture } from "./art.js";

// A short buzz where the browser can (Android, the Pi's touch screen); iOS ignores it.
export function haptic(ms = 10) {
  try { navigator.vibrate?.(ms); } catch { /* not allowed here */ }
}

export const tapOpens = (d) => isMedia(d) || !d.caps.includes("power");

const isOn = (d) => !!d.state?.on && d.state?.online !== false;

// size: the widget size on Home ("1x1", "2x1", "2x2"); ctx: "rooms" or "home".
// sub: optional text before the status, e.g. the room name on Home.
export function tileHtml(d, { size = "", ctx = "rooms", sub = "" } = {}) {
  const s = d.state || {};
  const on = isOn(d);
  const offline = s.online === false || s.needs_pairing;
  const level = d.kind === "light" && s.brightness ? Math.max(0.15, s.brightness / 100) : 1;
  const wide = size ? size !== "1x1" : ctx === "rooms" && isMedia(d);
  const cls = ["tile", on && "on", offline && "offline", store.busy.has(d.id) && "busy", wide && "wide"]
    .filter(Boolean).join(" ");
  const status = statusText(d);
  const tvControls = isMedia(d) && on && wide ? `
      <div class="tile-tv-ctl">
        <button data-act="volume_down" aria-label="Volume down">${icon("minus")}</button>
        <button data-act="volume_up" aria-label="Volume up">${icon("plus")}</button>
      </div>` : "";
  return `
    <div class="${cls}" data-id="${esc(d.id)}" data-ctx="${ctx}" data-size="${esc(size)}" data-on="${on}"
         role="button" tabindex="0" style="--glow:${glowVar(d)};--level:${level}"
         aria-label="${esc(d.name)}, ${esc(status)}${tapOpens(d) ? "" : on ? ". Tap to turn off" : ". Tap to turn on"}">
      ${tilePicture(d, offline)}
      <button class="tile-more" data-more aria-label="${esc(d.name)} controls">${svg("dots")}</button>
      <div class="tile-tv-row">
        <div class="tile-text">
          <div class="tile-name">${esc(d.name)}</div>
          <div class="tile-status">${sub ? `${esc(sub)} · ` : ""}${esc(status)}</div>
        </div>
        ${tvControls}
      </div>
    </div>`;
}

// The picture spot: the user's photo, an illustration, or the line icon (always the
// line icon while offline, so a problem is easy to spot).
function tilePicture(d, offline) {
  const pic = offline ? null : devicePicture(d);
  if (!pic) return `<div class="tile-icon">${offline ? icon("wifi-off") : deviceIcon(d)}</div>`;
  return `<div class="tile-icon pic ${pic.kind}">${pic.html}</div>`;
}

// Re-draw every tile showing this device (it can be on Home and in Rooms).
// Returns false if none is on screen.
export function updateTiles(id, subFor = () => "") {
  const d = store.devices.get(id);
  const els = document.querySelectorAll(`.tile[data-id="${CSS.escape(id)}"]`);
  if (!d || !els.length) return false;
  for (const old of els) {
    const tmp = document.createElement("div");
    tmp.innerHTML = tileHtml(d, { size: old.dataset.size, ctx: old.dataset.ctx, sub: subFor(d, old) });
    const el = tmp.firstElementChild;
    if (old.dataset.on !== el.dataset.on && el.dataset.on === "true") el.classList.add("pop");   // a little bounce when it lights up
    old.replaceWith(el);
  }
  return true;
}

export function toggle(d) {
  if (d.state?.needs_pairing) return openDevice(d.id);
  if (d.state?.online === false) {
    toast(`${d.name} is offline. ${d.state.error || ""}`.trim(), true);
    return;
  }
  const on = !d.state?.on;
  haptic(6);
  command(d.id, "power", on, { on });
}

// Tap, long-press and buttons on tiles inside `root`. `enabled()` turns it off (e.g.
// while editing the Home page); `onLongPress(event)` is called for a long press that
// isn't on a tile.
export function bindTiles(root, { enabled = () => true, onLongPress = null } = {}) {
  let timer = null, long = false, start = null;
  const stop = () => { clearTimeout(timer); timer = null; };

  root.addEventListener("pointerdown", (e) => {
    long = false;
    start = { x: e.clientX, y: e.clientY };
    if (!enabled() || e.button > 0 || e.target.closest("input, select, label, .wmenu-wrap")) return;
    const tile = e.target.closest(".tile");
    if (tile ? e.target.closest("button") : !onLongPress) return;     // a tile's own buttons act on tap
    timer = setTimeout(() => {
      long = true;
      haptic(14);
      if (tile) openDevice(tile.dataset.id);
      else onLongPress(e);
    }, 480);
  });
  root.addEventListener("pointermove", (e) => {
    if (timer && start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 10) stop();
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach((t) => root.addEventListener(t, stop));
  root.addEventListener("contextmenu", (e) => e.preventDefault());

  root.addEventListener("click", (e) => {   // the long press already acted: this click isn't a tap
    if (long) { long = false; e.stopImmediatePropagation(); e.preventDefault(); }
  }, { capture: true });
  root.addEventListener("click", (e) => {
    if (!enabled()) return;
    const tile = e.target.closest(".tile");
    if (!tile) return;
    const d = store.devices.get(tile.dataset.id);
    if (!d) return;
    if (e.target.closest("[data-more]")) return openDevice(d.id);
    const act = e.target.closest("[data-act]");
    if (act) return command(d.id, act.dataset.act);
    if (tapOpens(d)) return openDevice(d.id);   // never toggle a TV or sound bar by accident; vacuums have no on/off
    toggle(d);
  });
  root.addEventListener("keydown", (e) => {
    const tile = e.target.closest(".tile");
    if (tile && e.target === tile && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); tile.click(); }
  });
}
