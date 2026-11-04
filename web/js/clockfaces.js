// Resting clock faces: what the panel shows when nobody has touched it for a while
// (and when the home-screen clock is tapped). app.js decides when to show it; this
// file draws the chosen face and slowly drifts it around to avoid screen burn-in.
//
// Faces are sized in container units (cqmin/cqw), so the same markup draws both the
// full-screen clock and the small previews in Settings → Display and clock.

import { api } from "./api.js";
import { store } from "./store.js";
import { $, esc } from "./util.js";

export const FACES = [
  { id: "digital", name: "Big digital" },
  { id: "analog", name: "Analog" },
  { id: "words", name: "Word clock" },
  { id: "date", name: "Date and day" },
  { id: "night", name: "Dim night" },
];
export const DEFAULT_FACE = "digital";
export const faceId = (v) => (FACES.some((f) => f.id === v) ? v : DEFAULT_FACE);

// ---------- word clock ----------
const HOURS = ["twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven"];
const MINUTES = { 5: "five", 10: "ten", 15: "quarter", 20: "twenty", 25: "twenty-five", 30: "half" };

// "It's quarter past ten". Rounds to the nearest five minutes, like a word clock on a wall.
export function wordTime(hours, minutes) {
  let m = Math.round(minutes / 5) * 5;
  let h = hours;
  if (m === 60) { m = 0; h += 1; }
  h %= 24;
  if (m === 0) {
    if (h === 0) return "It's midnight";
    if (h === 12) return "It's noon";
    return `It's ${HOURS[h % 12]} o'clock`;
  }
  if (m <= 30) return `It's ${MINUTES[m]} past ${HOURS[h % 12]}`;
  return `It's ${MINUTES[60 - m]} to ${HOURS[(h + 1) % 12]}`;
}

// ---------- burn-in drift ----------
// A slow Lissajous path: about 37 minutes across and 53 minutes up and down, so the
// face never sits still on the same pixels. Returns an offset within ±free.
export function driftOffset(ms, freeX, freeY) {
  const turns = (ms / 60000) * 2 * Math.PI;
  return [Math.round(Math.sin(turns / 37) * freeX), Math.round(Math.sin(turns / 53 + 1) * freeY)];
}

// ---------- weather icons (drawn with strokes, no icon font) ----------
const CLOUD = `<path d="M7.5 17.5h9.3a3.6 3.6 0 0 0 .5-7.15A5.2 5.2 0 0 0 7.4 9.8a3.85 3.85 0 0 0 .1 7.7z"/>`;
const UP = (s) => `<g transform="translate(0 -3)">${s}</g>`;
const SUN = (cx, cy, r, ray) => `<circle cx="${cx}" cy="${cy}" r="${r}"/>` + Array.from({ length: 8 }, (_, i) => {
  const a = (i * Math.PI) / 4, c = Math.cos(a), s = Math.sin(a);
  const p = (d) => `${(cx + c * d).toFixed(2)} ${(cy + s * d).toFixed(2)}`;
  return `<path d="M${p(r + 2)}L${p(r + 2 + ray)}"/>`;
}).join("");
const MOON = (x = 0, y = 0) => `<path transform="translate(${x} ${y})" d="M15.8 4.6a7.6 7.6 0 1 0 3.6 13.1 6.2 6.2 0 0 1-3.6-13.1z"/>`;
const ICONS = {
  clear: (day) => (day ? SUN(12, 12, 4, 2.2) : MOON()),
  "partly-cloudy": (day) => (day ? `<g transform="translate(-1 -1) scale(.75)">${SUN(12, 12, 4, 2.2)}</g>`
    : `<g transform="translate(-1 -1) scale(.7)">${MOON()}</g>`) + `<g class="front" transform="translate(2 2) scale(.9)">${CLOUD}</g>`,
  cloudy: () => CLOUD,
  fog: () => `<path d="M4 9h16M6 13h12M4 17h16"/>`,
  drizzle: () => UP(CLOUD) + `<path d="M9 18.5v.01M13 20v.01M17 18.5v.01M11 21.5v.01"/>`,
  rain: () => UP(CLOUD) + `<path d="M9 17l-1 3M13 17l-1 3M17 17l-1 3"/>`,
  snow: () => UP(CLOUD) + `<path d="M9 18v3M7.5 19.5h3M15 18v3M13.5 19.5h3"/>`,
  storm: () => UP(CLOUD) + `<path d="M13 15l-2 3.5h3l-2 3.5"/>`,
};
export function weatherIcon(condition, isDay = true) {
  const draw = ICONS[condition] || ICONS.cloudy;
  return `<svg class="cf-wx-icon" viewBox="0 0 24 24" aria-hidden="true">${draw(isDay)}</svg>`;
}

// "54°" plus icon, label and place, for the faces that have room. Empty when there's nothing to show.
function wxRow(info, { highLow = false } = {}) {
  const w = info.weather;
  const place = info.place ? `<span class="cf-place">${esc(info.place)}</span>` : "";
  if (!w) return place ? `<div class="cf-wx">${place}</div>` : "";
  const hl = highLow && w.high != null ? `<span class="cf-hl">High ${w.high}° · Low ${w.low}°</span>` : "";
  return `<div class="cf-wx" data-condition="${esc(w.condition)}">${weatherIcon(w.condition, w.is_day)}
    <span class="cf-temp">${esc(w.temperature)}°</span><span class="cf-label">${esc(w.label)}</span>${hl}
    ${place ? `<span class="cf-dot">·</span>${place}` : ""}</div>`;
}

// ---------- drawing ----------
const fmtTime = (now, h24) => now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: !h24 })
  .replace(/\s?[AP]M$/i, "");
