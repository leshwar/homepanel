// Purifier controls use generic capability metadata, never a brand protocol.
import { esc } from "./util.js";

export function purifierBody(d) {
  const s = d.state || {};
  const choices = (cap, key, attr, title, selected) => !d.caps.includes(cap) ? "" : `
    <section class="purifier-options"><h3>${title}</h3>
      <div class="chips" role="group" aria-label="${title}">${(d.meta?.[key] || []).map(option =>
        `<button class="chip" ${attr}="${esc(option.id)}" aria-pressed="${s.on === true && String(selected) === String(option.id)}">${esc(option.name)}</button>`).join("")}</div>
    </section>`;
  const reading = (label, value, unit = "") => `<div><span>${label}</span>
    <b>${value == null ? "Not reported" : esc(value)}</b>${value != null && unit ? `<small>${unit}</small>` : ""}</div>`;
  return `<div class="purifier-controls">
    ${choices("fan_mode", "fan_modes", "data-fan-mode", "Mode", s.fan_mode)}
    ${choices("fan_speed", "fan_speeds", "data-fan-speed", "Fan speed", s.fan_mode === "manual" ? s.fan_speed : null)}
    <p class="control-help">Selecting a speed uses Manual mode. Selecting a mode or speed turns the purifier on.</p>
    <section><h3>Device readings</h3><div class="purifier-readings">
      ${d.caps.includes("air_quality") ? reading("PM2.5", s.pm25, "µg/m³") + reading("Air quality", s.air_quality) : ""}
      ${d.caps.includes("filter_life") ? reading("Filter life remaining", s.filter_life, "%") : ""}
    </div><p class="control-help">${s.on === false ? "Last reported values; the purifier is off." : "Reported by the purifier, refreshed periodically."}</p></section>
  </div>`;
}
