// SortableJS 1.15.7 (MIT) handles pointer/touch sorting; the app owns keyboard
// access, authorization and server-side persistence. No CDN or framework.
import "../vendor/sortablejs/Sortable.min.js";
import { store, saveRooms, moveRoom, emit } from "./store.js";
import { esc, toast } from "./util.js";
import { invalidateMarkup } from "./render.js";

const sorters = new Map();
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
reducedMotion.addEventListener("change", () => syncRoomSorters());
let dragging = false, saving = false;
export const isSortingRooms = () => dragging || saving;

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
  if (isSortingRooms()) return;
  const room = grip.dataset.roomGrip, i = store.rooms.indexOf(room);
  if (i + step < 0 || i + step >= store.rooms.length) return announce(`${room} is already ${step < 0 ? "first" : "last"}.`);
  commitOrder(() => moveRoom(room, step), room, scopeOf(grip));
}

export function syncRoomSorters() {
  for (const [list, sorter] of sorters) {
    if (!list.isConnected || store.me?.role !== "admin") {
      sorter.destroy();
      list.removeEventListener("keydown", keyMove);
      sorters.delete(list);
    } else {
      sorter.option("disabled", saving);
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
      disabled: saving,
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
