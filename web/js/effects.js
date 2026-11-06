// Light effects in the light sheet: scenes (grouped Scenes / DIY / Snapshots, searchable),
// music mode (mode chips + sensitivity), strip parts (tap parts, then a color) and feature
// toggles such as gradient or screen sync. Each section shows only when the device lists it
// (caps "effects", "music", "segments", "toggles"; the lists are in device.meta).

import { command } from "./store.js";
import { esc, toast } from "./util.js";

const GROUPS = ["Scenes", "DIY", "Snapshots"];
const SEGMENT_COLORS = [
  { c: "#ff5a3c", name: "Red" }, { c: "#ffa53c", name: "Amber" }, { c: "#ffe14d", name: "Yellow" },
  { c: "#5ee07a", name: "Green" }, { c: "#3fd6d0", name: "Teal" }, { c: "#4f7bff", name: "Blue" },
  { c: "#a35cff", name: "Purple" }, { c: "#ff5cb8", name: "Pink" }, { c: "#ffffff", name: "White" },
];
const SEARCH_FROM = 9;            // show the search box when there are more effects than this

// What the person is doing in this sheet, kept across re-renders (live updates redraw it).
const ui = { id: null, query: "", sensitivity: 50, parts: new Set(), listTop: 0 };
function forDevice(id) {
  if (ui.id !== id) Object.assign(ui, { id, query: "", parts: new Set(), listTop: 0 });
  return ui;
}

const has = (d, c) => d.caps.includes(c);

// Effects take over the light: which plain-light keys to clear when one starts.
const OFF = { effect: null, music: null, segments: null };

