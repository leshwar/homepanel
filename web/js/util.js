// Small shared helpers: escaping, icons, colors, status text, toasts.

export const $ = (sel, root = document) => root.querySelector(sel);

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const icon = (name, cls = "") => `<svg class="i ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

export const KIND_ICON = { light: "bulb", plug: "plug", switch: "switch", tv: "tv", fan: "fan", purifier: "fan", speaker: "speaker", vacuum: "vacuum", other: "power" };
export const kindIcon = (d) => d.icon || KIND_ICON[d.kind] || "power";
// TVs and speakers share the media controls: volume, mute, inputs.
export const isMedia = (d) => d.kind === "tv" || d.kind === "speaker";

const LAMP = [242, 179, 91];
const JADE = [124, 199, 165];
const INDIGO = [150, 166, 255];
const EFFECT = [196, 120, 255];     // a light playing a scene or following music

export function kelvinToRgb(k) {
  const t = k / 100;
  const r = t <= 66 ? 255 : 329.7 * Math.pow(t - 60, -0.1332);
  const g = t <= 66 ? 99.47 * Math.log(t) - 161.12 : 288.12 * Math.pow(t - 60, -0.0755);
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.52 * Math.log(t - 10) - 305.04;
  const c = (v) => Math.max(0, Math.min(255, Math.round(v)));
  return [c(r), c(g), c(b)];
}

// The color a device "gives off" when it's on. Lights use their real color.
export function glow(d) {
  if (isMedia(d)) return INDIGO;
  if (d.kind !== "light") return JADE;
  const s = d.state || {};
  const part = s.color_mode === "segments" && (s.segments || []).find(Boolean);
  if (part) return [1, 3, 5].map((i) => parseInt(part.slice(i, i + 2), 16));
  if (s.color_mode === "effect" || s.color_mode === "music") return EFFECT;
  if (s.color_mode === "color" && s.color) {
    const { r, g, b } = s.color;
    const max = Math.max(r, g, b, 1);     // full-saturation version so dim colors still read
    return [r, g, b].map((v) => Math.round((v / max) * 255));
  }
  if (s.color_temp) {
    const w = kelvinToRgb(s.color_temp);
    return w.map((v, i) => Math.round(v * 0.55 + LAMP[i] * 0.45));
  }
  return LAMP;
}
export const glowVar = (d) => glow(d).join(" ");

const ACTIVITY_TEXT = { cleaning: "Cleaning", paused: "Paused", returning: "Going back to dock",
                        docked: "Docked", idle: "Ready", error: "Needs help" };

// A device that wants a person: it reports a problem, or a part is worn out.
// Generic state keys (problem, parts), so any brand can use it.
export const WORN_PERCENT = 10;
export const wornPart = (s = {}) => (s.parts || []).find((p) => p.percent <= WORN_PERCENT) || null;
// Resting = nothing more useful to say: not cleaning, not still charging.
const resting = (s) => !s.activity || (["docked", "idle"].includes(s.activity) && (s.battery == null || s.battery >= 100));
export const needsAttention = (d) => {
  const s = d?.state || {};
  return s.online !== false && !s.needs_pairing && !!(s.problem || (wornPart(s) && resting(s)));
};

// What a room's heading says: nothing to turn off is not the same as nothing there.
export const roomStatus = (total, on) => !total ? "No devices yet" : on ? `${on} of ${total} on` : "Everything is off";

export function vacuumText(s) {
  if (!s.activity) return "Connecting…";
  if (s.problem) return "Needs attention";
  if (resting(s) && wornPart(s)) return "Maintenance due";
  let t = ACTIVITY_TEXT[s.activity] || "Ready";
  if (s.activity === "docked" && s.battery != null && s.battery < 100) t = "Charging";
  return s.battery != null ? `${t}, ${s.battery}%` : t;
}

export function statusText(d, apps = []) {
  const s = d.state || {};
  if (s.needs_pairing) return "Needs pairing";
  if (s.online === false) return s.error ? "Offline" : "Offline";
  if (s.online == null && s.on == null && s.activity == null) return "Connecting…";
  if (d.kind === "vacuum") return vacuumText(s);
  if (!s.on) return "Off";
  if (d.kind === "purifier") {
    return (d.meta?.fan_modes || []).find(mode => mode.id === s.fan_mode)?.name || "On";
  }
  if (d.kind === "light") {
    const effect = s.color_mode === "effect" && (d.meta?.effects || []).find((e) => e.id === s.effect);
    const what = effect ? effect.name : s.color_mode === "music" ? "Music" : "On";
    if (s.brightness != null && d.caps.includes("brightness")) return `${what}, ${s.brightness}%`;
    if (what !== "On") return what;
  }
  if (isMedia(d)) {
    const app = (d.meta?.apps || apps).find((a) => a.id === s.app);
    const input = (d.meta?.inputs || []).find((x) => x.id === s.input);
    return app ? app.name : input ? input.name : "On";
  }
  if (s.power_w != null) return `On, ${s.power_w} W`;
  return "On";
}

let toastTimer;
export function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast${isError ? " error" : ""}`;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), isError ? 5000 : 2600);
}

// Calls fn at most every ms, with a trailing call for the latest arguments.
// .cancel() drops a pending trailing call (e.g. when the final value is sent).
export function throttle(fn, ms) {
  let last = 0, timer, lastArgs;
  const run = (...args) => {
    lastArgs = args;
    const now = Date.now();
    if (now - last >= ms) { last = now; fn(...args); }
    else { clearTimeout(timer); timer = setTimeout(() => { last = Date.now(); fn(...lastArgs); }, ms - (now - last)); }
  };
  run.cancel = () => clearTimeout(timer);
  return run;
}

export const storage = {
  get(k, fallback) { try { const v = localStorage.getItem(k); return v == null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode etc. */ } },
};
