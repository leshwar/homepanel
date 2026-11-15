// The Home page's weather tile: what it's like now, and what the next hours bring.
//
//   small (1x1)   place, temperature, condition, today's high and low
//   wide  (2x1)   the same, plus four coming hours beside it
//   large (2x2)   the same, plus a line of the next 12 hours' temperature with the chance
//                 of rain under it, the four hours below, and one plain sentence about rain
//
// The moving sky behind it is weather-effects.js. Everything here is drawn from the neutral
// weather shape of GET /api/v1/weather; a reading without hours gives the small layout.

import { esc } from "./util.js";
import { weatherIcon } from "./clockfaces.js";
import { weatherBackdrop } from "./weather-effects.js";

const HOURS = 12;                       // the line covers this many coming hours
const COLUMNS = [1, 4, 7, 10];          // the hours spelled out under it: 2, 5, 8 and 11 hours from now

export const hourLabel = (hour, h24 = false) =>
  (h24 ? `${String(hour).padStart(2, "0")}:00` : `${hour % 12 || 12} ${hour < 12 ? "AM" : "PM"}`);

const WET = { drizzle: "Rain", rain: "Rain", snow: "Snow", storm: "Thunderstorms" };

// One plain sentence about rain or snow in the coming hours, or "" when there's nothing to say.
export function outlook(wx, h24 = false) {
  const hours = wx?.hours || [];
  if (!hours.length) return "";
  const at = (h) => hourLabel(h.hour, h24);
  if (WET[wx.condition]) {
    const dry = hours.find((h) => !WET[h.condition]);
    return dry ? `${WET[wx.condition]} until about ${at(dry)}` : `${WET[wx.condition]} for the next ${hours.length} hours`;
  }
  const wet = hours.find((h) => WET[h.condition]);
  if (wet) return `${WET[wet.condition]} around ${at(wet)}`;
  const peak = hours.reduce((a, h) => ((h.rain ?? 0) > (a.rain ?? 0) ? h : a));
  if ((peak.rain ?? 0) >= 40) return `${peak.rain}% chance of rain around ${at(peak)}`;
  return hours.length >= HOURS && hours.every((h) => Number.isFinite(h.rain) && h.rain <= 20) ? `Dry for the next ${hours.length} hours` : "";
}

// "Feels like" is only worth saying when it differs from the temperature by 3 degrees or more.
export const feelsLike = (wx) =>
  (Number.isFinite(wx?.feels_like) && Number.isFinite(wx?.temperature) && Math.abs(wx.feels_like - wx.temperature) >= 3 ? wx.feels_like : null);

// The temperature line: it starts at the left edge with the temperature now, then one point
// in the middle of each coming hour's slot, in a w × h box (y grows downward). A change of
// a degree or two stays a gentle slope: the scale never spans less than 6 degrees.
export function curve(now, hours, w = 240, h = 42, pad = 5) {
  const temps = [now, ...hours.map((x) => x.temperature)];
  const lo = Math.min(...temps), hi = Math.max(...temps);
  const span = Math.max(hi - lo, 6), base = (hi + lo) / 2 - span / 2;
  const r = (v) => +v.toFixed(1);
  const y = (t) => r(pad + (h - 2 * pad) * (1 - (t - base) / span));
  const pts = [[0, y(now)], ...hours.map((x, i) => [r(w * (i + 0.5) / hours.length), y(x.temperature)])];
  let d = `M${pts[0][0]} ${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {                    // a smooth line through every point
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    d += ` C${r(p1[0] + (p2[0] - p0[0]) / 6)} ${r(p1[1] + (p2[1] - p0[1]) / 6)} ${r(p2[0] - (p3[0] - p1[0]) / 6)} ${r(p2[1] - (p3[1] - p1[1]) / 6)} ${p2[0]} ${p2[1]}`;
  }
  return { d, pts };
}

function forecast(wx, h24) {
  const hours = (wx.hours || []).slice(0, HOURS);
  if (hours.length < HOURS || !Number.isFinite(wx.temperature)) return "";
  const W = 240, LINE = 40, BAND = 20, H = LINE + 2 + BAND;      // the line, then the chance of rain under it
  const { d, pts } = curve(wx.temperature, hours, W, LINE);     // a full bar is a 100% chance
  const slot = W / hours.length;
  const rain = hours.map((h, i) => ((h.rain ?? 0) >= 10
    ? `<rect x="${(i * slot + 1.5).toFixed(1)}" y="${(H - BAND * h.rain / 100).toFixed(1)}" width="${(slot - 3).toFixed(1)}" height="${(BAND * h.rain / 100).toFixed(1)}" rx="1.5"/>` : "")).join("");
  const dots = COLUMNS.map((i) => `<i style="left:${(pts[i + 1][0] / W * 100).toFixed(2)}%;top:${(pts[i + 1][1] / H * 100).toFixed(2)}%"></i>`).join("");
  const tell = outlook(wx, h24);
  return `${tell ? `<span class="wx-outlook">${esc(tell)}</span>` : ""}
      <div class="wx-chart" aria-hidden="true"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <path class="wx-line" d="${d}"/><g class="wx-rain">${rain}</g></svg>${dots}</div>
      <div class="wx-hours" role="list" aria-label="Coming hours">${COLUMNS.map((i) => {
        const h = hours[i];
        return `<span class="wx-hour" role="listitem" aria-label="${esc(hourLabel(h.hour, h24))}: ${esc(h.temperature)} degrees, ${esc(h.label.toLowerCase())}${
          Number.isFinite(h.rain) ? `, ${h.rain}% chance of rain` : ""}"><b>${esc(h.temperature)}°</b>${weatherIcon(h.condition, h.is_day)}<small>${esc(hourLabel(h.hour, h24))}</small></span>`;
      }).join("")}</div>`;
}

// The tile for a reading that's ready. `place` is the household's name for where it is.
export function weatherTile(wx, { place = "", h24 = false } = {}) {
  const feels = feelsLike(wx);
  const more = forecast(wx, h24);
  return `<div class="w-fill w-weather${more ? " has-hours" : ""}" data-weather-status="ready">${weatherBackdrop(wx)}
      <span class="w-label">${esc(place || "Weather")}</span>
      <span class="w-wx"><b>${esc(wx.temperature)}°</b></span>
      <span class="w-sub">${weatherIcon(wx.condition, wx.is_day)}<span>${esc(wx.label)}</span>${
        feels == null ? "" : `<span class="wx-feels">, feels like ${esc(feels)}°</span>`}</span>
      ${wx.high != null ? `<span class="wx-range">H ${esc(wx.high)}° L ${esc(wx.low)}°</span>` : ""}
      ${more}
    </div>`;
}
