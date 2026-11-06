// The "Sky" background: follows the weather outside and the time of day.
//
// Weather comes from the panel's own server (GET /api/v1/weather, fetched and
// cached there), and only when it's turned on in Settings → Location and presence.
// Without weather the sky still follows the time of day.
//
// Sets html[data-sky] (clear, partly, cloudy, fog, rain, snow, storm) and
// html[data-period] (dawn, day, dusk, night); app.css draws the gradients and the
// slow moving clouds, rain, snow and stars (paused for "reduce motion").

import { api } from "./api.js";
import { store } from "./store.js";
import { applyTiles } from "./tone.js";

let weather = null;
let key = "";
let fetchedAt = 0;
const listeners = new Set();

export const onWeather = (fn) => listeners.add(fn);
export const currentWeather = () => weather;

export function refreshWeather(force = false) {
  const s = store.settings;
  if (!s.weather_enabled || s.latitude == null) {
    key = "";
    if (weather) { weather = null; changed(); }
    return;
  }
  const k = [s.latitude, s.longitude, s.temperature_unit].join();
  if (!force && k === key && Date.now() - fetchedAt < 10 * 60e3) return;
  key = k;
  fetchedAt = Date.now();
  api.weather()
    .then((w) => { weather = w?.available ? w : null; changed(); })
    .catch(() => { /* the server already logged it; keep the last reading */ });
}

function changed() {
  applySky();
  listeners.forEach((fn) => fn(weather));
}

const SKY = { clear: "clear", "partly-cloudy": "partly", cloudy: "cloudy", fog: "fog",
              drizzle: "rain", rain: "rain", snow: "snow", storm: "storm" };

// dawn 5–7:30, day, dusk 17:30–20, night. The weather's own day/night flag wins
// in between (it knows the real sunset for the place).
export function periodAt(now = new Date(), w = weather) {
  const h = now.getHours() + now.getMinutes() / 60;
  if (h >= 5 && h < 7.5) return "dawn";
  if (h >= 17.5 && h < 20) return "dusk";
  if (w && typeof w.is_day === "boolean") return w.is_day ? "day" : "night";
  return h >= 7.5 && h < 17.5 ? "day" : "night";
}

export const skyAt = (w = weather) => (w && SKY[w.condition]) || "clear";

export function applySky(now = new Date()) {
  const root = document.documentElement;
  root.dataset.sky = skyAt();
  root.dataset.period = periodAt(now);
  applyTiles();                       // keep the tiles in step with the background
}
