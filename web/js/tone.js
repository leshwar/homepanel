// Tiles that stand out from the background: light tiles on a dark background,
// dark tiles on a light one ("Tiles: Auto" in Settings → Display and clock), or
// always light / always dark.
//
// How bright the background is: for a wallpaper, the picture's own average
// brightness (measured when it loads, minus the "Darken" setting): the whole
// picture decides the tiles, its top band decides the text right on it (the page
// title sits there). The Sky, Ocean, Aurora and Night are dark (every sky gradient
// is deep blue or slate at the top). Sets html[data-tiles] to "light" or "dark", and
// html[data-tone] to the background's own tone, so text that sits right on the
// background (page title, room headings, the side rail) turns dark on a light one.

import { store } from "./store.js";

let wallLuma = null;       // {all, top} 0–1 for the wallpaper on screen; null = none measured yet

// Average perceived brightness of an image (0 = black, 1 = white), from a tiny copy:
// {all: the whole picture, top: its top quarter}.
export function measureLuma(img) {
  try {
    const n = 24;
    const c = document.createElement("canvas");
    c.width = c.height = n;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(img, 0, 0, n, n);
    const px = g.getImageData(0, 0, n, n).data;
    let all = 0, top = 0;
    for (let i = 0; i < px.length; i += 4) {
      const l = 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
      all += l;
      if (i / 4 < n * (n / 4)) top += l;        // first quarter of the rows
    }
    return { all: all / (n * n) / 255, top: top / (n * n / 4) / 255 };
  } catch {
    return null;              // couldn't read it: treat the background as dark
  }
}

export function setWallpaperLuma(l) { wallLuma = l; applyTiles(); }

// part: "all" (for the tiles) or "top" (for the page title and headings)
export function backgroundIsLight(s = store.settings, part = "all") {
  if ((s.background || "sky") !== "wallpaper" || !wallLuma) return false;   // sky, ocean, aurora, night: dark
  const dim = (Number(s.wallpaper_dim ?? 25) || 0) / 100;
  return wallLuma[part] * (1 - dim) > 0.5;
}

export function tilesFor(s = store.settings) {
  const style = s.tile_style || "auto";
  if (style === "light" || style === "dark") return style;
  return backgroundIsLight(s, "all") ? "dark" : "light";
}

let preview = null;           // Settings → Display: unsaved choices shown live
export function previewTiles(p) { preview = p; applyTiles(); }

export function applyTiles() {
  const s = preview ? { ...store.settings, ...preview } : store.settings;
  const root = document.documentElement;
  root.dataset.tiles = tilesFor(s);
  root.dataset.tone = backgroundIsLight(s, "top") ? "light" : "dark";
}