export function effectsBody(d) {
  const st = forDevice(d.id);
  const s = d.state || {};
  let html = "";
  if (d.meta?.hint) html += `<div class="note fx-hint">${esc(d.meta.hint)}</div>`;

  if (has(d, "effects")) {
    const all = d.meta?.effects || [];
    const active = all.find((e) => s.color_mode === "effect" && e.id === s.effect);
    const groups = GROUPS.map((g) => [g, all.filter((e) => (e.group || "Scenes") === g)]).filter(([, l]) => l.length);
    const showGroups = groups.length > 1;
    const list = groups.map(([g, l]) => `<div class="fx-group" data-fx-group>
        ${showGroups ? `<div class="fx-group-name">${esc(g)}</div>` : ""}
        <div class="chips">${l.map((e) => `<button class="chip" data-effect="${esc(e.id)}" data-name="${esc(e.name.toLowerCase())}"
          aria-pressed="${active?.id === e.id}">${esc(e.name)}</button>`).join("")}</div></div>`).join("");
    html += `<section class="fx" aria-label="Scenes">
      <div class="section-label"><span>Scenes${active ? ` <b>${esc(active.name)}</b>` : ""}</span>
        <button class="link" data-fx-update>Update list</button></div>
      ${all.length > SEARCH_FROM ? `<input class="fx-search" type="search" placeholder="Search ${all.length} scenes"
        aria-label="Search scenes" value="${esc(st.query)}" autocomplete="off" enterkeyhint="search">` : ""}
      ${all.length ? `<div class="fx-list" data-fx-list>${list}<p class="fx-none" hidden>No scenes match.</p></div>`
        : `<p class="fx-none">No scenes yet. Make some in the light's own app, then tap Update list.</p>`}
    </section>`;
  }

  if (has(d, "music")) {
    const modes = d.meta?.music_modes || [];
    const on = s.color_mode === "music" && s.music;
    if (on && s.music.sensitivity != null) st.sensitivity = s.music.sensitivity;
    html += `<section class="fx" aria-label="Music">
      <div class="section-label"><span>Music${on ? ` <b>${esc(modes.find((m) => m.id === s.music.mode)?.name || "")}</b>` : ""}</span></div>
      <div class="chips">${modes.map((m) => `<button class="chip" data-music-mode="${esc(m.id)}"
        aria-pressed="${!!(on && s.music.mode === m.id)}">${esc(m.name)}</button>`).join("")}</div>
      <label class="fx-range"><span>Sensitivity <b data-sens-val>${st.sensitivity}%</b></span>
        <input type="range" class="glass-range" min="0" max="100" step="5" value="${st.sensitivity}" data-sensitivity
          aria-label="Music sensitivity"></label>
      <p class="hint fx-note">The light listens with its own microphone.</p>
    </section>`;
  }

  if (has(d, "segments")) {
    const n = Number(d.meta?.segments) || 0;
    const colors = Array.isArray(s.segments) ? s.segments : [];
    const parts = Array.from({ length: n }, (_, i) => {
      const c = colors[i];
      return `<button class="seg-part ${c ? "lit" : ""}" data-seg="${i}" style="${c ? `--sw:${esc(c)}` : ""}"
        aria-pressed="${st.parts.has(i)}" aria-label="Part ${i + 1}${c ? `, ${esc(c)}` : ""}">${i + 1}</button>`;
    }).join("");
    html += `<section class="fx" aria-label="Strip parts">
      <div class="section-label"><span>Strip parts <span class="soft">Tap parts, then a color</span></span>
        <button class="link" data-seg-all>${st.parts.size === n && n ? "Clear" : "Select all"}</button></div>
      <div class="seg-strip" role="group" aria-label="Parts of the strip">${parts}</div>
      <div class="presets seg-colors" role="group" aria-label="Color for the chosen parts">
        ${SEGMENT_COLORS.map((c) => `<button class="swatch" data-seg-color="${c.c}" style="--sw:${c.c}" aria-label="${c.name}"></button>`).join("")}
      </div>
    </section>`;
  }

  if (has(d, "toggles") && (d.meta?.toggles || []).length) {
    const t = s.toggles || {};
    html += `<section class="fx" aria-label="Options">
      <div class="section-label"><span>Options</span></div>
      <div class="chips">${d.meta.toggles.map((x) => `<button class="chip fx-toggle" data-toggle="${esc(x.id)}"
        aria-pressed="${!!t[x.id]}"><i aria-hidden="true"></i>${esc(x.name)}</button>`).join("")}</div>
    </section>`;
  }
  return html ? `<div class="fx-wrap">${html}</div>` : "";
}

// Filter the scene chips without redrawing (so typing isn't interrupted).
function filter(sheet) {
  const list = sheet.querySelector("[data-fx-list]");
  if (!list) return;
  const q = ui.query.trim().toLowerCase();
  let shown = 0;
  for (const g of list.querySelectorAll("[data-fx-group]")) {
    let inGroup = 0;
    for (const b of g.querySelectorAll("[data-effect]")) {
      const ok = !q || b.dataset.name.includes(q);
      b.hidden = !ok;
      inGroup += ok;
    }
    g.hidden = !inGroup;
    shown += inGroup;
  }
  list.querySelector(".fx-none").hidden = shown > 0;
}

// The sheet is about to redraw: remember where the scene list was scrolled to.
export function keepEffects(sheet, same) {
  const list = sheet.querySelector("[data-fx-list]");
  ui.listTop = same && list ? list.scrollTop : 0;
}

// Typing in the search box: the sheet waits with live redraws until the box loses focus.
export const effectsBusy = () => document.activeElement?.classList?.contains("fx-search");

export function attachEffects(sheet, d, onIdle) {
  forDevice(d.id);
  const list = sheet.querySelector("[data-fx-list]");
  if (list) { filter(sheet); list.scrollTop = ui.listTop; }
  const search = sheet.querySelector(".fx-search");
  if (search) {
    search.addEventListener("input", () => { ui.query = search.value; filter(sheet); });
    search.addEventListener("blur", onIdle);
  }
  const range = sheet.querySelector("[data-sensitivity]");
  if (range) {
    const val = sheet.querySelector("[data-sens-val]");
    range.addEventListener("input", () => { val.textContent = `${range.value}%`; });
    range.addEventListener("change", () => {
      ui.sensitivity = +range.value;
      const s = d.state || {};
      if (s.color_mode === "music" && s.music) sendMusic(d, s.music.mode);   // only while music is playing
    });
  }
}

function sendMusic(d, mode) {
  const value = { mode, sensitivity: ui.sensitivity };
  return command(d.id, "set_music", value, { on: true, ...OFF, music: value, color_mode: "music" });
}

// Handles a click in the sheet. Returns "render" to redraw, true if handled, false if not ours.
export function effectsClick(e, d) {
  const t = (sel) => e.target.closest(sel);
  const st = forDevice(d.id);
  if (t("[data-effect]")) {
    const id = t("[data-effect]").dataset.effect;
    command(d.id, "set_effect", id, { on: true, ...OFF, effect: id, color_mode: "effect" });
    return true;
  }
  if (t("[data-fx-update]")) {
    const b = t("[data-fx-update]");
    b.disabled = true; b.textContent = "Updating…";
    command(d.id, "update_effects").then((ok) => { if (ok) toast("Scene list updated"); });
    return true;
  }
  if (t("[data-music-mode]")) { sendMusic(d, t("[data-music-mode]").dataset.musicMode); return true; }
  if (t("[data-seg]")) {
    const b = t("[data-seg]"), i = +b.dataset.seg;
    st.parts.has(i) ? st.parts.delete(i) : st.parts.add(i);
    b.setAttribute("aria-pressed", st.parts.has(i));
    return "render";
  }
  if (t("[data-seg-all]")) {
    const n = Number(d.meta?.segments) || 0;
    st.parts = st.parts.size === n ? new Set() : new Set(Array.from({ length: n }, (_, i) => i));
    return "render";
  }
  if (t("[data-seg-color]")) {
    if (!st.parts.size) { toast("Tap the parts of the strip to color first."); return true; }
    const color = t("[data-seg-color]").dataset.segColor;
    const segments = [...st.parts].sort((a, b) => a - b);
    const n = Number(d.meta?.segments) || 0;
    const now = (Array.isArray(d.state?.segments) ? [...d.state.segments] : []).concat(Array(n).fill(null)).slice(0, n);
    segments.forEach((i) => { now[i] = color; });
    command(d.id, "set_segments", { segments, color }, { on: true, ...OFF, segments: now, color_mode: "segments" });
    return true;
  }
  if (t("[data-toggle]")) {
    const id = t("[data-toggle]").dataset.toggle;
    const cur = (d.state?.toggles || {})[id];
    command(d.id, "set_toggle", { id, on: !cur }, { toggles: { ...(d.state?.toggles || {}), [id]: !cur } });
    return true;
  }
  return false;
}
