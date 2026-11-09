// Robot vacuum controls for the device sheet: the map, a status line, one main
// button that does the obvious next thing, rooms as chips, an Options section
// (suction, mode, station jobs) and parts wear behind a Maintenance row.

import { api } from "./api.js";
import { esc, icon } from "./util.js";

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

export function vacuumBody(d) {
  const s = d.state || {};
  const a = s.activity;
  const m = d.meta || {};
  const rooms = has(d, "rooms") ? m.rooms || [] : [];
  const chosen = picked(d.id);
  for (const id of [...chosen]) if (!rooms.some((r) => String(r.id) === id)) chosen.delete(id);
  const running = a === "cleaning";

  // The one big button: pause while cleaning, resume when paused, otherwise start
  // (or clean just the rooms the user picked).
  const main = !ACTIVITY[a] ? `<button class="btn primary vac-main" data-refresh>Refresh status</button>`
    : running ? `<button class="btn primary vac-main" data-clean="pause" data-activity="paused">${icon("pause")}Pause</button>`
    : a === "paused" ? `<button class="btn primary vac-main" data-clean="resume" data-activity="cleaning">${icon("play")}Keep cleaning</button>`
    : chosen.size ? `<button class="btn primary vac-main" data-clean-rooms>${icon("play")}Clean ${chosen.size === 1 ? "1 room" : `${chosen.size} rooms`}</button>`
    : `<button class="btn primary vac-main" data-clean="start" data-activity="cleaning">${icon("play")}Start cleaning</button>`;
  const side = [
    (running || a === "paused") && `<button class="vac-act" data-clean="stop" data-activity="idle">${icon("stop")}<span>Stop</span></button>`,
  ].filter(Boolean).join("");
  const secondary = [
    ACTIVITY[a] && has(d, "dock") && a !== "docked" && a !== "returning" && `<button class="vac-act" data-dock>${icon("home")}<span>Dock</span></button>`,
    has(d, "locate") && `<button class="vac-act" data-locate>${icon("target")}<span>Find</span></button>`,
  ].filter(Boolean).join("");

  const [label, ic] = ACTIVITY[a] || ["Connecting…", "vacuum"];
  const charging = a === "docked" && s.battery != null && s.battery < 100;
  const last = s.last_clean;
  const lastText = last && (last.area_m2 != null || last.minutes != null)
    ? `Last clean ${[last.area_m2 != null ? `${last.area_m2} m²` : "", last.minutes != null ? `${last.minutes} min` : ""].filter(Boolean).join(" in ")}` : "";

  const options = [
    has(d, "suction") && m.suction_levels?.length && `<div class="opt"><div class="opt-label">${icon("fan")}Suction</div>
      ${seg(m.suction_levels, s.suction, "data-suction")}</div>`,
    has(d, "clean_mode") && m.clean_modes?.length && `<div class="opt"><div class="opt-label">${icon("drop")}Mode</div>
      ${seg(m.clean_modes, s.clean_mode, "data-clean-mode", modeIcon)}</div>`,
    has(d, "station") && m.station_actions?.length && `<details class="control-section" data-control-section="station"><summary>Dock actions</summary>
      <div class="station">${m.station_actions.map((o) => `<button class="btn" data-station="${esc(String(o.id))}">
        ${icon(stationIcon(String(o.id)))}<span>${esc(o.name)}</span></button>`).join("")}</div></details>`,
  ].filter(Boolean).join("");

  const parts = s.parts || [];
  const worst = parts.reduce((w, p) => (w && w.percent <= p.percent ? w : p), null);

  return `<div class="vac">
    <div class="vac-col">
      <div class="vac-status" role="status">
        <span class="vac-state ${a || ""}">${icon(ic)}<b>${charging ? "Charging" : label}</b></span>
        ${s.battery != null ? `<span class="vac-batt ${s.battery <= 20 ? "low" : ""}" style="--pct:${s.battery}"
          role="meter" aria-label="Battery" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${s.battery}">
          <i aria-hidden="true"></i>Battery ${s.battery}%</span>` : ""}
      </div>
      ${lastText ? `<p class="vac-last">${esc(lastText)}</p>` : ""}
      ${s.problem ? `<div class="note warn">${esc(s.problem)}</div>` : ""}
      <div class="vac-actions">${main}${side}</div>
      ${secondary ? `<div class="vac-secondary" role="group" aria-label="Dock and locate">${secondary}</div>` : ""}
      ${has(d, "map") ? `<div class="vac-map loading" aria-busy="true"><img src="${api.mapUrl(d.id, s.map_rev || 0)}" alt="Map of your home">
        <span role="status">Loading map...</span></div>` : ""}
    </div>
    <div class="vac-col">
      ${rooms.length ? `<details class="control-section" data-control-section="vac-rooms"><summary>Choose rooms${chosen.size ? ` (${chosen.size} selected)` : ""}</summary>
        <div class="section-label"><span>Rooms</span>
          ${chosen.size ? `<button class="link" data-rooms-clear>Clear</button>` : `<b class="soft">Tap rooms to clean only those</b>`}</div>
        <div class="chips">${rooms.map((r) => { const on = chosen.has(String(r.id)); return `<button class="chip room-chip"
          data-room-pick="${esc(String(r.id))}" aria-pressed="${on}">${on ? icon("check") : ""}${esc(r.name)}</button>`; }).join("")}</div></details>` : ""}
      ${options ? `<details class="control-section" data-control-section="vac-options"><summary>Cleaning options</summary><div class="opts">${options}</div></details>` : ""}
      ${parts.length ? `<details class="vac-parts" data-control-section="maintenance">
          <summary class="maint-row">${icon("wrench")}<span class="grow"><span class="title">Maintenance</span>
            <span class="sub ${worst.percent <= 10 ? "warn" : ""}">${worst.percent <= 10 ? `${esc(worst.name)} needs replacing`
              : `All parts good. ${esc(worst.name)} at ${worst.percent}%`}</span></span>${icon("down", "chev")}</summary>
          ${parts.map((p) => `<div class="part"><span>${esc(p.name)}</span>
            <div class="meter small"><div class="meter-fill ${p.percent <= 10 ? "low" : ""}" style="width:${p.percent}%"></div></div>
            <b>${p.percent}%</b></div>`).join("")}</details>` : ""}
    </div>
  </div>`;
}