const fmtShort = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

function analogSVG(now) {
  const m = now.getMinutes() + now.getSeconds() / 60;
  const h = (now.getHours() % 12) + m / 60;
  const ticks = Array.from({ length: 12 }, (_, i) => {
    const major = i % 3 === 0;
    return `<line class="${major ? "major" : ""}" x1="0" y1="${major ? -86 : -90}" x2="0" y2="-96" transform="rotate(${i * 30})"/>`;
  }).join("");
  return `<svg class="cf-dial" viewBox="-100 -100 200 200" aria-hidden="true">
    <g class="cf-ticks">${ticks}</g>
    <line class="cf-hour" x1="0" y1="10" x2="0" y2="-50" transform="rotate(${(h * 30).toFixed(2)})"/>
    <line class="cf-min" x1="0" y1="14" x2="0" y2="-78" transform="rotate(${(m * 6).toFixed(2)})"/>
    <circle class="cf-pin" r="4"/></svg>`;
}

// HTML for one face. `info` = { h24, lightsOn, sun: {sunrise, sunset} | null, place: "",
// weather: {temperature, high, low, condition, label, is_day} | null }.
export function faceHTML(face, now, info = {}) {
  const time = fmtTime(now, info.h24);
  const date = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  const on = info.lightsOn || 0;
  const lights = on ? `${on} ${on === 1 ? "light is" : "lights are"} on` : "";
  switch (faceId(face)) {
    case "analog":
      return `<div class="cf cf-analog">${analogSVG(now)}<div class="cf-sub">${esc(date)}</div>${wxRow(info)}</div>`;
    case "words": {
      const [lead, ...rest] = wordTime(now.getHours(), now.getMinutes()).split(" ");
      return `<div class="cf cf-words"><div class="cf-phrase"><span class="cf-lead">${esc(lead)}</span> ${esc(rest.join(" "))}</div>
        <div class="cf-sub">${esc(date)}</div>${wxRow(info)}</div>`;
    }
    case "date": {
      const bits = [];
      if (info.sun?.sunrise) bits.push(`Sunrise ${fmtShort(info.sun.sunrise)}`, `Sunset ${fmtShort(info.sun.sunset)}`);
      if (lights) bits.push(lights[0].toUpperCase() + lights.slice(1));
      return `<div class="cf cf-date">
        ${info.place ? `<div class="cf-kicker">${esc(info.place)}</div>` : ""}
        <div class="cf-weekday">${esc(now.toLocaleDateString([], { weekday: "long" }))}</div>
        <div class="cf-day">${esc(now.toLocaleDateString([], { month: "long", day: "numeric" }))}</div>
        <div class="cf-time">${esc(time)}</div>
        ${wxRow({ ...info, place: "" }, { highLow: true })}
        ${bits.length ? `<div class="cf-sub">${bits.map(esc).join(" · ")}</div>` : ""}</div>`;
    }
    case "night":
      return `<div class="cf cf-night"><div class="cf-time">${esc(time)}</div>
        ${info.weather ? `<div class="cf-temp">${esc(info.weather.temperature)}°</div>` : ""}</div>`;
    default:
      return `<div class="cf cf-digital"><div class="cf-time">${esc(time)}</div>
        <div class="cf-sub">${esc(lights ? `${date}. ${lights}.` : date)}</div>${wxRow(info)}</div>`;
  }
}

// ---------- sunrise/sunset for the date face (fetched at most once a day) ----------
let sun = null;
let sunDay = "";
function refreshSun() {
  const today = new Date().toDateString();
  if (sunDay === today || store.settings.latitude == null) return;
  sunDay = today;
  api.sun().then((s) => { sun = s; renderAmbient(); }).catch(() => { sunDay = ""; });
}

// ---------- weather (the server fetches and caches it; we ask every 10 minutes) ----------
let weather = null;
let weatherKey = "";
let weatherAt = 0;
function refreshWeather() {
  const s = store.settings;
  if (!s.weather_enabled || s.latitude == null) { weather = null; weatherKey = ""; return; }
  const key = [s.latitude, s.longitude, s.temperature_unit].join();
  if (key === weatherKey && Date.now() - weatherAt < 10 * 60e3) return;
  if (key !== weatherKey) weather = null;
  weatherKey = key; weatherAt = Date.now();
  api.weather().then((w) => { weather = w?.available ? w : null; renderAmbient(); })
    .catch(() => { weather = null; });
}

export function faceInfo() {
  const s = store.settings;
  const lightsOn = [...store.devices.values()].filter((d) => d.kind === "light" && d.state?.on).length;
  return { h24: !!s.clock_24h, lightsOn, sun: s.latitude != null ? sun : null,
           place: s.place_name || "", weather: s.weather_enabled ? weather : null };
}

// Draw the resting clock (if it's showing) and nudge it along its drift path.
export function renderAmbient(now = new Date()) {
  const root = $("#ambient");
  const stage = $("#ambient-face");
  if (!root || !stage || root.hidden) return;
  const face = faceId(store.settings.clock_face);
  if (face === "date") refreshSun();
  refreshWeather();
  root.dataset.face = face;
  stage.innerHTML = faceHTML(face, now, faceInfo());
  const freeX = Math.max(0, (root.clientWidth - stage.offsetWidth) / 2 - 16);
  const freeY = Math.max(0, (root.clientHeight - stage.offsetHeight) / 2 - 16);
  const [x, y] = driftOffset(now.getTime(), Math.min(freeX, root.clientWidth * 0.2), Math.min(freeY, root.clientHeight * 0.2));
  stage.style.transform = `translate(${x}px, ${y}px)`;
}
