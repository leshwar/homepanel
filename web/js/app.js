// Home screen: clock, scenes, room tabs and the device grid. Also wires up live
// updates and the idle ambient clock.

import { api, connectEvents } from "./api.js";
import { store, onChange, emit, reload, upsertDevice, command, setRoom, devicesIn } from "./store.js";
import { $, esc, icon, kindIcon, glowVar, statusText, toast } from "./util.js";
import { openDevice, refreshSheet, closeSheet, isSheetOpen } from "./sheet.js";
import { openSettings, isSettingsOpen, refreshSettings } from "./settings.js";

const SCENE_ICONS = ["sun", "moon", "film", "sparkle", "coffee", "door"];

// ---------- clock ----------
function renderClock() {
  const now = new Date();
  const h24 = !!store.settings.clock_24h;
  const time = now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: !h24 })
    .replace(/\s?[AP]M$/i, "");
  const date = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  $("#clock-time").textContent = time;
  $("#clock-sub").textContent = date;
  $("#ambient-time").textContent = time;
  const on = [...store.devices.values()].filter((d) => d.state?.on && d.kind === "light").length;
  $("#ambient-sub").textContent = on ? `${date}. ${on} ${on === 1 ? "light is" : "lights are"} on.` : date;
}

// ---------- scenes ----------
function renderScenes() {
  const el = $("#scenes");
  const items = store.scenes.map((s) =>
    `<button class="scene" data-scene="${esc(s.id)}">${icon(SCENE_ICONS.includes(s.icon) ? s.icon : "sparkle")}<span>${esc(s.name)}</span></button>`);
  if (store.devices.size) items.push(`<button class="scene add" data-new-scene>${icon("plus")}<span>New scene</span></button>`);
  el.innerHTML = items.join("");
  el.hidden = !items.length;
}

// ---------- rooms ----------
function renderRooms() {
  const rooms = store.rooms.filter((r) => devicesIn(r).length);
  const el = $("#rooms");
  if (rooms.length < 2) { el.hidden = true; if (store.room !== "all") setRoom("all"); return; }
  el.hidden = false;
  const onCount = (r) => devicesIn(r).filter((d) => d.state?.on).length;
  const tab = (id, label) => {
    const n = onCount(id);
    return `<button class="room" data-room="${esc(id)}" aria-pressed="${store.room === id}">${esc(label)}${
      n ? `<span class="count" aria-label="${n} on">${n}</span>` : ""}</button>`;
  };
  el.innerHTML = tab("all", "All") + rooms.map((r) => tab(r, r)).join("");
}

// ---------- tiles ----------
function tileHtml(d) {
  const s = d.state || {};
  const on = !!s.on && s.online !== false;
  const offline = s.online === false || s.needs_pairing;
  const level = d.kind === "light" && s.brightness ? Math.max(0.15, s.brightness / 100) : 1;
  const cls = ["tile", on && "on", offline && "offline", store.busy.has(d.id) && "busy", d.kind === "tv" && "wide"]
    .filter(Boolean).join(" ");
  const tvControls = d.kind === "tv" && on ? `
      <div class="tile-tv-ctl">
        <button data-act="volume_down" aria-label="Volume down">${icon("minus")}</button>
        <button data-act="volume_up" aria-label="Volume up">${icon("plus")}</button>
      </div>` : "";
  return `
    <div class="${cls}" data-id="${esc(d.id)}" role="button" tabindex="0"
         style="--glow:${glowVar(d)};--level:${level}"
         aria-label="${esc(d.name)}, ${esc(statusText(d))}">
      <div class="tile-icon">${icon(offline ? "wifi-off" : kindIcon(d))}</div>
      <button class="tile-more" data-more aria-label="${esc(d.name)} controls">${icon("right")}</button>
      <div class="tile-tv-row">
        <div>
          <div class="tile-name">${esc(d.name)}</div>
          <div class="tile-status">${esc(statusText(d))}</div>
        </div>
        ${tvControls}
      </div>
    </div>`;
}

function renderGrid() {
  const grid = $("#grid");
  if (!store.devices.size) {
    grid.innerHTML = `<div class="empty"><h2>Add your first device</h2>
      <p>Plugs, lights and TVs on your Wi-Fi show up here.</p>
      <button class="btn primary" data-add-device>${icon("plus")}Add a device</button></div>`;
    return;
  }
  const room = store.room;
  let html = "";
  if (room === "all") {
    const order = [...store.rooms, ""];
    for (const r of order) {
      const list = devicesIn(r === "" ? "" : r).filter((d) => (r === "" ? !store.rooms.includes(d.room) : true));
      if (!list.length) continue;
      html += `<div class="room-head">${esc(r || "Other")}</div>` + sortDevices(list).map(tileHtml).join("");
    }
  } else {
    html = sortDevices(devicesIn(room)).map(tileHtml).join("");
  }
  grid.innerHTML = html;
}

