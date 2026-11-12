// The panel for a plain speaker or sound bar (no TV remote or transport keys).
// Stage: a volume dial with the level in the middle, a release-to-apply slider under it,
// and mute. Tabs: Input and Sound mode, as chips.
import { store, command } from "./store.js";
import { esc, icon } from "./util.js";
import { bindRelativeRange } from "./device-controls.js";
import { chipChoices } from "./panel.js";

const has = (d, cap) => d.caps.includes(cap);
export const simpleSpeaker = (d) => d.kind === "speaker" && !has(d, "remote") && !has(d, "media")
  && !(has(d, "apps") && d.meta?.apps?.length);
const clamp = (n) => Math.max(0, Math.min(100, Math.round(n)));
let interaction = null;
export const speakerBusy = () => !!interaction;
export function clearSpeakerInteraction() { interaction = null; }

export function speakerPanel(d) {
  const s = d.state || {};
  const enabled = s.online !== false && !s.needs_pairing && (!has(d, "power") || s.on === true);
  const level = Number.isFinite(s.volume) ? clamp(s.volume) : null;
  const off = enabled ? "" : "disabled";
  const step = (action, glyph, label) => (has(d, "volume") ? `<button class="rkey bare" data-act="${action}" data-repeat
    aria-label="${label}" ${off}>${icon(glyph)}</button>` : "");
  const canSet = has(d, "volume_level") && level != null;
  const stage = has(d, "volume") || has(d, "volume_level") ? `<div class="speaker-stage ${enabled ? "" : "idle"}">
      <div class="dial" style="--pct:${level ?? 0}" role="img" aria-label="Volume ${level == null ? "not reported" : `${level}%`}">
        <div class="dial-core"><output data-speaker-level>${level ?? "–"}</output><span>${s.muted === true ? "Muted" : "Volume"}</span></div>
      </div>
      <div class="dial-row">${step("volume_down", "minus", "Volume down")}
        ${canSet ? `<input type="range" class="level-range" data-speaker-volume min="0" max="100" step="1" value="${level}"
          aria-label="Volume" aria-valuetext="${level}%" ${off}>` : "<span></span>"}
        ${step("volume_up", "plus", "Volume up")}</div>
      ${has(d, "mute") && typeof s.muted === "boolean" ? `<button class="chip mute-chip" data-mute aria-pressed="${s.muted}" ${off}>
        ${icon(s.muted ? "mute" : "vol")}<span>${s.muted ? "Unmute" : "Mute"}</span></button>` : ""}
      ${!enabled && has(d, "power") && s.on === false ? `<p class="stage-hint">Turn it on to change the volume.</p>` : ""}
      ${level == null && has(d, "volume_level") ? `<button class="btn small" data-refresh>Refresh status</button>` : ""}
    </div>` : "";

  const inputs = has(d, "inputs") ? d.meta?.inputs || [] : [];
  const modes = has(d, "sound_mode") ? d.meta?.sound_modes || [] : [];
  const regular = modes.filter((m) => !m.advanced);
  // Modes the speaker lists by number only: shown apart, with their ids, so nobody takes them for presets.
  const reported = modes.filter((m) => m.advanced).map((m) => ({ id: m.id, name: `${m.name} · ID ${m.id}` }));
  const pane = (html) => `<fieldset class="pane-set" ${off}>${html}</fieldset>`;
  const tabs = [
    inputs.length && { id: "input", label: "Input", html: pane(`${chipChoices(inputs, s.input, "data-input", { glyph: "input", label: "Input" })}
      ${d.meta?.playback_help ? `<p class="pane-help">${esc(d.meta.playback_help)}</p>` : ""}`) },
    modes.length && { id: "sound", label: "Sound mode", html: pane(`${chipChoices(regular, s.sound_mode, "data-sound-mode", { label: "Sound mode" })}
      ${reported.length ? `<p class="pane-label">Reported by the speaker</p>
        ${chipChoices(reported, s.sound_mode, "data-sound-mode", { label: "Device-reported sound modes" })}
        <p class="pane-help">These depend on the input and audio format, and may not do anything.</p>` : ""}`) },
  ].filter(Boolean);
  return { stage, tabs };
}

export function attachSpeaker(root, d, onIdle) {
  const range = root.querySelector("[data-speaker-volume]");
  if (!range) return;
  const latest = () => store.devices.get(d.id)?.state || d.state || {};
  const show = (value) => {
    const output = root.querySelector("[data-speaker-level]");
    if (output) output.textContent = value;
    root.querySelector(".dial")?.style.setProperty("--pct", value);
    range.value = value;
    range.setAttribute("aria-valuetext", `${value}%`);
  };
  bindRelativeRange(range, {
    value: () => clamp(latest().volume ?? Number(range.value)), preview: show, idle: onIdle,
    commit: async (value) => {
      const ticket = {};
      interaction = ticket;                 // hold redraws until the speaker has answered
      await command(d.id, "volume", value, { volume: value });
      if (interaction !== ticket) return;
      interaction = null;
      onIdle();
      if (!root.hidden && !root.classList.contains("closing") && root.dataset.deviceId === d.id) {
        root.querySelector("[data-speaker-volume]")?.focus({ preventScroll: true });
      }
    },
  });
}
