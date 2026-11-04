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

// HTML for one face. `info` = { h24, lightsOn, sun: {sunrise, sunset} | null }.
export function faceHTML(face, now, info = {}) {
  const time = fmtTime(now, info.h24);
  const date = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  const on = info.lightsOn || 0;
  const lights = on ? `${on} ${on === 1 ? "light is" : "lights are"} on` : "";
  switch (faceId(face)) {
    case "analog":
      return `<div class="cf cf-analog">${analogSVG(now)}<div class="cf-sub">${esc(date)}</div></div>`;
    case "words": {
      const [lead, ...rest] = wordTime(now.getHours(), now.getMinutes()).split(" ");
      return `<div class="cf cf-words"><div class="cf-phrase"><span class="cf-lead">${esc(lead)}</span> ${esc(rest.join(" "))}</div>
        <div class="cf-sub">${esc(date)}</div></div>`;
    }
    case "date": {
      const bits = [];
      if (info.sun?.sunrise) bits.push(`Sunrise ${fmtShort(info.sun.sunrise)}`, `Sunset ${fmtShort(info.sun.sunset)}`);
      if (lights) bits.push(lights[0].toUpperCase() + lights.slice(1));
      return `<div class="cf cf-date">
        <div class="cf-weekday">${esc(now.toLocaleDateString([], { weekday: "long" }))}</div>
        <div class="cf-day">${esc(now.toLocaleDateString([], { month: "long", day: "numeric" }))}</div>
        <div class="cf-time">${esc(time)}</div>
        ${bits.length ? `<div class="cf-sub">${bits.map(esc).join(" · ")}</div>` : ""}</div>`;
    }
    case "night":
      return `<div class="cf cf-night"><div class="cf-time">${esc(time)}</div></div>`;
    default:
      return `<div class="cf cf-digital"><div class="cf-time">${esc(time)}</div>
        <div class="cf-sub">${esc(lights ? `${date}. ${lights}.` : date)}</div></div>`;
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

export function faceInfo() {
  const lightsOn = [...store.devices.values()].filter((d) => d.kind === "light" && d.state?.on).length;
  return { h24: !!store.settings.clock_24h, lightsOn, sun: store.settings.latitude != null ? sun : null };
}

// Draw the resting clock (if it's showing) and nudge it along its drift path.
export function renderAmbient(now = new Date()) {
  const root = $("#ambient");
  const stage = $("#ambient-face");
  if (!root || !stage || root.hidden) return;
  const face = faceId(store.settings.clock_face);
  if (face === "date") refreshSun();
  root.dataset.face = face;
  stage.innerHTML = faceHTML(face, now, faceInfo());
  const freeX = Math.max(0, (root.clientWidth - stage.offsetWidth) / 2 - 16);
  const freeY = Math.max(0, (root.clientHeight - stage.offsetHeight) / 2 - 16);
  const [x, y] = driftOffset(now.getTime(), Math.min(freeX, root.clientWidth * 0.2), Math.min(freeY, root.clientHeight * 0.2));
  stage.style.transform = `translate(${x}px, ${y}px)`;
}
