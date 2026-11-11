// The shape every device panel shares (the sheet that opens from a tile):
//
//   header  picture, name, live status, an on/off switch, settings, close
//   stage   one large control you operate directly (a brightness bar, a remote, a dial, a map)
//   dock    tabs for everything else, one tap away: no folded sections
//
// Each device kind (light.js, remote.js, speaker.js, vacuum.js, purifier.js) returns
// { stage, tabs: [{ id, label, html, alert? }], note? }; this file draws it.

import { esc, icon, isMedia, statusText } from "./util.js";
import { deviceIcon } from "./icons.js";
import { devicePicture } from "./art.js";

const has = (d, cap) => d.caps.includes(cap);

// ---------- header ----------
export function panelStatus(d) {
  const s = d.state || {};
  if (s.online === true && !s.needs_pairing && has(d, "power") && typeof s.on !== "boolean") return "Connected; power not reported";
  const text = statusText(d);
  return isMedia(d) && s.on === true && s.muted === true ? `${text} · Muted` : text;
}

// The on/off switch. Disabled while the device hasn't said whether it is on:
// a blind toggle could do the opposite of what the person wants.
export function powerSwitch(d) {
  if (!has(d, "power")) return "";
  const s = d.state || {}, known = typeof s.on === "boolean";
  return `<button class="switch" role="switch" data-power aria-checked="${s.on === true}"
    aria-label="${esc(d.name)} power${known ? "" : ", not reported"}" title="${known ? s.on ? "Turn off" : "Turn on" : "Power not reported"}" ${known ? "" : "disabled"}><i aria-hidden="true"></i></button>`;
}

export function panelHead(d, { controls = true } = {}) {
  const picture = devicePicture(d, `panel-${d.id}`);
  return `<header class="panel-head">
    <div class="panel-pic ${picture ? picture.kind : "line"}" aria-hidden="true">${picture ? picture.html : deviceIcon(d)}</div>
    <div class="panel-title"><h2>${esc(d.name)}</h2><p role="status">${esc(panelStatus(d))}</p></div>
    ${controls ? powerSwitch(d) : ""}
    <button class="icon-btn" data-edit aria-label="Device settings">${icon("gear")}</button>
    <button class="icon-btn" data-close aria-label="Close device controls">${icon("close")}</button>
  </header>`;
}

// ---------- tabs ----------
const chosenTab = new Map();      // device id -> tab id, kept while the panel redraws and reopens
export const setTab = (deviceId, tab) => chosenTab.set(deviceId, tab);

// The tab to show: the one the person picked if it still exists, else `prefer`
// (what the device is doing right now), else the first.
export function activeTab(deviceId, tabs, prefer = null) {
  const ids = tabs.map((t) => t.id);
  const picked = chosenTab.get(deviceId);
  return ids.includes(picked) ? picked : ids.includes(prefer) ? prefer : ids[0] ?? null;
}

function dock(deviceId, tabs, prefer) {
  if (!tabs.length) return "";
  const active = activeTab(deviceId, tabs, prefer);
  const pane = tabs.find((t) => t.id === active);
  const bar = tabs.length > 1 ? `<div class="panel-tabs" role="tablist" aria-label="More controls">${tabs.map((t) =>
    `<button role="tab" id="tab-${esc(t.id)}" data-tab="${esc(t.id)}" aria-selected="${t.id === active}" aria-controls="panel-pane"
      tabindex="${t.id === active ? 0 : -1}">${esc(t.label)}${t.alert ? '<i class="tab-alert" aria-label="needs attention"></i>' : ""}</button>`).join("")}</div>` : "";
  return `<div class="panel-dock">${bar}
    <div class="panel-pane" id="panel-pane" data-pane="${esc(pane.id)}" ${tabs.length > 1
      ? `role="tabpanel" aria-labelledby="tab-${esc(pane.id)}"` : `role="group" aria-label="${esc(pane.label)}"`}>${pane.html}</div></div>`;
}

// stage and/or tabs side by side on wide screens, stacked on narrow ones.
export function panelBody(d, { stage = "", tabs = [], prefer = null, note = "" } = {}) {
  const list = tabs.filter((t) => t && t.html);
  return `${note}<div class="panel ${stage && list.length ? "duo" : "solo"}">
    ${stage ? `<div class="panel-stage">${stage}</div>` : ""}${dock(d.id, list, prefer)}</div>`;
}

// Arrow keys move between tabs, as a tab list should.
export function tabKey(e) {
  const tab = e.target.closest?.('[role="tab"]');
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
  if (!tab || (!step && !["Home", "End"].includes(e.key))) return null;
  const tabs = [...tab.parentElement.querySelectorAll('[role="tab"]')];
  const next = e.key === "Home" ? tabs[0] : e.key === "End" ? tabs.at(-1) : tabs[(tabs.indexOf(tab) + step + tabs.length) % tabs.length];
  e.preventDefault();
  return next.dataset.tab;
}

// ---------- shared stage pieces ----------
// A device whose whole job is on/off (a plug, a switch, a TV that is off): one big button.
export function powerHero(d, hint = "") {
  const s = d.state || {}, known = typeof s.on === "boolean";
  const label = known ? (s.on ? "On" : "Off") : "Not reported";
  return `<div class="power-hero">
    <button class="power-orb" data-power aria-pressed="${!!s.on}" ${known ? "" : "disabled"}
      aria-label="${known ? `Turn ${s.on ? "off" : "on"} ${esc(d.name)}` : "Power not reported"}">${icon("power")}<b>${label}</b></button>
    ${hint ? `<p class="stage-hint">${esc(hint)}</p>` : ""}
    ${known ? "" : `<button class="btn small" data-refresh>Refresh status</button>`}
  </div>`;
}

// Choices as chips: one tap, the current one highlighted.
export function chipChoices(options, current, attr, { glyph = "", label = "" } = {}) {
  if (!options.length) return "";
  return `<div class="chips" role="group" ${label ? `aria-label="${esc(label)}"` : ""}>${options.map((o) =>
    `<button class="chip" ${attr}="${esc(o.id)}" aria-pressed="${String(o.id) === String(current)}">${glyph ? icon(glyph) : ""}<span>${esc(o.name)}</span></button>`).join("")}</div>`;
}
