// Photo frame: a full-screen slideshow of the photos in data/photos.
// Two stacked <img> layers crossfade; each photo drifts slowly (off when the
// person prefers reduced motion). Any touch exits — and that touch is swallowed,
// so it never presses a tile underneath.

import { api } from "./api.js";
import { store } from "./store.js";
import { $, esc, toast } from "./util.js";

let photos = [];
let order = [];
let index = 0;
let timer = null;
let clockTimer = null;
let front = 0;

export const isFrameOpen = () => !$("#frame").hidden;

function shuffle(list) {
  const a = [...list];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function tickClock() {
  const s = store.settings;
  const now = new Date();
  $("#frame-time").textContent = now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: !s.clock_24h })
    .replace(/\s?[AP]M$/i, "");
  $("#frame-date").textContent = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
}

function load(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(url);
    img.onerror = reject;
    img.src = url;
  });
}

async function showNext() {
  if (!isFrameOpen() || !order.length) return;
  const photo = order[index % order.length];
  index += 1;
  if (index % order.length === 0 && store.settings.frame_shuffle !== false) order = shuffle(photos);
  try {
    await load(photo.url);                       // decode before swapping so the fade is smooth
  } catch {
    return schedule(1000);                       // skip a photo that won't load
  }
  if (!isFrameOpen()) return;
  const layers = document.querySelectorAll(".frame-photo");
  const next = layers[1 - front];
  next.style.backgroundImage = `url("${photo.url}")`;
  next.style.setProperty("--drift-x", `${(Math.random() * 4 - 2).toFixed(2)}%`);
  next.style.setProperty("--drift-y", `${(Math.random() * 4 - 2).toFixed(2)}%`);
  next.classList.remove("drift");
  void next.offsetWidth;                         // restart the drift animation
  next.classList.add("drift", "visible");
  layers[front].classList.remove("visible");
  front = 1 - front;
  schedule();
}

function schedule(ms) {
  clearTimeout(timer);
  const seconds = Number(store.settings.frame_seconds || 15);
  document.documentElement.style.setProperty("--frame-seconds", `${seconds + 2}s`);
  timer = setTimeout(showNext, ms ?? seconds * 1000);
}

export async function openFrame() {
  let list;
  try {
    list = (await api.photos()).photos;
  } catch (e) {
    return toast(e.message, true);
  }
  const frame = $("#frame");
  frame.hidden = false;
  frame.querySelectorAll(".frame-photo").forEach((l) => { l.classList.remove("visible"); l.style.backgroundImage = ""; });
  $("#frame-empty").hidden = list.length > 0;
  $("#frame-empty").innerHTML = frameEmptyHtml();
  $("#frame-clock").hidden = store.settings.frame_clock === false;
  const hint = $("#frame-hint");
  hint.classList.add("show");
  setTimeout(() => hint.classList.remove("show"), 3000);
  tickClock();
  clearInterval(clockTimer);
  clockTimer = setInterval(tickClock, 10_000);
  photos = list;
  order = store.settings.frame_shuffle === false ? [...list] : shuffle(list);
  index = 0;
  if (list.length) showNext();
}

export function closeFrame() {
  clearTimeout(timer);
  clearInterval(clockTimer);
  $("#frame").hidden = true;
}

// Any touch, click or key exits — and the touch doesn't reach the tiles underneath.
const frame = $("#frame");
frame.addEventListener("pointerdown", (e) => { e.preventDefault(); e.stopPropagation(); closeFrame(); });
frame.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); });
document.addEventListener("keydown", (e) => { if (isFrameOpen()) { e.preventDefault(); closeFrame(); } }, true);

// Keep the list fresh while running (photos added from a phone appear without restarting).
setInterval(async () => {
  if (!isFrameOpen()) return;
  try {
    const list = (await api.photos()).photos;
    if (list.length !== photos.length) {
      const known = new Set(photos.map((p) => p.id));
      photos = list;
      order = [...order.filter((p) => list.some((x) => x.id === p.id)), ...list.filter((p) => !known.has(p.id))];
      $("#frame-empty").hidden = list.length > 0;
      if (list.length && !timer) showNext();
    }
  } catch { /* server briefly unreachable */ }
}, 60_000);

const frameEmptyHtml = () => `<div>
  <h2>No photos yet</h2>
  <p>Add photos from your phone: open ${esc(location.host)} in its browser, then Settings → Photo frame → Add photos.</p>
  <p class="frame-tap">Tap to go back</p></div>`;
