// Room tile layouts belong to the current profile, just like the Home page.
import { api } from "./api.js";
import { store, devicesIn } from "./store.js";
import { $, esc, toast } from "./util.js";
import { svg } from "./icons.js";
import { tileHtml } from "./tiles.js";
import { sizeChoices, sizeName, grip, columnsFor, arrange, remember, place, placementStyle, gridStyle, bindGridEditor, watchGridWidth } from "./grid.js";

let draft = null, editingRoom = null, redraw = () => {}, cancelGesture = () => {}, saving = false;
let editingProfile = null, entryLayout = null;
export const isRoomEditing = () => draft !== null;
const columns = () => columnsFor($("#grid").clientWidth);
const label = (r) => r || "Other";
const KIND_ORDER = { tv: 0, speaker: 1, light: 2, switch: 3, fan: 4, purifier: 5, plug: 6, vacuum: 7, other: 8 };

function roomWidgets(room) {
  const devices = devicesIn(room).sort((a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || a.name.localeCompare(b.name));
  const saved = store.settings.room_layouts?.[room]?.widgets || [];
  const items = devices.map((d) => saved.find((w) => w.id === d.id) || { id: d.id, size: `${columns()>2 ? columns()/2 : 2}x3` });
  return [...saved.filter(w => devices.some(d => d.id === w.id)), ...items.filter(w => !saved.some(s => s.id === w.id))];
}

export function syncRoomEditor() {
  if (draft && editingProfile !== store.me?.id) stopRoomEditing(false);
  if (draft) draft.widgets = draft.widgets.filter(w => devicesIn(editingRoom).some(d => d.id === w.id));
}

function toolbar() {
  return `<div class="editbar" role="toolbar" aria-label="Edit room tiles">
    <span class="editbar-hint">Drag a grip to move; drag a corner to resize</span>
    <button class="btn small" data-room-cancel ${saving ? "disabled" : ""}>Cancel</button>
    <button class="btn small primary" data-room-done ${saving ? "disabled" : ""}>${saving ? "Saving..." : "Done"}</button>
  </div>`;
}

export function roomLayoutKey(room) {
  const editing = isRoomEditing() && room === editingRoom;
  const items = editing ? draft.widgets : roomWidgets(room);
  return [room, columns(), editing, saving, items,
    items.map(w => { const d = store.devices.get(w.id); return [w.id, d?.name, d?.kind]; })];
}

export function roomTiles(room) {
  const editing = isRoomEditing() && room === editingRoom;
  const items = editing ? draft.widgets : roomWidgets(room);
  const positions = arrange(items, columns());
  return `<div class="tiles layout-grid${editing ? " editing" : ""}" style="${gridStyle(items, columns(), editing && store.room !== "all")}">${
    items.map((w) => {
      const d = store.devices.get(w.id), p = positions.get(w.id);
      if (!d) return "";
      return `<div class="room-tile room-card layout-item" data-wid="${esc(w.id)}"
        ${editing ? `tabindex="0" aria-label="Move ${esc(d.name)} with arrow keys"` : ""}
        style="${placementStyle(p)}">${tileHtml(d, { editing })}
        ${editing ? `${grip(esc(d.name))}<button class="w-badge w-menu" data-room-options="${esc(w.id)}" aria-label="${esc(d.name)} layout options">${svg("dots")}</button>
          <button class="w-resize" data-resize aria-label="Resize ${esc(d.name)} (now ${sizeName(p.size)}); use arrow keys">${svg("resize")}</button>` : ""}</div>`;
    }).join("")}</div>${editing ? toolbar() : ""}`;
}

export function startRoomEditing(room) {
  if (isRoomEditing()) return;
  editingProfile = store.me?.id;
  editingRoom = room;
  entryLayout=JSON.parse(JSON.stringify(store.settings.room_layouts?.[room] ?? null));
  draft = { version: 4, widgets: JSON.parse(JSON.stringify(roomWidgets(room))) };
  remember(draft.widgets, columns());
  document.documentElement.dataset.layoutEditing = "rooms";
  redraw();
}

function closeOptions() { document.querySelector(".room-layout-menu")?.remove(); }

export function stopRoomEditing(render = true) {
  cancelGesture();
  draft = null;
  editingRoom = null;
  editingProfile = null;
  entryLayout=null;
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
    const saved = await api.saveRoomLayout(room, next, entryLayout);
    if (draft !== next || store.me?.id !== profile) return;
    store.settings = { ...store.settings, ...saved };
    stopRoomEditing();
    toast(`${label(room)} layout saved`);
  } catch (e) { toast(e.message, true); }
  finally { saving = false; redraw(); }
}

function options(id) {
  if (!draft || saving) return;
  closeOptions();
  const d = store.devices.get(id), p = arrange(draft.widgets, columns()).get(id);
  if (!d || !p) return;
  const wrap = document.createElement("div");
  wrap.className = "wmenu-wrap room-layout-menu";
  wrap.innerHTML = `<div class="wmenu-scrim" data-room-options-close></div>
    <div class="wmenu" role="dialog" aria-modal="true" aria-label="${esc(d.name)} layout options">
      <h3>${esc(d.name)}</h3>
      <div class="seg" role="radiogroup" aria-label="Size">${sizeChoices(null,columns()).map((s) =>
        `<button role="radio" aria-checked="${p.size === s}" data-room-size="${s}" data-wid="${esc(id)}">${sizeName(s)}</button>`).join("")}</div>
      <p>Arrow keys on the grip move one cell. Arrow keys on the corner change width and height.</p>
      <p>Column ${p.x + 1}, row ${p.y + 1}. Changes apply to this ${columns()}-column layout.</p>
      <button class="btn primary" data-room-options-close>Close</button>
    </div>`;
  document.body.append(wrap);
  wrap.querySelector("button")?.focus();
}

export function setupRoomEditor(root, render) {
  redraw = render;
  cancelGesture = bindGridEditor(root, { enabled: () => isRoomEditing() && !saving, items: () => draft.widgets,
    render, error: (message) => toast(message, true) });
  watchGridWidth(root, () => { cancelGesture(); render(); });
  addEventListener("resize", () => { cancelGesture(); render(); });
  addEventListener("blur", () => { cancelGesture(); render(); });
  root.addEventListener("click", (e) => {
    if (e.target.closest("[data-room-done]")) return save();
    if (e.target.closest("[data-room-cancel]")) return stopRoomEditing();
    const button = e.target.closest("[data-room-options]");
    if (button) options(button.dataset.roomOptions);
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".room-layout-menu") || !isRoomEditing()) return;
    if (e.target.closest("[data-room-options-close]")) return closeOptions();
    const button = e.target.closest("[data-room-size]");
    if (!button) return;
    const id = button.dataset.wid, p = arrange(draft.widgets, columns()).get(id);
    const next = { ...p, size:button.dataset.roomSize };
    if (!place(draft.widgets, columns(), id, next)) toast("Choose an empty space inside the grid, or a smaller size.", true);
    render();
    options(id);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeOptions(); });
}
