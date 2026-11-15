// One private, decoded image stream shared by Photos widgets on this screen.
import { api } from "./api.js";
import { store, reload, onChange } from "./store.js";
import { esc } from "./util.js";

export function photoTile() {
  const source = store.settings.photo_library || {}, admin = store.me?.role === "admin";
  const message = source.ready ? "Loading photos..." : !source.configured ? "Connect a photo library in Settings."
    : !source.permitted ? "Photos are not shared with this profile." : "Choose an album in Settings.";
  return `<div class="w-photos w-fill${source.ready ? "" : " empty"}" data-photo-tile data-photo-generation="${esc(source.generation || "")}">
    <img class="photo-layer" alt="Photo from a selected album"><img class="photo-layer" alt="">
    <a class="photo-link" data-photo-link target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer"
      aria-label="Open this photo in Immich (new tab)" hidden></a>
    <span class="photo-caption widget-heading">Photos</span>
    <div class="photo-placeholder"><p role="status">${message}</p>
      ${!source.ready && admin ? '<button class="btn small" data-photo-settings>Set up photos</button>' : ""}</div>
  </div>`;
}

export function watchPhotoTiles(root, editing) {
  const visible = new Map(), urls = new Set();
  const ambient=document.querySelector("#ambient"), idle=ambient?.querySelector("[data-idle-photo]");
  let key = "", serial = 0, pending = null, timer = null, retire = null, current = null, token = "", link = "", front = 0, nextAt = 0, attemptedAt = 0;
  let press=null, releaseTimer=null, transitioning=false;
  const idleActive=()=>ambient && !ambient.hidden && ambient.dataset.night!=="true";
  const active = () => !document.hidden && !editing() && !press && store.settings.photo_library?.ready
    && !document.querySelector("#settings:not([hidden]), #sheet:not([hidden]), #frame:not([hidden])")
    && (idleActive() || ((!ambient || ambient.hidden) && !root.hidden && [...visible].some(([el,shown])=>el!==idle&&shown)));
  const setLink=(el,value)=>{
    const anchor=el.querySelector("[data-photo-link]");
    if (!anchor) return;
    anchor.hidden=!value || editing() || transitioning;
    if (value && !editing() && !transitioning) anchor.href=value; else anchor.removeAttribute("href");
  };
  const safeLink=value=>{
    try {
      const url=new URL(value);
      return ["http:","https:"].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash
        && /\/photos\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(url.pathname) ? url.href : "";
    } catch { return ""; }
  };
  const stop = () => { clearTimeout(timer); timer = null; pending?.abort(); pending = null; serial++; };
  const clearImages = () => {
    clearTimeout(retire);
    for (const el of visible.keys()) {
      el.querySelectorAll("img").forEach(img => { img.removeAttribute("src"); img.classList.remove("visible"); });
      setLink(el,"");
    }
    for (const url of urls) URL.revokeObjectURL(url);
    urls.clear(); current = null; token = ""; link = ""; transitioning=false;
    if (ambient) delete ambient.dataset.photos;
    nextAt = Math.min(nextAt, attemptedAt + 5000);
  };
  const status = (message) => {
    for (const el of visible.keys()) {
      const box = el===idle ? ambient.querySelector("[data-idle-photo-status]") : el.querySelector(".photo-placeholder");
      if (!box) continue;
      box.hidden = !message;
      if (message) (el===idle ? box : box.querySelector("[role=status]")).textContent = message;
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
        const old = current; current = url; token = photo.token; link = safeLink(photo.link); front = 1 - front;
        transitioning=!!old && !matchMedia("(prefers-reduced-motion: reduce)").matches;
        for (const el of visible.keys()) {
          const layers = el.querySelectorAll("img");
          layers[front].src = current;
          layers[front].classList.add("visible");
          layers[1 - front].classList.remove("visible");
          setLink(el,link);
        }
        if (ambient) ambient.dataset.photos="true";
        url = null;
        clearTimeout(retire);
        retire = setTimeout(() => {
          if (old) { URL.revokeObjectURL(old); urls.delete(old); }
          transitioning=false;
          for (const el of visible.keys()) setLink(el,link);
        }, 700);
      }
      link=safeLink(photo.link);
      for (const el of visible.keys()) setLink(el,link);
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
    new MutationObserver(() => { sync(); run(); }).observe(overlay, { attributes: true, attributeFilter: ["hidden","data-night"] });
  }
  new MutationObserver(() => sync()).observe(root, { attributes: true, attributeFilter: ["hidden", "class"], childList: true });
  function sync() {
    const nextKey = `${store.me?.id || ""}:${store.settings.photo_library?.generation || ""}`;
    if (nextKey !== key) { stop(); clearImages(); if(press)press.cancelled=true; nextAt = 0; key = nextKey; }
    const nodes = new Set(root.querySelectorAll("[data-photo-tile]"));
    if (idle) nodes.add(idle);
    for (const el of visible.keys()) if (!nodes.has(el)) { observer.unobserve(el); visible.delete(el); }
    for (const el of nodes) if (!visible.has(el)) {
      visible.set(el, false); observer.observe(el);
      if (current) { const image = el.querySelectorAll("img")[front]; image.src = current; image.classList.add("visible"); }
      if (current && el!==idle) el.querySelector(".photo-placeholder").hidden = true;
    }
    for (const el of nodes) setLink(el,link);
    if (!nodes.size || !store.settings.photo_library?.ready) {
      stop(); clearImages();
      if (nodes.size) status(store.settings.photo_library?.configured
        ? "Choose an album and share it with this profile in Settings." : "Connect a photo library in Settings.");
    }
    run();
  }
  onChange(what=>{if(["all","view"].includes(what))sync();});
  const release=()=>{clearTimeout(releaseTimer);press=null;run();};
  root.addEventListener("pointerdown",e=>{
    const anchor=e.target.closest("[data-photo-link]");
    if (!anchor?.hasAttribute("href") || editing()) return;
    press={pointer:e.pointerId,x:e.clientX,y:e.clientY,key,link:anchor.href,cancelled:false};
    stop();
  });
  addEventListener("pointermove",e=>{
    if(press?.pointer===e.pointerId && Math.hypot(e.clientX-press.x,e.clientY-press.y)>10)press.cancelled=true;
  });
  for(const name of ["pointerup","pointercancel"]) addEventListener(name,e=>{
    if(press?.pointer!==e.pointerId)return;
    if(name==="pointercancel")press.cancelled=true;
    releaseTimer=setTimeout(release,350);
  });
  root.addEventListener("click",e=>{
    const anchor=e.target.closest("[data-photo-link]");
    if(!anchor)return;
    if(editing() || !anchor.hasAttribute("href") || (press&&(press.cancelled||press.key!==key||press.link!==anchor.href)))e.preventDefault();
    e.stopPropagation();
    setTimeout(release,0);
  });
  root.addEventListener("keydown",e=>{
    const anchor=e.target.closest("[data-photo-link]");
    if(!anchor || !["Enter"," "].includes(e.key) || !anchor.hasAttribute("href") || editing())return;
    press={key,link:anchor.href,cancelled:false};
    stop();
    if(e.key===" "){e.preventDefault();anchor.click();}
  });
  addEventListener("blur",release);
  return sync;
}
