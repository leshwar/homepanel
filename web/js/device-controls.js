// Release-to-apply sliders shared by the device panels: a tap never jumps the value,
// a drag previews, and one command is sent when the finger lifts.

export const relativeValue = (base, start, point, length, min = 0, max = 100, step = 1) =>
  Math.max(min, Math.min(max, Math.round((base + (point - start) / Math.max(1, length) * (max - min)) / step) * step));

const gestures = new Map();
export const controlGestureBusy = () => gestures.size > 0;
export function clearControlGestures() {
  for (const cancel of gestures.values()) cancel();
  gestures.clear();
}

export function bindRelativeRange(range, { value, preview, commit, idle }) {
  let drag = null, pointerChange = false;
  const show = (v) => { range.value = v; preview(v); };
  const cancel = () => { drag = null; show(value()); };
  for (const event of ["touchstart", "touchmove"]) range.addEventListener(event, (e) => e.preventDefault(), { passive: false });
  range.addEventListener("pointerdown", (e) => {
    if (range.disabled || e.button > 0 || gestures.size) return;
    e.preventDefault();
    range.focus({ preventScroll: true });
    range.setPointerCapture(e.pointerId);
    drag = { pointer: e.pointerId, base: value(), value: value(), x: e.clientX, y: e.clientY,
      width: range.getBoundingClientRect().width, moved: false, canceled: false };
    gestures.set(range, cancel);
  });
  range.addEventListener("pointermove", (e) => {
    if (!drag || drag.pointer !== e.pointerId) return;
    e.preventDefault();
    const dx = Math.abs(e.clientX - drag.x), dy = Math.abs(e.clientY - drag.y);
    if (!drag.moved && dy > 6 && dy > dx) drag.canceled = true;
    if (drag.canceled) return;
    if (dx > 6) drag.moved = true;
    if (drag.moved) {
      drag.value = relativeValue(drag.base, drag.x, e.clientX, drag.width,
        Number(range.min), Number(range.max), Number(range.step) || 1);
      show(drag.value);
    }
  });
  const finish = (e) => {
    if (!drag || drag.pointer !== e.pointerId) return;
    e.preventDefault();
    const done = drag;
    drag = null; gestures.delete(range);
    pointerChange = true;
    setTimeout(() => { pointerChange = false; }, 0);
    if (e.type === "pointerup" && !done.canceled && done.moved && done.value !== done.base) commit(done.value);
    else { show(value()); idle(); }
  };
  range.addEventListener("pointerup", finish);
  range.addEventListener("pointercancel", finish);
  range.addEventListener("lostpointercapture", finish);
  range.addEventListener("input", () => { if (!drag) preview(Number(range.value)); });
  range.addEventListener("change", () => {
    if (!drag && !pointerChange && range.isConnected && !range.closest(".closing")) commit(Number(range.value));
  });
}
