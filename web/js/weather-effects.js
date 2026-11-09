// The page sky and tile share condition names, but their effects stay independent.
const SCENES = { clear: "clear", "partly-cloudy": "partly", cloudy: "cloudy", fog: "fog",
  drizzle: "rain", rain: "rain", snow: "snow", storm: "storm" };

export const weatherScene = (weather) => weather && Object.hasOwn(SCENES, weather.condition) ? SCENES[weather.condition] : null;

export function weatherBackdrop(weather) {
  const scene = weather?.available && weatherScene(weather);
  if (!scene) return "";
  const night = weather.is_day === false;
  const layer = (name) => `<span class="w-fx-${name}"></span>`;
  let layers = "";
  if (scene === "clear" || scene === "partly") layers += night ? layer("stars") + layer("moon") : layer("sun");
  if (scene !== "clear") layers += layer("clouds");
  if (scene === "rain" || scene === "storm") layers += layer("rain");
  if (scene === "snow") layers += layer("snow");
  if (scene === "fog") layers += layer("fog");
  if (scene === "storm") layers += layer("lightning");
  return `<div class="w-weather-fx" data-weather-scene="${scene}" data-weather-period="${night ? "night" : "day"}"
    data-active="false" aria-hidden="true">${layers}</div>`;
}

export function watchWeatherEffects(root) {
  const visible = new Map();
  const sync = () => {
    for (const [el, inView] of visible) el.dataset.active = String(inView && !document.hidden);
  };
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (visible.has(entry.target)) visible.set(entry.target, entry.isIntersecting);
    }
    sync();
  });
  document.addEventListener("visibilitychange", sync);
  return () => {
    const next = new Set(root.querySelectorAll(".w-weather-fx"));
    for (const el of visible.keys()) {
      if (!next.has(el)) { el.dataset.active = "false"; observer.unobserve(el); visible.delete(el); }
    }
    for (const el of next) {
      if (!visible.has(el)) { visible.set(el, false); observer.observe(el); }
    }
    sync();
  };
}
