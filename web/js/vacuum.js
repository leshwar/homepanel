// Robot vacuum panel. Stage: what it is doing, the map, and one main button that does the
// obvious next thing (with Stop / Dock / Find beside it). Tabs: Rooms (pick some and the
// main button becomes "Clean 2 rooms"), Options (suction, mode), Station, Care (parts wear).

import { api } from "./api.js";
import { esc, icon, WORN_PERCENT } from "./util.js";

const has = (d, c) => d.caps.includes(c);

// Rooms picked for "Clean these rooms", per vacuum. Kept while the sheet re-renders.
const pickedRooms = new Map();
export const picked = (id) => { if (!pickedRooms.has(id)) pickedRooms.set(id, new Set()); return pickedRooms.get(id); };

const ACTIVITY = {
  cleaning: ["Cleaning", "vacuum"], paused: ["Paused", "pause"], returning: ["Going back to dock", "home"],
  docked: ["Docked", "home"], idle: ["Ready", "vacuum"], error: ["Needs help", "info"],
};

// Icons for option ids. Matched on words, so they fit any brand's names.
const modeIcon = (id) => (/mop/.test(id) && /vac/.test(id) ? "vacmop" : /mop/.test(id) ? "drop" : "vacuum");
const stationIcon = (id) => (/dust|empty|bin|bag/.test(id) ? "bin" : /wash/.test(id) ? "drop"
  : /dry/.test(id) ? "wind" : "sparkle");

const seg = (list, current, attr, iconFor) => `<div class="seg ${iconFor ? "with-icons" : ""}" role="group">${list.map((o) => {
  const id = String(o.id);
  return `<button ${attr}="${esc(id)}" aria-pressed="${String(current) === id}">${iconFor ? icon(iconFor(id)) : ""}<span>${esc(o.name)}</span></button>`;
}).join("")}</div>`;

export function vacuumPanel(d) {
  const s = d.state || {};
  const a = s.activity;
  const m = d.meta || {};
  const rooms = has(d, "rooms") ? m.rooms || [] : [];
  const chosen = picked(d.id);
  for (const id of [...chosen]) if (!rooms.some((r) => String(r.id) === id)) chosen.delete(id);
  const running = a === "cleaning";

  // The one big button: pause while cleaning, resume when paused, otherwise start
  // (or clean just the rooms the person picked).
  const main = !ACTIVITY[a] ? `<button class="btn primary vac-main" data-refresh>Refresh status</button>`
    : running ? `<button class="btn primary vac-main" data-clean="pause" data-activity="paused">${icon("pause")}Pause</button>`
    : a === "paused" ? `<button class="btn primary vac-main" data-clean="resume" data-activity="cleaning">${icon("play")}Keep cleaning</button>`
    : chosen.size ? `<button class="btn primary vac-main" data-clean-rooms>${icon("play")}Clean ${chosen.size === 1 ? "1 room" : `${chosen.size} rooms`}</button>`
    : `<button class="btn primary vac-main" data-clean="start" data-activity="cleaning">${icon("play")}Start cleaning</button>`;
  const round = (attrs, glyph, label) => `<button class="rkey" ${attrs} aria-label="${label}">${icon(glyph)}<span>${label}</span></button>`;
  const side = [
    (running || a === "paused") && round('data-clean="stop" data-activity="idle"', "stop", "Stop"),
    ACTIVITY[a] && has(d, "dock") && a !== "docked" && a !== "returning" && round("data-dock", "home", "Dock"),
    has(d, "locate") && round("data-locate", "target", "Find"),
  ].filter(Boolean).join("");

  const [label, ic] = ACTIVITY[a] || ["Connecting…", "vacuum"];
  const charging = a === "docked" && s.battery != null && s.battery < 100;
  const last = s.last_clean;
  const lastText = last && (last.area_m2 != null || last.minutes != null)
    ? `Last clean ${[last.area_m2 != null ? `${last.area_m2} m²` : "", last.minutes != null ? `${last.minutes} min` : ""].filter(Boolean).join(" in ")}` : "";

  const stage = `<div class="vac-stage">
      <div class="vac-status" role="status">
        <span class="vac-state ${a || ""}">${icon(ic)}<b>${charging ? "Charging" : label}</b></span>
        ${s.battery != null ? `<span class="vac-batt ${s.battery <= 20 ? "low" : ""}" style="--pct:${s.battery}"
          role="meter" aria-label="Battery" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${s.battery}">
          <i aria-hidden="true"></i>${s.battery}%</span>` : ""}
      </div>
      ${s.problem ? `<div class="note warn">${esc(s.problem)}</div>` : ""}
      ${has(d, "map") ? `<div class="vac-map loading" aria-busy="true"><img src="${api.mapUrl(d.id, s.map_rev || 0)}" alt="Map of your home">
        <span role="status">Loading map...</span></div>` : ""}
      ${lastText ? `<p class="stage-hint">${esc(lastText)}</p>` : ""}
      <div class="vac-actions">${main}${side}</div>
    </div>`;

  const parts = s.parts || [];
  const worst = parts.reduce((w, p) => (w && w.percent <= p.percent ? w : p), null);
  const worn = !!worst && worst.percent <= WORN_PERCENT;
  const options = [
    has(d, "suction") && m.suction_levels?.length && `<div class="opt"><div class="opt-label">${icon("fan")}Suction</div>
      ${seg(m.suction_levels, s.suction, "data-suction")}</div>`,
    has(d, "clean_mode") && m.clean_modes?.length && `<div class="opt"><div class="opt-label">${icon("drop")}Mode</div>
      ${seg(m.clean_modes, s.clean_mode, "data-clean-mode", modeIcon)}</div>`,
  ].filter(Boolean).join("");

  const tabs = [
    rooms.length && { id: "rooms", label: "Rooms", html: `<div class="pane-bar">
        <span class="pane-help">${chosen.size ? `${chosen.size} selected` : "Tap rooms to clean only those"}</span>
        ${chosen.size ? `<button class="link" data-rooms-clear>Clear</button>` : ""}</div>
      <div class="chips" role="group" aria-label="Rooms">${rooms.map((r) => { const on = chosen.has(String(r.id)); return `<button class="chip room-chip"
        data-room-pick="${esc(String(r.id))}" aria-pressed="${on}">${on ? icon("check") : ""}<span>${esc(r.name)}</span></button>`; }).join("")}</div>` },
    options && { id: "options", label: "Options", html: `<div class="opts">${options}</div>` },
    has(d, "station") && m.station_actions?.length && { id: "station", label: "Station",
      html: `<div class="station">${m.station_actions.map((o) => `<button class="btn" data-station="${esc(String(o.id))}">
        ${icon(stationIcon(String(o.id)))}<span>${esc(o.name)}</span></button>`).join("")}</div>` },
    parts.length && { id: "care", label: "Care", alert: worn, html: `<p class="care-line ${worn ? "warn" : ""}">${icon("wrench")}${
        worn ? `${esc(worst.name)} needs replacing` : `All parts good. ${esc(worst.name)} at ${worst.percent}%`}</p>
      <div class="parts">${parts.map((p) => `<div class="part"><span>${esc(p.name)}</span>
        <div class="meter small"><div class="meter-fill ${p.percent <= WORN_PERCENT ? "low" : ""}" style="width:${p.percent}%"></div></div>
        <b>${p.percent}%</b></div>`).join("")}</div>` },
  ].filter(Boolean);
  return { stage, tabs };
}
