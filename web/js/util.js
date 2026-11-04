// Small shared helpers: escaping, icons, colors, status text, toasts.

export const $ = (sel, root = document) => root.querySelector(sel);

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const icon = (name, cls = "") => `<svg class="i ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

export const KIND_ICON = { light: "bulb", plug: "plug", switch: "switch", tv: "tv", fan: "fan", vacuum: "vacuum", other: "power" };
export const kindIcon = (d) => d.icon || KIND_ICON[d.kind] || "power";

const LAMP = [242, 179, 91];
const JADE = [124, 199, 165];
const INDIGO = [150, 166, 255];

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
  if (d.kind === "tv") return INDIGO;
  if (d.kind !== "light") return JADE;
  const s = d.state || {};
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

export function vacuumText(s) {
  if (!s.activity) return "Connecting…";
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
  if (d.kind === "light" && s.brightness != null && d.caps.includes("brightness")) return `On, ${s.brightness}%`;
  if (d.kind === "tv") {
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
