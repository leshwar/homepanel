// Air purifier panel. Stage: what the purifier reports (air quality, filter).
// Tabs: Mode and Fan speed. Uses generic capability metadata, never a brand protocol.
import { esc } from "./util.js";
import { powerHero, chipChoices } from "./panel.js";

export function purifierPanel(d) {
  const s = d.state || {};
  const reading = (label, value, unit = "") => `<div><span>${label}</span>
    <b>${value == null ? "Not reported" : esc(value)}</b>${value != null && unit ? `<small>${unit}</small>` : ""}</div>`;
  const readings = [
    d.caps.includes("air_quality") && reading("PM2.5", s.pm25, "µg/m³") + reading("Air quality", s.air_quality),
    d.caps.includes("filter_life") && reading("Filter life left", s.filter_life, "%"),
  ].filter(Boolean).join("");
  const stage = readings ? `<div class="purifier-stage"><div class="purifier-readings">${readings}</div>
      ${s.on === false ? `<p class="stage-hint">Last readings; the purifier is off.</p>` : ""}</div>`
    : d.caps.includes("power") ? powerHero(d) : "";
  // A mode or speed only counts as "current" while the purifier is running.
  const current = (value) => (s.on === true ? value : null);
  const tabs = [
    d.caps.includes("fan_mode") && { id: "mode", label: "Mode",
      html: chipChoices(d.meta?.fan_modes || [], current(s.fan_mode), "data-fan-mode", { label: "Mode" }) },
    d.caps.includes("fan_speed") && { id: "speed", label: "Fan speed",
      html: `${chipChoices(d.meta?.fan_speeds || [], current(s.fan_mode === "manual" ? s.fan_speed : null), "data-fan-speed", { label: "Fan speed" })}
        <p class="pane-help">Picking a speed switches to Manual mode and turns the purifier on.</p>` },
  ].filter(Boolean);
  return { stage, tabs };
}
