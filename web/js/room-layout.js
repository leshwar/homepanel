// Room tile layouts belong to the current profile, just like the Home page.
import { api } from "./api.js";
import { store, devicesIn } from "./store.js";
import { $, esc, toast, isMedia } from "./util.js";
import { svg } from "./icons.js";
import { tileHtml } from "./tiles.js";
import "../vendor/sortablejs/Sortable.min.js";
import { invalidateMarkup } from "./render.js";
import { SIZES, SIZE_NAMES, columnsFor, arrange, remember, place, placementStyle, gridStyle, bindGridEditor, watchGridWidth } from "./grid.js";

let draft = null, editingRoom = null, redraw = () => {}, cancelGesture = () => {}, saving = false;
let editingProfile = null, editCompact = false, sorter = null, sortList = null, sortCancelled = false;
export const isRoomEditing = () => draft !== null;
export const compactRooms = () => isRoomEditing() ? editCompact : store.settings.room_view !== "free";
const columns = () => columnsFor($("#grid").clientWidth);
const label = (r) => r || "Other";
const KIND_ORDER = { tv: 0, speaker: 1, light: 2, switch: 3, fan: 4, purifier: 5, plug: 6, vacuum: 7, other: 8 };

function roomWidgets(room) {
  const devices = devicesIn(room).sort((a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || a.name.localeCompare(b.name));
  const saved = store.settings.room_layouts?.[room]?.widgets || [];
  const items = devices.map((d) => saved.find((w) => w.id === d.id) || { id: d.id, size: isMedia(d) ? "2x1" : "1x1" });
  return [...saved.filter(w => devices.some(d => d.id === w.id)), ...items.filter(w => !saved.some(s => s.id === w.id))];
}

export function syncRoomEditor() {
  if (draft && editingProfile !== store.me?.id) stopRoomEditing(false);
  if (draft) draft.widgets = draft.widgets.filter(w => devicesIn(editingRoom).some(d => d.id === w.id));
}

function toolbar() {
  return `<div class="editbar" role="toolbar" aria-label="Edit room tiles">
    <span class="editbar-hint">${editCompact ? "Drag the grips to reorder cards" : "Hold to move · corner to resize"}</span>
    <button class="btn small" data-room-cancel ${saving ? "disabled" : ""}>Cancel</button>
    <button class="btn small primary" data-room-done ${saving ? "disabled" : ""}>${saving ? "Saving..." : "Done"}</button>
    <span class="visually-hidden" role="status" data-card-sort-status></span>
  </div>`;
}

const grip = d => `<button type="button" class="card-sort-grip" data-card-grip="${esc(d.id)}"
  aria-label="Reorder ${esc(d.name)}" aria-keyshortcuts="ArrowUp ArrowDown ArrowLeft ArrowRight"
  title="Drag to reorder; use arrow keys when focused" ${saving ? "disabled" : ""}>
  <svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M5 12h14M5 17h14"/></svg></button>`;

export function roomLayoutKey(room) {
  const editing = isRoomEditing() && room === editingRoom;
  const items = editing ? draft.widgets : roomWidgets(room);
  return [room, compactRooms(), columns(), editing, saving, items,
    items.map(w => { const d = store.devices.get(w.id); return [w.id, d?.name, d?.kind]; })];
}

export function roomTiles(room) {
  const editing = isRoomEditing() && room === editingRoom;
  const items = editing ? draft.widgets : roomWidgets(room);
  if (compactRooms()) return `<div class="compact-rooms${editing ? " editing" : ""}">${items.map(w => {
    const d = store.devices.get(w.id);
    return `<div class="room-card" data-wid="${esc(w.id)}">${tileHtml(d, {compact:true, editing})}${editing ? grip(d) : ""}</div>`;
  }).join("")}</div>${editing ? toolbar() : ""}`;
  const positions = arrange(items, columns());
  return `<div class="tiles layout-grid${editing ? " editing" : ""}" style="${gridStyle(items, columns(), editing)}">${
    items.map((w) => {
      const d = store.devices.get(w.id), p = positions.get(w.id);
      if (!d) return "";
      return `<div class="room-tile layout-item s-${p.size}" data-wid="${esc(w.id)}"
        ${editing ? `tabindex="0" aria-label="Move ${esc(d.name)} with arrow keys"` : ""}
        style="${placementStyle(p)}">${tileHtml(d, { size: p.size, editing })}
        ${editing ? `<button class="w-badge w-menu" data-room-options="${esc(w.id)}" aria-label="${esc(d.name)} layout options">${svg("dots")}</button>
          <button class="w-resize" data-resize aria-label="Change size of ${esc(d.name)} (now ${SIZE_NAMES[p.size]})">${svg("resize")}</button>` : ""}</div>`;
    }).join("")}</div>${editing ? toolbar() : ""}`;
}

export function startRoomEditing(room) {
  if (isRoomEditing()) return;
  editingProfile = store.me?.id;
  editCompact = store.settings.room_view !== "free";
  editingRoom = room;
  draft = { version: 3, widgets: JSON.parse(JSON.stringify(roomWidgets(room))) };
  if (!editCompact) remember(draft.widgets, columns());
  document.documentElement.dataset.layoutEditing = "rooms";
  redraw();
}

function closeOptions() { document.querySelector(".room-layout-menu")?.remove(); }

export function stopRoomEditing(render = true) {
  cancelGesture();
  cancelSort();
  draft = null;
  editingRoom = null;
  editingProfile = null;
  delete document.documentElement.dataset.layoutEditing;
  closeOptions();
  if (render) redraw();
}

async function save() {
  if (saving) return;
  const next = draft, room = editingRoom, profile = editingProfile;
  saving = true;
  redraw();
  try {
    const saved = await api.saveRoomLayout(room, next);
    if (draft !== next || store.me?.id !== profile) return;
    store.settings = { ...store.settings, ...saved };
    stopRoomEditing();
    toast(`${label(room)} layout saved`);
  } catch (e) { toast(e.message, true); }
  finally { saving = false; redraw(); }
}

function options(id) {
  if (!draft || editCompact || saving) return;
  closeOptions();
  const d = store.devices.get(id), p = arrange(draft.widgets, columns()).get(id);
  if (!d || !p) return;
  const wrap = document.createElement("div");
  wrap.className = "wmenu-wrap room-layout-menu";
  wrap.innerHTML = `<div class="wmenu-scrim" data-room-options-close></div>
    <div class="wmenu" role="dialog" aria-modal="true" aria-label="${esc(d.name)} layout options">
      <h3>${esc(d.name)}</h3>
      <div class="seg" role="radiogroup" aria-label="Size">${SIZES.map((s) =>
        `<button role="radio" aria-checked="${p.size === s}" data-room-size="${s}" data-wid="${esc(id)}">${SIZE_NAMES[s]}</button>`).join("")}</div>
      <div class="wmenu-row">${[["Left", -1, 0], ["Right", 1, 0], ["Up", 0, -1], ["Down", 0, 1]].map(([text, x, y]) =>
        `<button class="btn small" data-room-move="${x},${y}" data-wid="${esc(id)}">${text}</button>`).join("")}</div>
      <p>Column ${p.x + 1}, row ${p.y + 1}. Changes apply to this ${columns()}-column layout.</p>
      <button class="btn primary" data-room-options-close>Close</button>
    </div>`;
  document.body.append(wrap);
  wrap.querySelector("button")?.focus();
}

export function setupRoomEditor(root, render) {
  redraw = render;
  cancelGesture = bindGridEditor(root, { enabled: () => isRoomEditing() && !editCompact && !saving, items: () => draft.widgets,
    render, error: (message) => toast(message, true) });
  watchGridWidth(root, () => { cancelGesture(); render(); });
  addEventListener("resize", () => { cancelSort(); cancelGesture(); render(); });
  addEventListener("blur", () => { cancelSort(); cancelGesture(); render(); });
  root.addEventListener("pointercancel", () => { cancelSort(); render(); });
  root.addEventListener("keydown", e => {
    const handle = e.target.closest("[data-card-grip]");
    const step = {ArrowUp:-1,ArrowLeft:-1,ArrowDown:1,ArrowRight:1}[e.key];
    if (!handle || !step || !draft || saving) return;
    e.preventDefault(); e.stopPropagation();
    const index = draft.widgets.findIndex(w => w.id === handle.dataset.cardGrip);
    if (index + step < 0 || index + step >= draft.widgets.length) return;
    const [item] = draft.widgets.splice(index, 1);
    draft.widgets.splice(index + step, 0, item);
    render();
    root.querySelector(`[data-card-grip="${CSS.escape(item.id)}"]`)?.focus({preventScroll:true});
    root.querySelector("[data-card-sort-status]").textContent = `Moved to position ${index + step + 1} of ${draft.widgets.length}`;
  });
  root.addEventListener("click", (e) => {
    if (e.target.closest("[data-room-done]")) return save();
    if (e.target.closest("[data-room-cancel]")) return stopRoomEditing();
    const button = e.target.closest("[data-room-options]");
    if (button) options(button.dataset.roomOptions);
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".room-layout-menu") || !isRoomEditing()) return;
    if (e.target.closest("[data-room-options-close]")) return closeOptions();
    const button = e.target.closest("[data-room-size], [data-room-move]");
    if (!button) return;
    const id = button.dataset.wid, p = arrange(draft.widgets, columns()).get(id);
    let next = { ...p };
    if (button.dataset.roomSize) next.size = button.dataset.roomSize;
    else {
      const [x, y] = button.dataset.roomMove.split(",").map(Number);
      next.x += x; next.y += y;
    }
    if (!place(draft.widgets, columns(), id, next)) toast("Choose an empty space inside the grid, or a smaller size.", true);
    render();
    options(id);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeOptions(); });
}

