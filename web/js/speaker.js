// Capability-driven controls for speakers without a TV remote/transport.
import { store, command } from "./store.js";
import { esc, icon } from "./util.js";
import { bindRelativeRange } from "./device-controls.js";

const has = (d, cap) => d.caps.includes(cap);
export const simpleSpeaker = (d) => d.kind === "speaker" && !has(d, "remote") && !has(d, "media")
  && !(has(d, "apps") && d.meta?.apps?.length);
const clamp = (n) => Math.max(0, Math.min(100, Math.round(n)));
let interaction = null, choosing = null;
const openSelectSupported = CSS.supports("selector(select:open)");
export const speakerBusy = () => !!interaction || (openSelectSupported
  ? !!document.querySelector("#sheet [data-speaker-select]:open")
  : choosing !== null && document.activeElement === choosing);
export function clearSpeakerInteraction() { interaction = null; choosing = null; }

export function speakerTop(d) {
  const s = d.state || {};
  const status = s.needs_pairing ? "Needs pairing" : s.online === false ? "Offline"
    : s.on === true ? (s.muted ? "On · muted" : "On") : s.on === false ? "Standby"
      : s.online === true ? "Connected" : "Connecting...";
  return `<div class="speaker-head">
    <div><h2 id="speaker-title">${esc(d.name)}</h2><p role="status">${esc(status)}</p></div>
    <button class="icon-btn" data-close aria-label="Close speaker controls">${icon("close")}</button>
  </div>`;
}

function choices(label, action, options, current, { advanced = false, hint = "", emptyMessage = "No selectable options have been reported by the speaker." } = {}) {
  const selected = options.find((o) => String(o.id) === String(current));
  const placeholder = current != null ? `Current: device-reported ${current}` : "Not reported";
  return `<div class="speaker-section">
    <label class="field"><span>${label}</span>
      <select data-speaker-select="${action}" aria-label="${label}" ${!options.length ? "disabled" : ""}>
        ${selected ? "" : `<option value="" selected disabled>${esc(placeholder)}</option>`}
        ${options.map((o) => `<option value="${esc(o.id)}" ${String(o.id) === String(current) ? "selected" : ""}>${
          esc(advanced ? `${o.name} · ID ${o.id}` : o.name)}</option>`).join("")}
      </select>
    </label>${hint ? `<p class="speaker-help">${esc(hint)}</p>` : ""}
    ${!options.length ? `<p class="speaker-help">${esc(emptyMessage)}</p>` : ""}
  </div>`;
}

