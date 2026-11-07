// Room tile layouts belong to the current profile, just like the Home page.
import { api } from "./api.js";
import { store, devicesIn } from "./store.js";
import { $, esc, toast, isMedia } from "./util.js";
import { svg } from "./icons.js";
import { tileHtml } from "./tiles.js";
import { SIZES, SIZE_NAMES, columnsFor, arrange, remember, place, placementStyle, gridStyle, bindGridEditor, watchGridWidth } from "./grid.js";

let draft = null, editingRoom = null, redraw = () => {}, cancelGesture = () => {}, saving = false;
export const isRoomEditing = () => draft !== null;
const columns = () => columnsFor($("#grid").clientWidth);
const label = (r) => r || "Other";
const KIND_ORDER = { tv: 0, speaker: 1, light: 2, switch: 3, fan: 4, plug: 5, vacuum: 6, other: 7 };

function roomWidgets(room) {
  const devices = devicesIn(room).sort((a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || a.name.localeCompare(b.name));
  const saved = store.settings.room_layouts?.[room]?.widgets || [];
  return devices.map((d) => saved.find((w) => w.id === d.id) || { id: d.id, size: isMedia(d) ? "2x1" : "1x1" });
}

export function roomTiles(room) {
  const editing = isRoomEditing() && room === editingRoom;
  const items = editing ? draft.widgets : roomWidgets(room);
  const positions = arrange(items, columns());
  return `<div class="tiles layout-grid${editing ? " editing" : ""}" style="${gridStyle(items, columns(), editing)}">${
    items.map((w) => {
      const d = store.devices.get(w.id), p = positions.get(w.id);
      if (!d) return "";
      return `<div class="room-tile layout-item s-${p.size}" data-wid="${esc(w.id)}"
        ${editing ? `tabindex="0" aria-label="Move ${esc(d.name)} with arrow keys"` : ""}
        style="${placementStyle(p)}">${tileHtml(d, { size: p.size })}
        ${editing ? `<button class="w-badge w-menu" data-room-options="${esc(w.id)}" aria-label="${esc(d.name)} layout options">${svg("dots")}</button>
          <button class="w-resize" data-resize aria-label="Change size of ${esc(d.name)} (now ${SIZE_NAMES[p.size]})">${svg("resize")}</button>` : ""}</div>`;
    }).join("")}</div>${editing ? `<div class="editbar" role="toolbar" aria-label="Edit room tiles">
      <span class="editbar-hint">Hold to move into free space · corner to resize</span>
      <button class="btn small" data-room-cancel ${saving ? "disabled" : ""}>Cancel</button>
      <button class="btn small primary" data-room-done ${saving ? "disabled" : ""}>${saving ? "Saving..." : "Done"}</button>
    </div>` : ""}`;
}

export function startRoomEditing(room) {
  if (isRoomEditing()) return;
  editingRoom = room;
  draft = { version: 3, widgets: JSON.parse(JSON.stringify(roomWidgets(room))) };
  remember(draft.widgets, columns());
  redraw();
}

function closeOptions() { document.querySelector(".room-layout-menu")?.remove(); }

export function stopRoomEditing() {
  cancelGesture();
  draft = null;
  editingRoom = null;
  closeOptions();
  redraw();
}

async function save() {
  if (saving) return;
  const next = draft, room = editingRoom, profile = store.me?.id;
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
  cancelGesture = bindGridEditor(root, { enabled: () => isRoomEditing() && !saving, items: () => draft.widgets,
    render, error: (message) => toast(message, true) });
  watchGridWidth(root, () => { cancelGesture(); render(); });
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
