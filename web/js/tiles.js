// Ordinary activation opens controls. Only explicit quick-action buttons send commands.

import { store, command } from "./store.js";
import { esc, icon, isMedia, glowVar, statusText, toast } from "./util.js";
import { openDevice } from "./sheet.js";
import { deviceIcon } from "./icons.js";
import { devicePicture } from "./art.js";
import { syncAttributes } from "./render.js";

const heldTiles = new Set(), pending = new Set();

// A short buzz where the browser can (Android, the Pi's touch screen); iOS ignores it.
export function haptic(ms = 10) {
  try { navigator.vibrate?.(ms); } catch { /* not allowed here */ }
}

const isOn = (d) => !!d.state?.on && d.state?.online !== false;

export function primaryAction(d) {
  const s = d.state || {};
  const disabled = s.online !== true || !!s.needs_pairing || store.busy.has(d.id) || pending.has(d.id);
  if (d.caps.includes("clean")) {
    const actions = { cleaning: ["pause", "Pause cleaning", "pause"], paused: ["resume", "Resume cleaning", "play"],
      idle: ["start", "Start cleaning", "play"], docked: ["start", "Start cleaning", "play"] };
    const action = actions[s.activity];
    return action ? { action: "clean", value: action[0], label: action[1], glyph: action[2], disabled } : null;
  }
  if (!d.caps.includes("power")) return null;
  const known = typeof s.on === "boolean";
  return { action: "power", value: String(!s.on), label: known ? `Turn ${s.on ? "off" : "on"}` : "Power status unavailable",
    glyph: "power", disabled: disabled || !known };
}

// size: the widget size on Home ("1x1", "2x1", "2x2"); ctx: "rooms" or "home".
// sub: optional text before the status, e.g. the room name on Home.
export function tileHtml(d, { size = "", ctx = "rooms", sub = "", editing = false } = {}) {
  const s = d.state || {};
  const on = isOn(d);
  const offline = s.online === false || s.needs_pairing;
  const level = d.kind === "light" && s.brightness ? Math.max(0.15, s.brightness / 100) : 1;
  const wide = size ? size !== "1x1" : ctx === "rooms" && isMedia(d);
  const busy = store.busy.has(d.id) || pending.has(d.id), quick = primaryAction(d);
  const cls = ["tile", on && "on", offline && "offline", busy && "busy", wide && "wide"]
    .filter(Boolean).join(" ");
  const status = statusText(d);
  const tvControls = isMedia(d) && d.caps.includes("volume") && on && wide ? `
      <div class="tile-tv-ctl">
        <button type="button" data-act="volume_down" aria-label="${esc(d.name)} volume down" ${busy || editing || offline || s.online !== true ? "disabled" : ""}>${icon("minus")}</button>
        <button type="button" data-act="volume_up" aria-label="${esc(d.name)} volume up" ${busy || editing || offline || s.online !== true ? "disabled" : ""}>${icon("plus")}</button>
      </div>` : "";
  return `
    <div class="${cls}" data-id="${esc(d.id)}" data-ctx="${ctx}" data-size="${esc(size)}" data-on="${on}" data-editing="${editing}"
         role="group" style="--glow:${glowVar(d)};--level:${level}" aria-busy="${busy}" aria-label="${esc(d.name)}">
      ${tilePicture(d, offline, ctx)}
      <div class="tile-tv-row">
        <button type="button" class="tile-open" data-more tabindex="${editing ? -1 : 0}"
          aria-disabled="${editing}" aria-label="${esc(d.name)}, ${esc(status)}. Open controls">
          <span class="tile-name">${esc(d.name)}</span>
          <span class="tile-status">${sub ? `${esc(sub)} · ` : ""}${esc(status)}</span>
        </button>
        ${quick ? `<button type="button" class="tile-quick" data-quick-action="${quick.action}" data-value="${quick.value}"
          aria-label="${esc(quick.label)}: ${esc(d.name)}" title="${esc(quick.label)}" ${quick.disabled || editing ? "disabled" : ""}>${icon(quick.glyph)}</button>` : ""}
        ${tvControls}
      </div>
    </div>`;
}

