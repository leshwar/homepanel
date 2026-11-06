// The "Wallpaper" background: the user's own pictures behind the glass.
//
// Settings (Settings → Display and clock): background = "wallpaper", wallpaper =
// an id or "shuffle", wallpaper_every = minutes per picture when shuffling (0 = a
// new one each time the page opens), wallpaper_dim = how much to darken (0–80 %).
//
// Shuffling prefers pictures shaped like the screen (portrait on a phone,
// landscape on the panel) and picks by time slot, so every screen in the house
// shows the same picture at the same time. Two layers cross-fade between pictures.

import { api } from "./api.js";
import { store } from "./store.js";

let list = null;          // [{id, url, width, height}], null = not loaded yet
let loadedAt = 0;
let loading = null;
let shown = "";           // url on screen
let front = 0;            // which of the two layers is on top
let timer = null;
const pageSeed = Math.random();

export function invalidateWallpapers() { list = null; }

async function wallpapers() {
  if (list && Date.now() - loadedAt < 10 * 60e3) return list;
  loading ||= api.wallpapers()
    .then((r) => { list = r.wallpapers || []; loadedAt = Date.now(); return list; })
    .catch(() => list || [])
    .finally(() => { loading = null; });
  return loading;
}

const portrait = () => innerHeight > innerWidth;
const fits = (w) => !w.width || !w.height || (w.height > w.width) === portrait();

// Small, stable number for a slot, so the same slot picks the same picture everywhere.
function slotIndex(slot, n) {
  let x = Math.imul(slot ^ 0x9e3779b9, 0x85ebca6b) >>> 0;
  x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
  return ((x ^ (x >>> 16)) >>> 0) % n;          // >>> 0: keep it positive
}

export function pickWallpaper(all, s = store.settings, now = Date.now()) {
  if (!all.length) return null;
  if (s.wallpaper && s.wallpaper !== "shuffle") {
    const fixed = all.find((w) => w.id === s.wallpaper);
    if (fixed) return fixed;
  }
  const pool = all.filter(fits).length ? all.filter(fits) : all;
  const sorted = [...pool].sort((a, b) => a.id.localeCompare(b.id));
  const every = Number(s.wallpaper_every) || 0;
  const slot = every > 0 ? Math.floor(now / (every * 60e3)) : Math.floor(pageSeed * 1e9);
  return sorted[slotIndex(slot, sorted.length)];
}

let preview = null;       // Settings → Display: unsaved choices shown live
export function previewWallpaper(p) { preview = p; return applyWallpaper(); }

export async function applyWallpaper() {
  const root = document.documentElement;
  const layers = document.querySelectorAll(".wall-layer .wp");
  const s = preview ? { ...store.settings, ...preview } : store.settings;
  const on = (s.background || "sky") === "wallpaper";
  clearTimeout(timer);
  if (!on || !layers.length) {
    root.classList.remove("has-wallpaper");
    return;
  }
  root.style.setProperty("--wall-dim", String((Number(s.wallpaper_dim ?? 25) || 0) / 100));
  const all = await wallpapers();
  const w = pickWallpaper(all, s);
  root.classList.toggle("has-wallpaper", !!w);   // none added yet: the plain night backdrop shows
  if (w && w.url !== shown) {
    const img = new Image();
    img.onload = () => {
      if (document.documentElement.dataset.bg !== "wallpaper") return;
      front = 1 - front;
      layers[front].style.backgroundImage = `url("${w.url}")`;
      layers[front].classList.add("show");
      layers[1 - front].classList.remove("show");
      shown = w.url;
    };
    img.src = w.url;
  }
  timer = setTimeout(applyWallpaper, 60e3);      // checks for the next slot once a minute
}

let resizeTimer = null;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(applyWallpaper, 400);  // turning a phone or tablet: pick a picture that fits
});
