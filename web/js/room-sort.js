// SortableJS 1.15.7 (MIT) handles pointer/touch sorting; the app owns keyboard
// access, authorization and server-side persistence. No CDN or framework.
import "../vendor/sortablejs/Sortable.min.js";
import { store, saveRooms, moveRoom, renameRoom, emit } from "./store.js";
import { esc, toast } from "./util.js";
import { invalidateMarkup } from "./render.js";

const sorters = new Map();
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
reducedMotion.addEventListener("change", () => syncRoomSorters());
let dragging = false, saving = false, editingProfile = null;
export const isSortingRooms = () => dragging || saving;
export const isEditingRooms = () => store.me?.role === "admin" && editingProfile === store.me.id;

export function toggleRoomEditing() {
  if (store.me?.role !== "admin" || isSortingRooms()) return;
  editingProfile = isEditingRooms() ? null : store.me.id;
  if (!isEditingRooms()) document.querySelector(".room-name-dialog")?.close();
  emit("all");
  syncRoomSorters();
}

export const roomEditButton = () => `<button class="btn small" type="button" data-edit-rooms
  aria-pressed="${isEditingRooms()}">${isEditingRooms() ? "Done" : "Edit"}</button>`;

export const roomRenameButton = (room) => `<button type="button" class="btn small room-rename"
  data-rename-room="${esc(room)}" aria-label="Rename ${esc(room)}">Rename</button>`;

export const roomGrip = (room) => `<button type="button" class="room-grip" data-room-grip="${esc(room)}"
  aria-label="Reorder ${esc(room)}" aria-describedby="room-sort-help" aria-keyshortcuts="ArrowUp ArrowDown ArrowLeft ArrowRight"
  title="Drag to reorder; arrow keys when focused"><svg class="i" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M5 7h14M5 12h14M5 17h14"/></svg></button>`;

function announce(message) {
  const status = document.querySelector("#room-sort-status");
  if (status) status.textContent = message;
}

function scopeOf(list) {
  return list.closest("#rail") ? "#rail" : list.closest("#settings") ? "#settings" : "#rooms";
}

function redraw(scope, room) {
  invalidateMarkup(document.querySelector(scope));
  emit("all");
  document.querySelector(`${scope} [data-room-grip="${CSS.escape(room)}"]`)?.focus();
}

async function commitOrder(action, room, scope) {
  saving = true;
  for (const sorter of sorters.values()) sorter.option("disabled", true);
  try {
    await action();
    const message = `${room} moved to position ${store.rooms.indexOf(room) + 1} of ${store.rooms.length}.`;
    announce(message);
    toast("Room order saved");
  } catch (e) {
    announce(e.message);
    toast(e.message, true);
  } finally {
    saving = false;
    redraw(scope, room);
    syncRoomSorters();
  }
}

function keyMove(e) {
  const grip = e.target.closest("[data-room-grip]");
  const step = { ArrowUp: -1, ArrowLeft: -1, ArrowDown: 1, ArrowRight: 1 }[e.key];
  if (!grip || !step) return;
  e.preventDefault();
  e.stopPropagation();
  if (isSortingRooms() || !isEditingRooms()) return;
  const room = grip.dataset.roomGrip, i = store.rooms.indexOf(room);
  if (i + step < 0 || i + step >= store.rooms.length) return announce(`${room} is already ${step < 0 ? "first" : "last"}.`);
  commitOrder(() => moveRoom(room, step), room, scopeOf(grip));
}

export function syncRoomSorters() {
  if (editingProfile !== null && (store.me?.role !== "admin" || editingProfile !== store.me.id)) {
    editingProfile = null;
    document.querySelector(".room-name-dialog")?.close();
  }
  for (const [list, sorter] of sorters) {
    if (!list.isConnected || store.me?.role !== "admin") {
      sorter.destroy();
      list.removeEventListener("keydown", keyMove);
      sorters.delete(list);
    } else {
      sorter.option("disabled", saving || !isEditingRooms());
      sorter.option("animation", reducedMotion.matches ? 0 : 150);
    }
  }
  if (store.me?.role !== "admin") return;
  for (const list of document.querySelectorAll("[data-room-sort]")) {
    if (sorters.has(list)) continue;
    let expected = [];
    const sorter = new globalThis.Sortable(list, {
      handle: ".room-grip",
      draggable: "[data-sort-room]",
      dataIdAttr: "data-sort-room",
      group: { name: "room-order", pull: false, put: false },
      direction: list.dataset.roomSort,
      animation: reducedMotion.matches ? 0 : 150,
      forceFallback: true,
      fallbackOnBody: true,
      fallbackTolerance: 3,
      delayOnTouchOnly: true,
      delay: 120,
      touchStartThreshold: 4,
      ghostClass: "room-sort-ghost",
      chosenClass: "room-sort-chosen",
      fallbackClass: "room-sort-drag",
      disabled: saving || !isEditingRooms(),
      onStart() {
        dragging = true;
        expected = [...store.rooms];
      },
      onEnd(e) {
        const order = sorter.toArray(), room = e.item.dataset.sortRoom, scope = scopeOf(list);
        dragging = false;
        if (order.every((r, i) => r === expected[i]) && order.length === expected.length) {
          queueMicrotask(() => redraw(scope, room));
          return;
        }

        commitOrder(() => {
          if (order.length !== expected.length || new Set(order).size !== expected.length || order.some((r) => !expected.includes(r))) {
            throw new Error("Rooms changed while dragging. Reload and try again.");
          }
          return saveRooms(order, expected);
        }, room, scope);
      },
    });
    sorters.set(list, sorter);
    list.addEventListener("keydown", keyMove);
  }
}

export function showRoomRename(room) {
  if (!isEditingRooms() || isSortingRooms()) return;
  document.querySelector(".room-name-dialog")?.close();
  const dialog = document.createElement("dialog");
  dialog.className = "room-name-dialog";
  dialog.setAttribute("aria-labelledby", "room-rename-title");
  dialog.innerHTML = `<form>
    <h2 id="room-rename-title">Rename room</h2>
    <label class="field"><span>Room name</span><input name="room" value="${esc(room)}" maxlength="24" required></label>
    <p>Devices and tile layouts will stay in this room.</p>
    <p class="room-rename-error" role="alert"></p>
    <div class="btn-row"><button type="button" class="btn" data-cancel>Cancel</button>
      <button type="submit" class="btn primary">Rename room</button></div>
  </form>`;
  dialog.addEventListener("close", () => dialog.remove());
  dialog.addEventListener("keydown", (e) => { if (e.key === "Escape") e.stopPropagation(); });
  dialog.querySelector("[data-cancel]").addEventListener("click", () => dialog.close());
  dialog.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target, input = form.elements.room, controls = [...form.querySelectorAll("button, input")];
    controls.forEach((el) => { el.disabled = true; });
    try {
      const name = await renameRoom(room, input.value);
      toast(`Room renamed to ${name}`);
      announce(`Room renamed to ${name}`);
      dialog.close();
    } catch (error) {
      dialog.querySelector(".room-rename-error").textContent = error.message;
      controls.forEach((el) => { el.disabled = false; });
      input.focus();
    }
  });
  document.body.append(dialog);
  dialog.showModal();
  dialog.querySelector("input").select();
}
