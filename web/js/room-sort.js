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
const nameDrafts = new Map();
let refreshingNames = false;
const hasRoomEntryDraft = () => [...document.querySelectorAll("[data-room-add] input")].some(input => input.value.trim());
const addingRoom = () => !!document.querySelector("#rail [data-room-add], #room-tools [data-room-add]") || hasRoomEntryDraft();
export const isSortingRooms = () => dragging || saving;
export const isEditingRooms = () => store.me?.role === "admin" && editingProfile === store.me.id;
export const isEditingRoomName = () => !refreshingNames && isEditingRooms()
  && (nameDrafts.size > 0 || hasRoomEntryDraft() || document.activeElement?.matches("[data-room-name], [data-room-add] input"));
// Keep a removed room's unsaved field visible until it is explicitly canceled.
export const editableRoomNames = (rooms) => [...new Set([...rooms, ...nameDrafts.keys()])];

export async function toggleRoomEditing(scope) {
  if (store.me?.role !== "admin" || isSortingRooms()) return false;
  if (isEditingRooms() && hasRoomEntryDraft()) {
    toast("Add or cancel the new room first.", true); return false;
  }
  if (isEditingRooms() && !await commitNames(scope)) return false;
  editingProfile = isEditingRooms() ? null : store.me.id;
  emit("all");
  syncRoomSorters();
  return true;
}

export const roomEditButton = () => `<button class="btn small" type="button" data-edit-rooms
  aria-pressed="${isEditingRooms()}">${isEditingRooms() ? "Done" : "Edit"}</button>`;

export const roomNameField = (room) => `<span class="room-name-field">
  <input data-room-name="${esc(room)}" value="${esc(nameDrafts.get(room)?.value ?? room)}"
    aria-label="Room name: ${esc(room)}" aria-describedby="room-name-help"
    aria-invalid="${!!nameDrafts.get(room)?.error}" maxlength="24" required autocomplete="off">
  <span class="room-name-error" role="alert" ${nameDrafts.get(room)?.error ? "" : "hidden"}>${esc(nameDrafts.get(room)?.error || "")}</span></span>`;

export const roomNameHelp = () => `<div class="room-name-help">
  <p>Enter or Done saves names. Escape cancels a name. Save names before dragging.</p>
  <button class="btn small" type="button" data-cancel-room-names ${nameDrafts.size ? "" : "hidden"}>Cancel name edits</button></div>`;

export function canLeaveRoomNames(allowEntry = false) {
  if (!isEditingRooms()) return true;
  if (nameDrafts.size) {
    toast("Save room names with Enter or Done, or cancel the name edits.", true); return false;
  }
  if (!allowEntry && hasRoomEntryDraft()) {
    toast("Add or cancel the new room first.", true); return false;
  }
  return true;
}

function refreshNames(scope, room) {
  syncNameFields();
  refreshingNames = true;
  try { emit("all"); } finally { refreshingNames = false; }
  syncRoomSorters();
  document.querySelector(`${scope} [data-room-name="${CSS.escape(room)}"]`)?.focus();
}

function syncNameFields() {
  for (const input of document.querySelectorAll("[data-room-name]")) {
    const room = input.dataset.roomName, draft = nameDrafts.get(room);
    if (input.value !== (draft?.value ?? room)) input.value = draft?.value ?? room;
    input.disabled = saving;
    input.setAttribute("aria-invalid", String(!!draft?.error));
    const error = input.nextElementSibling;
    error.textContent = draft?.error || "";
    error.hidden = !draft?.error;
  }
  for (const button of document.querySelectorAll("[data-cancel-room-names]")) {
    button.hidden = !nameDrafts.size;
    button.disabled = saving;
  }
  syncRoomSorters();
}

async function commitNames(scope, onlyRoom) {
  if (!isEditingRooms() || isSortingRooms()) return false;
  let focus = onlyRoom || "", success = true;
  saving = true;
  syncNameFields();
  try {
    for (const [room, draft] of [...nameDrafts]) {
      if (onlyRoom && room !== onlyRoom) continue;
      try {
        focus = await renameRoom(room, draft.value);
        nameDrafts.delete(room);
        announce(`Room name saved: ${focus}`);
      } catch (error) {
        draft.error = error.message;
        focus = room;
        success = false;
        announce(error.message);
        toast(error.message, true);
        break;
      }
    }
  } finally {
    saving = false;
    refreshNames(scope, focus);
  }
  return success;
}

document.addEventListener("input", (e) => {
  if (e.target.matches("[data-room-add] input")) { syncRoomSorters(); return; }
  const input = e.target.closest("[data-room-name]");
  if (!input || !isEditingRooms() || saving) return;
  const room = input.dataset.roomName;
  if (input.value === room) nameDrafts.delete(room);
  else nameDrafts.set(room, { value: input.value, error: "" });
  syncNameFields();
});

document.addEventListener("keydown", (e) => {
  const input = e.target.closest("[data-room-name]");
  if (!input || e.isComposing || !["Enter", "Escape"].includes(e.key)) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  if (!isEditingRooms() || saving) return;
  if (e.key === "Enter") commitNames(scopeOf(input), input.dataset.roomName);
  else {
    nameDrafts.delete(input.dataset.roomName);
    refreshNames(scopeOf(input), input.dataset.roomName);
    announce("Room name edit canceled.");
  }
}, true);

document.addEventListener("click", (e) => {
  const cancel = e.target.closest("[data-cancel-room-names]");
  if (!cancel || !isEditingRooms() || saving) return;
  const scope = scopeOf(cancel);
  nameDrafts.clear();
  refreshNames(scope, "");
  document.querySelector(`${scope === "#rooms" ? "#room-tools" : scope} [data-edit-rooms]`)?.focus();
  announce("Room name edits canceled.");
});

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
  if (isSortingRooms() || !isEditingRooms() || !canLeaveRoomNames()) return;
  if (addingRoom()) return toast("Add or cancel the new room before reordering.", true);
  const room = grip.dataset.roomGrip, i = store.rooms.indexOf(room);
  if (i + step < 0 || i + step >= store.rooms.length) return announce(`${room} is already ${step < 0 ? "first" : "last"}.`);
  commitOrder(() => moveRoom(room, step), room, scopeOf(grip));
}

export function syncRoomSorters() {
  if (editingProfile !== null && (store.me?.role !== "admin" || editingProfile !== store.me.id)) {
    editingProfile = null;
    nameDrafts.clear();
  }
  for (const [list, sorter] of sorters) {
    if (!list.isConnected || store.me?.role !== "admin") {
      sorter.destroy();
      list.removeEventListener("keydown", keyMove);
      sorters.delete(list);
    } else {
      sorter.option("disabled", saving || !isEditingRooms() || nameDrafts.size > 0 || addingRoom());
      sorter.option("animation", reducedMotion.matches ? 0 : 200);
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
      animation: reducedMotion.matches ? 0 : 200,
      forceFallback: true,
      fallbackOnBody: true,
      fallbackTolerance: 3,
      delayOnTouchOnly: true,
      delay: 120,
      touchStartThreshold: 4,
      ghostClass: "room-sort-ghost",
      chosenClass: "room-sort-chosen",
      fallbackClass: "room-sort-drag",
      disabled: saving || !isEditingRooms() || nameDrafts.size > 0 || addingRoom(),
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