// The picture spot: the user's photo, an illustration, or the line icon (always the
// line icon while offline, so a problem is easy to spot).
function tilePicture(d, offline, ctx) {
  const pic = offline ? null : devicePicture(d, `tile-${ctx}-${d.id}`);
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
    if (heldTiles.has(old) || pending.has(id)) continue;
    const tmp = document.createElement("div");
    tmp.innerHTML = tileHtml(d, { size: old.dataset.size, ctx: old.dataset.ctx, sub: subFor(d, old), editing: old.dataset.editing === "true" });
    const el = tmp.firstElementChild;
    const turnedOn = old.dataset.on !== el.dataset.on && el.dataset.on === "true";
    syncAttributes(old, el);
    for (const selector of [".tile-name", ".tile-status"]) {
      const current = old.querySelector(selector), next = el.querySelector(selector);
      if (current.textContent !== next.textContent) current.textContent = next.textContent;
    }
    syncAttributes(old.querySelector("[data-more]"), el.querySelector("[data-more]"));
    const picture = old.querySelector(".tile-icon"), nextPicture = el.querySelector(".tile-icon");
    if (!picture.isEqualNode(nextPicture)) picture.replaceWith(nextPicture);
    for (const selector of [".tile-quick", ".tile-tv-ctl"]) {
      const current = old.querySelector(selector), next = el.querySelector(selector);
      if (current && next) {
        syncAttributes(current, next);
        if (selector === ".tile-quick") {
          if (current.innerHTML !== next.innerHTML) current.innerHTML = next.innerHTML;
        } else {
          current.querySelectorAll("[data-act]").forEach(button => syncAttributes(button, next.querySelector(`[data-act="${button.dataset.act}"]`)));
        }
      } else if (current) {
        const focused = current.contains(document.activeElement);
        current.remove();
        if (focused) old.querySelector("[data-more]").focus({ preventScroll: true });
      } else if (next) {
        if (selector === ".tile-quick") old.querySelector(".tile-tv-row").insertBefore(next, old.querySelector(".tile-tv-ctl"));
        else old.querySelector(".tile-tv-row").append(next);
      }
    }
    if (turnedOn && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      old.querySelector(".tile-icon").animate([{ opacity: .7 }, { opacity: 1 }], { duration: 200 });
    }
  }
  return true;
}

// Tap, long-press and buttons on tiles inside `root`. `enabled()` turns it off (e.g.
// while editing the Home page); `onLongPress(event)` is called for a long press that
// isn't on a tile.
export function bindTiles(root, { enabled = () => true, onLongPress = null } = {}) {
  let timer = null, long = false, start = null;
  const stop = () => { clearTimeout(timer); timer = null; };
  const release = () => {
    stop();
    if (start?.tile) { heldTiles.delete(start.tile); updateTiles(start.tile.dataset.id); }
    start = null;
  };

  root.addEventListener("pointerdown", (e) => {
    release();
    long = false;
    if (!enabled() || e.button > 0 || e.target.closest("input, select, label, .wmenu-wrap")) return;
    const tile = e.target.closest(".tile");
    if (e.target.closest("button:disabled")) return;
    start = { x: e.clientX, y: e.clientY, pointer: e.pointerId, tile, moved: false };
    if (tile) heldTiles.add(tile);
    if (tile ? e.target.closest("[data-quick-action], [data-act]") : !onLongPress) return;
    timer = setTimeout(() => {
      long = true;
      haptic(14);
      if (tile) openDevice(tile.dataset.id);
      else onLongPress(e);
      release();
    }, 480);
  });
  root.addEventListener("pointermove", (e) => {
    if (start && e.pointerId === start.pointer && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 10) {
      start.moved = true; stop();
    }
  });
  addEventListener("pointerup", (e) => {
    if (!start || e.pointerId !== start.pointer) return;
    stop();
    const box = start.tile?.getBoundingClientRect();
    if (start.moved || (box && (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom))) {
      long = true; release();
    }
  });
  root.addEventListener("pointercancel", () => { long = true; release(); });
  addEventListener("blur", release);
  root.addEventListener("contextmenu", (e) => { e.preventDefault(); release(); });

  root.addEventListener("click", (e) => {   // the long press already acted: this click isn't a tap
    if (long) {
      long = false;
      if (e.detail !== 0) { e.stopImmediatePropagation(); e.preventDefault(); release(); }
    }
  }, { capture: true });
  root.addEventListener("click", async (e) => {
    if (!enabled()) { release(); return; }
    const tile = e.target.closest(".tile");
    if (!tile) { release(); return; }
    const d = store.devices.get(tile.dataset.id);
    if (!d) { release(); return; }
    e.stopPropagation();
    const action = e.target.closest("[data-quick-action], [data-act]");
    if (!action) { openDevice(d.id); release(); return; }
    if (action.disabled) { release(); return; }
    if (pending.has(d.id) || store.busy.has(d.id)) { toast("Waiting for the device to finish the previous action."); release(); return; }
    const name = action.dataset.quickAction || action.dataset.act;
    const value = name === "power" ? action.dataset.value === "true" : action.dataset.value;
    const profile = store.me?.id, focused = document.activeElement === action;
    const cap = name === "power" ? "power" : name === "clean" ? "clean" : "volume";
    if (!d.caps.includes(cap) || d.state?.online !== true || d.state?.needs_pairing
      || (cap === "volume" && d.state.on !== true)) {
      toast("Open the controls to check this device's connection.", true); release(); return;
    }
    pending.add(d.id);
    tile.classList.add("busy"); tile.setAttribute("aria-busy", "true");
    tile.querySelector(".tile-status").textContent = "Updating...";
    tile.querySelectorAll("[data-quick-action], [data-act]").forEach(button => { button.disabled = true; });
    haptic(6);
    try { await command(d.id, name, value); }
    finally {
      pending.delete(d.id); release(); updateTiles(d.id);
      if (focused && profile === store.me?.id && (document.activeElement === document.body || document.activeElement === action)) {
        const live = root.querySelector(`.tile[data-id="${CSS.escape(d.id)}"]`);
        (live?.querySelector(`[data-quick-action="${name}"], [data-act="${name}"]`) || live?.querySelector("[data-more]"))?.focus({ preventScroll: true });
      }
    }
  });
}
