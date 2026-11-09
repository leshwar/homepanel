// One private, decoded image stream shared by Photos widgets on this screen.
import { api } from "./api.js";
import { store, reload } from "./store.js";
import { esc } from "./util.js";

export function photoTile() {
  const source = store.settings.photo_library || {}, admin = store.me?.role === "admin";
  const message = source.ready ? "Loading photos..." : !source.configured ? "Connect a photo library in Settings."
    : !source.permitted ? "Photos are not shared with this profile." : "Choose an album in Settings.";
  return `<div class="w-photos w-fill" data-photo-tile data-photo-generation="${esc(source.generation || "")}">
    <img class="photo-layer" alt="Photo from a selected album"><img class="photo-layer" alt="">
    <span class="photo-caption">Photos</span>
    <div class="photo-placeholder"><p role="status">${message}</p>
      ${!source.ready && admin ? '<button class="btn small" data-photo-settings>Set up photos</button>' : ""}</div>
  </div>`;
}

export function watchPhotoTiles(root, editing) {
  const visible = new Map(), urls = new Set();
  let key = "", serial = 0, pending = null, timer = null, retire = null, current = null, token = "", front = 0, nextAt = 0, attemptedAt = 0;
  const active = () => !document.hidden && !root.hidden && !editing() && store.settings.photo_library?.ready
    && !document.querySelector("#settings:not([hidden]), #sheet:not([hidden]), #ambient:not([hidden]), #frame:not([hidden])")
    && [...visible.values()].some(Boolean);
  const stop = () => { clearTimeout(timer); timer = null; pending?.abort(); pending = null; serial++; };
  const clearImages = () => {
    clearTimeout(retire);
    for (const el of visible.keys()) {
      el.querySelectorAll("img").forEach(img => { img.removeAttribute("src"); img.classList.remove("visible"); });
    }
    for (const url of urls) URL.revokeObjectURL(url);
    urls.clear(); current = null; token = "";
    nextAt = Math.min(nextAt, attemptedAt + 5000);
  };
  const status = (message) => {
    for (const el of visible.keys()) {
      const box = el.querySelector(".photo-placeholder");
      box.hidden = !message;
      if (message) box.querySelector("[role=status]").textContent = message;
    }
  };
  const schedule = (seconds) => {
    clearTimeout(timer);
    nextAt = Date.now() + seconds * 1000;
    timer = active() ? setTimeout(next, seconds * 1000) : null;
  };
  async function next() {
    if (!active() || pending) return;
    const mine = ++serial, expectedKey = key, controller = new AbortController();
    pending = controller;
    attemptedAt = Date.now(); nextAt = attemptedAt + 5000;
    let url = null;
    try {
      const photo = await api.nextLibraryPhoto(controller.signal);
      if (mine !== serial || expectedKey !== key || !active()) return;
      if (photo.generation !== store.settings.photo_library?.generation) {
        clearImages(); status("The photo source changed. Reloading...");
        await reload();
        return;
      }
      if (photo.token !== token || !current) {
        url = URL.createObjectURL(photo.blob); urls.add(url);
        const decoded = new Image(); decoded.src = url; await decoded.decode();
        if (mine !== serial || expectedKey !== key || !active()) return;
        const old = current; current = url; token = photo.token; front = 1 - front;
        for (const el of visible.keys()) {
          const layers = el.querySelectorAll("img");
          layers[front].src = current;
          layers[front].classList.add("visible");
          layers[1 - front].classList.remove("visible");
        }
        url = null;
        clearTimeout(retire);
        retire = setTimeout(() => { if (old) { URL.revokeObjectURL(old); urls.delete(old); } }, 700);
      }
      status("");
    } catch (error) {
      if (mine !== serial || error.name === "AbortError") return;
      clearImages();
      status(error.message || "That photo could not be decoded.");
    } finally {
      if (url) { URL.revokeObjectURL(url); urls.delete(url); }
      if (mine === serial) { pending = null; schedule(Math.max(30, store.settings.photo_library?.seconds || 45)); }
    }
  }
  const run = () => {
    if (!active()) stop();
    else if (!pending && !timer) {
      if (nextAt > Date.now()) timer = setTimeout(() => { timer = null; next(); }, nextAt - Date.now());
      else next();
    }
  };
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) if (visible.has(entry.target)) visible.set(entry.target, entry.isIntersecting);
    run();
  });
  document.addEventListener("visibilitychange", run);
  for (const overlay of document.querySelectorAll("#settings, #sheet, #ambient, #frame")) {
    new MutationObserver(run).observe(overlay, { attributes: true, attributeFilter: ["hidden"] });
  }
  new MutationObserver(() => sync()).observe(root, { attributes: true, attributeFilter: ["hidden", "class"], childList: true });
  function sync() {
    const nextKey = `${store.me?.id || ""}:${store.settings.photo_library?.generation || ""}`;
    if (nextKey !== key) { stop(); clearImages(); nextAt = 0; key = nextKey; }
    const nodes = new Set(root.querySelectorAll("[data-photo-tile]"));
    for (const el of visible.keys()) if (!nodes.has(el)) { observer.unobserve(el); visible.delete(el); }
    for (const el of nodes) if (!visible.has(el)) {
      visible.set(el, false); observer.observe(el);
      if (current) { const image = el.querySelectorAll("img")[front]; image.src = current; image.classList.add("visible"); }
      if (current) el.querySelector(".photo-placeholder").hidden = true;
    }
    if (!nodes.size || !store.settings.photo_library?.ready) {
      stop(); clearImages();
      if (nodes.size) status(store.settings.photo_library?.configured
        ? "Choose an album and share it with this profile in Settings." : "Connect a photo library in Settings.");
    }
    run();
  }
  return sync;
}