function cancelSort() {
  sortCancelled = true;
  const current = sorter;
  sorter = null; sortList = null;
  current?.destroy();
  delete $("#grid").dataset.gridGesture;
}

export function syncCompactSorter(root) {
  const list = root.querySelector(".compact-rooms.editing");
  if (list === sortList) { sorter?.option("disabled", saving); return; }
  cancelSort();
  if (!list || !draft || !editCompact) return;
  sortList = list;
  let entry = null;
  sorter = new globalThis.Sortable(list, {
    handle: "[data-card-grip]", draggable: ".room-card", dataIdAttr:"data-wid",
    group:{name:"compact-cards",pull:false,put:false}, forceFallback:true, fallbackOnBody:true,
    fallbackTolerance:3, delayOnTouchOnly:true, delay:120, touchStartThreshold:4,
    animation:matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 180,
    ghostClass:"card-sort-ghost", fallbackClass:"card-sort-drag", disabled:saving,
    onStart() { entry=draft; sortCancelled=false; root.dataset.gridGesture="compact"; },
    onEnd(e) {
      delete root.dataset.gridGesture;
      if (!sortCancelled && draft === entry && editingProfile === store.me?.id) {
        const ids=[...list.querySelectorAll(":scope > .room-card")].map(el=>el.dataset.wid);
        const permitted=new Set(devicesIn(editingRoom).map(d=>d.id));
        draft.widgets=ids.map(id=>entry.widgets.find(w=>w.id===id)).filter(w=>w && permitted.has(w.id));
      }
      invalidateMarkup(root);
      queueMicrotask(() => {
        redraw();
        root.querySelector(`[data-card-grip="${CSS.escape(e.item.dataset.wid)}"]`)?.focus({preventScroll:true});
      });
    },
  });
}