export function speakerBody(d) {
  const s = d.state || {}, powerKnown = typeof s.on === "boolean", muteKnown = typeof s.muted === "boolean";
  const enabled = s.online !== false && !s.needs_pairing && (!has(d, "power") || s.on === true);
  const level = Number.isFinite(s.volume) ? clamp(s.volume) : null;
  const toggle = (attr, title, state, action, glyph, pressed, disabled = false) => `
    <button class="speaker-toggle" ${attr} aria-pressed="${pressed}" ${disabled ? "disabled" : ""}>
      ${icon(glyph)}<span><b>${title}: ${state}</b><small>${action}</small></span>
    </button>`;
  const power = has(d, "power") ? toggle("data-power", "Power", powerKnown ? s.on ? "On" : "Off" : "Unknown",
    powerKnown ? s.on ? "Turn off" : "Turn on" : "Waiting for the speaker", "power", !!s.on, !powerKnown) : "";
  const mute = has(d, "mute") ? toggle("data-mute", "Mute", muteKnown ? s.muted ? "On" : "Off" : "Unknown",
    s.muted ? "Unmute" : "Mute audio", s.muted ? "mute" : "vol", !!s.muted, !enabled || !muteKnown) : "";
  const step = (action, glyph, label) => `<button class="speaker-volume-step" data-act="${action}" data-repeat
    aria-label="${label}" ${enabled ? "" : "disabled"}>${icon(glyph)}</button>`;
  const volume = has(d, "volume") || has(d, "volume_level") ? `<section class="speaker-section speaker-volume">
    <div class="speaker-volume-title"><h3>Volume</h3><output data-speaker-level>${level == null ? "Not reported" : `${level}%`}</output></div>
    <div class="speaker-volume-row">${has(d, "volume") ? step("volume_down", "minus", "Volume down") : ""}
      ${has(d, "volume_level") && level != null ? `<input type="range" data-speaker-volume min="0" max="100" step="1"
        value="${level}" aria-label="Volume" aria-valuetext="${level}%" ${enabled ? "" : "disabled"}>` : ""}
      ${has(d, "volume") ? step("volume_up", "plus", "Volume up") : ""}
    </div><p class="speaker-help">${!enabled ? "Turn the speaker on to adjust the volume."
      : has(d, "volume_level") && level != null ? "Drag to adjust; release to apply. Tapping the track will not jump the volume."
      : "Use the volume buttons; a direct level is not available."}</p>
  </section>` : `<p class="speaker-help">Volume control is not available for this device.</p>`;
  const modes = has(d, "sound_mode") ? d.meta?.sound_modes || [] : [];
  const regular = modes.filter((m) => !m.advanced), advanced = modes.filter((m) => m.advanced);
  const input = has(d, "inputs") ? choices("Input", "set_input", d.meta?.inputs || [], s.input,
    { hint: "Choose the audio connection. Start music in the playback app." }) : "";
  const sound = has(d, "sound_mode") ? choices("Sound mode", "set_sound_mode", regular, s.sound_mode,
    { hint: "Changes how audio sounds, not what is playing.",
      emptyMessage: advanced.length ? "No standard presets are named. See device-reported modes below." : undefined }) : "";
  const extra = advanced.length ? `<details class="speaker-advanced"><summary>Device-reported modes</summary>
    <p class="speaker-help">These are reported by the speaker, not verified ordinary EQ presets. Some depend on the input or audio format; undocumented IDs keep their original numbers.</p>
    ${choices("Advanced sound mode", "set_sound_mode_advanced", advanced, s.sound_mode, { advanced: true })}</details>` : "";
  return `<div class="speaker-controls"><div class="speaker-toggles">${power}${mute}</div>${volume}
    ${(!powerKnown && has(d, "power")) || (level == null && has(d, "volume_level"))
      ? '<button class="btn small" data-refresh>Refresh status</button>' : ""}
    ${input || sound || extra ? `<details class="control-section" data-control-section="speaker-options">
      <summary>${input && sound ? "Input and sound" : input ? "Input" : "Sound mode"}</summary><fieldset class="speaker-options" ${enabled ? "" : "disabled"}>${input}${sound}${extra}</fieldset>
    </details>` : ""}
    ${d.meta?.playback_help ? `<p class="speaker-playback">${esc(d.meta.playback_help)}</p>` : ""}
  </div>`;
}

export function attachSpeaker(root, d, onIdle) {
  const latest = () => store.devices.get(d.id)?.state || d.state || {};
  const show = (value) => {
    const output = root.querySelector("[data-speaker-level]");
    if (output) output.textContent = `${value}%`;
    const range = root.querySelector("[data-speaker-volume]");
    if (range) { range.value = value; range.setAttribute("aria-valuetext", `${value}%`); }
  };
  const send = async (action, value, optimistic, focus, disable) => {
    const ticket = { kind: "command" };
    interaction = ticket;
    if (disable) disable.disabled = true;
    await command(d.id, action, value, optimistic);
    if (interaction !== ticket) return;
    interaction = null;
    onIdle();
    if (focus && !root.hidden && !root.classList.contains("closing") && root.dataset.deviceId === d.id) {
      root.querySelector(focus)?.focus({ preventScroll: true });
    }
  };
  const range = root.querySelector("[data-speaker-volume]");
  if (range) {
    bindRelativeRange(range, {
      value: () => clamp(latest().volume ?? Number(range.value)), preview: show,
      commit: value => send("volume", value, { volume: value }, "[data-speaker-volume]"), idle: onIdle,
    });
  }
  root.querySelectorAll("[data-speaker-select]").forEach((select) => {
    select.addEventListener("pointerdown", () => { choosing = select; });
    select.addEventListener("keydown", (e) => {
      choosing = ["Escape", "Tab"].includes(e.key) ? null : select;
      if (e.key === "Escape") { e.stopPropagation(); setTimeout(onIdle, 0); }
    });
    select.addEventListener("blur", () => { if (choosing === select) choosing = null; queueMicrotask(onIdle); });
    select.addEventListener("change", () => {
      choosing = null;
      if (!select.value) return;
      const action = select.dataset.speakerSelect === "set_input" ? "set_input" : "set_sound_mode";
      const value = select.value, focused = document.activeElement === select;
      send(action, value, action === "set_input" ? { input: value, app: null } : { sound_mode: value },
        focused ? `[data-speaker-select="${select.dataset.speakerSelect}"]` : null, select);
    });
  });
}