const KIND_ORDER = { tv: 0, light: 1, switch: 2, fan: 3, plug: 4, other: 5 };
const sortDevices = (list) => list.sort((a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || a.name.localeCompare(b.name));

function updateTile(id) {
  const d = store.devices.get(id);
  const old = document.querySelector(`.tile[data-id="${CSS.escape(id)}"]`);
  if (!d || !old) return renderGrid();
  const tmp = document.createElement("div");
  tmp.innerHTML = tileHtml(d);
  old.replaceWith(tmp.firstElementChild);
}

function renderAll() {
  renderClock();
  renderScenes();
  renderRooms();
  renderGrid();
}

// ---------- interactions ----------
function toggle(d) {
  if (d.state?.needs_pairing) return openDevice(d.id);
  if (d.state?.online === false) {
    toast(`${d.name} is offline. ${d.state.error || ""}`.trim(), true);
    return;
  }
  const on = !d.state?.on;
  command(d.id, "power", on, { on });
}

function setupGrid() {
  const grid = $("#grid");
  let pressTimer = null, longPressed = false;

  grid.addEventListener("pointerdown", (e) => {
    const tile = e.target.closest(".tile");
    if (!tile || e.target.closest("button")) return;
    longPressed = false;
    pressTimer = setTimeout(() => { longPressed = true; openDevice(tile.dataset.id); }, 480);
  });
  const cancel = () => clearTimeout(pressTimer);
  grid.addEventListener("pointerup", cancel);
  grid.addEventListener("pointerleave", cancel);
  grid.addEventListener("pointercancel", cancel);
  grid.addEventListener("contextmenu", (e) => e.preventDefault());

  grid.addEventListener("click", (e) => {
    if (e.target.closest("[data-add-device]")) return openSettings("add");
    const tile = e.target.closest(".tile");
    if (!tile) return;
    if (longPressed) { longPressed = false; return; }
    const d = store.devices.get(tile.dataset.id);
    if (!d) return;
    if (e.target.closest("[data-more]")) return openDevice(d.id);
    const act = e.target.closest("[data-act]");
    if (act) return command(d.id, act.dataset.act);
    if (d.kind === "tv") return openDevice(d.id);   // never toggle a TV by accident
    toggle(d);
  });
  grid.addEventListener("keydown", (e) => {
    const tile = e.target.closest(".tile");
    if (tile && e.target === tile && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); tile.click(); }
  });
}

function setupChrome() {
  $("#rooms").addEventListener("click", (e) => {
    const b = e.target.closest("[data-room]");
    if (b) setRoom(b.dataset.room);
  });
  $("#scenes").addEventListener("click", async (e) => {
    if (e.target.closest("[data-new-scene]")) return openSettings("scene-new");
    const b = e.target.closest("[data-scene]");
    if (!b) return;
    b.classList.add("running");
    try {
      const r = await api.runScene(b.dataset.scene);
      const name = store.scenes.find((s) => s.id === b.dataset.scene)?.name || "Scene";
      toast(r.failed.length ? `${name}: ${r.failed.length} device(s) didn't respond` : `${name} is on`, !!r.failed.length);
    } catch (err) { toast(err.message, true); }
    b.classList.remove("running");
  });
  $("#all-off").addEventListener("click", async () => {
    const room = store.room === "all" ? null : store.room;
    try {
      const r = await api.allOff(room);
      toast(r.turned_off ? `Turned off ${r.turned_off} ${r.turned_off === 1 ? "device" : "devices"}` : "Everything is already off");
    } catch (err) { toast(err.message, true); }
  });
  $("#open-settings").addEventListener("click", () => openSettings());
  $("#clock").addEventListener("click", showAmbient);
}

// ---------- idle ambient clock ----------
let lastActivity = Date.now();
function showAmbient() { closeSheet(); $("#ambient").hidden = false; }
function setupIdle() {
  const wake = () => { lastActivity = Date.now(); };
  ["pointerdown", "keydown"].forEach((ev) => document.addEventListener(ev, wake, { capture: true }));
  $("#ambient").addEventListener("pointerdown", (e) => {   // swallow the wake-up touch
    e.preventDefault(); e.stopPropagation();
    $("#ambient").hidden = true;
  });
  setInterval(() => {
    const after = Number(store.settings.dim_after_seconds || 0);
    if (after > 0 && Date.now() - lastActivity > after * 1000 && !isSettingsOpen() && $("#ambient").hidden) showAmbient();
  }, 5000);
}

// ---------- live updates ----------
function setupLive() {
  connectEvents((ev) => {
    if (ev.type === "device") upsertDevice(ev.device);
    else if (ev.type === "layout") reload().catch(() => {});
  }, (connected) => {
    $("#conn").hidden = connected;
    if (connected) reload().catch(() => {});
  });
}

onChange((what, id) => {
  if (what === "device") {
    updateTile(id);
    refreshSheet(id);
    renderRooms();
  } else if (what === "room") {
    renderRooms(); renderGrid();
  } else {
    renderAll();
    refreshSheet();
    refreshSettings();
  }
});

setupGrid();
setupChrome();
setupIdle();
setInterval(renderClock, 10_000);
reload().then(setupLive).catch((e) => { toast(e.message, true); setupLive(); });
