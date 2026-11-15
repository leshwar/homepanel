// Shared grid geometry and pointer editing for Home and room tiles.
// Positions are independent at each column count; looking at a smaller screen
// never rewrites the arrangement saved on a larger one.
export const SIZES = Array.from({length:6},(_,w)=>Array.from({length:22},(_,h)=>`${w+1}x${h+3}`)).flat();
export const MAX_ROWS = 800;
export const columnsFor = (width) => width >= 960 ? 6 : width >= 600 ? 4 : 2;
const dimensions = (p) => p.size.split("x").map(Number);
export const sizeName = size => `${size.split("x")[0]} columns by ${size.split("x")[1]} rows`;
export const minimumSize = item => [item?.type === "zone" ? 1 : 2, 3];
export const sizeChoices = (item, cols) => [...new Set([`${minimumSize(item)[0]}x3`,`${Math.min(cols,3)}x4`,`${cols}x6`])];
export const grip = name => `<button class="layout-grip" data-grip aria-label="Move ${name}"
  title="Drag to move; arrow keys move one cell" aria-keyshortcuts="ArrowUp ArrowDown ArrowLeft ArrowRight">
  <svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M5 12h14M5 17h14"/></svg></button>`;
const overlaps = (a, b) => {
  const [aw, ah] = dimensions(a), [bw, bh] = dimensions(b);
  return a.x < b.x + bw && b.x < a.x + aw && a.y < b.y + bh && b.y < a.y + ah;
};

export function fits(p, placed, cols) {
  if (!p || !SIZES.includes(p.size) || !Number.isInteger(p.x) || !Number.isInteger(p.y)) return false;
  const [w, h] = dimensions(p);
  return p.x >= 0 && p.y >= 0 && p.x + w <= cols && p.y + h <= MAX_ROWS && !placed.some((q) => overlaps(p, q));
}

export function arrange(items, cols) {
  const result = new Map(), waiting = [];
  for (const item of items.filter((w) => !w.hidden)) {
    const saved = item.positions?.[cols];
    if (fits(saved, [...result.values()], cols)) result.set(item.id, { ...saved });
    else waiting.push(item);
  }
  for (const item of waiting) {
    const variants = Object.keys(item.positions || {}).sort((a, b) => Math.abs(a - cols) - Math.abs(b - cols));
    const source = item.positions?.[variants[0]];
    const raw = source?.size || item.size || "2x3", [width,height] = dimensions({size:raw});
    const size = `${Math.min(width,cols)}x${height}`;
    const placed = [...result.values()];
    const preferred = source && { ...source, size, x: Math.min(source.x, cols - dimensions({ size })[0]) };
    if (fits(preferred, placed, cols)) { result.set(item.id, preferred); continue; }
    let slot = null;
    for (let y = 0; y < MAX_ROWS && !slot; y++) {
      for (let x = 0; x < cols; x++) {
        const p = { x, y, size };
        if (fits(p, placed, cols)) { slot = p; break; }
      }
    }
    if (!slot) throw new Error("This grid is full. Remove a tile or make it smaller.");
    result.set(item.id, slot);
  }
  return result;
}

export function remember(items, cols) {
  const positions = arrange(items, cols);
  for (const w of items) {
    if (positions.has(w.id)) w.positions = { ...w.positions, [cols]: positions.get(w.id) };
  }
  return positions;
}

export function place(items, cols, id, next) {
  const positions = arrange(items, cols);
  const item = items.find(w=>w.id===id), [minW,minH] = minimumSize(item), [w,h] = dimensions(next);
  if (w<minW || h<minH) return false;
  if (!positions.has(id) || !fits(next, [...positions].filter(([key]) => key !== id).map(([, p]) => p), cols)) return false;
  remember(items, cols);
  items.find((w) => w.id === id).positions[cols] = { ...next };
  return true;
}

export function placementStyle(p) {
  const [w, h] = dimensions(p);
  return `grid-column:${p.x + 1} / span ${w};grid-row:${p.y + 1} / span ${h}`;
}

export function gridStyle(items, cols, editing = false) {
  const positions = arrange(items, cols);
  const rows = Math.max(1, ...[...positions.values()].map((p) => p.y + dimensions(p)[1]));
  return `--cols:${cols};grid-template-rows:repeat(${Math.min(MAX_ROWS, rows + (editing ? 8 : 0))}, var(--cell))`;
}

export function watchGridWidth(root, render) {
  new ResizeObserver(([entry]) => {
    const width = entry.contentRect.width;
    const cols = columnsFor(width);
    // A snapshot or navigation may already have rendered the new width before
    // this observer runs. Do not replace those fresh nodes a second time.
    if (width > 0 && [...root.querySelectorAll(".layout-grid")].some(
      (grid) => Number(grid.style.getPropertyValue("--cols")) !== cols)) render();
  }).observe(root);
}

export function bindGridEditor(root, { enabled, items, render, error }) {
  let gesture = null, suppressClick = false;
  const cols = () => columnsFor(root.clientWidth);
  const cancel = () => {
    if (!gesture) return;
    clearTimeout(gesture.timer);
    gesture.box.classList.remove("dragging", "invalid-drop");
    gesture.box.style.transform = "";
    gesture.marker?.remove();
    delete root.dataset.gridGesture;
    const pointer = gesture.pointer;
    gesture = null;
    if (root.hasPointerCapture(pointer)) root.releasePointerCapture(pointer);
  };
  root.addEventListener("pointerdown", (e) => {
    if (!enabled() || gesture || e.button > 0) return;
    const box = e.target.closest(".layout-item");
    if (!box || !e.target.closest("[data-grip], [data-resize]")) return;
    const positions = arrange(items(), cols()), p = positions.get(box.dataset.wid);
    const grid = box.parentElement, cs = getComputedStyle(grid), rect = box.getBoundingClientRect();
    const resizing = !!e.target.closest("[data-resize]");
    gesture = { box, item:items().find(w=>w.id===box.dataset.wid), id: box.dataset.wid, pointer: e.pointerId, resizing, start: p, next: p,
      x: e.clientX, y: e.clientY, grabX: e.clientX - rect.left, grabY: e.clientY - rect.top,
      stepX: parseFloat(cs.gridTemplateColumns) + parseFloat(cs.columnGap),
      stepY: parseFloat(cs.gridAutoRows) + parseFloat(cs.rowGap), gapX: parseFloat(cs.columnGap), gapY: parseFloat(cs.rowGap),
      others: [...positions].filter(([id]) => id !== box.dataset.wid).map(([, p]) => p),
      grid, cols: cols(), moved: false, active: true };
    root.dataset.gridGesture = "active";
    root.setPointerCapture(e.pointerId);  // stable root: tile content may be refreshed by live state
    e.preventDefault();
  });
  root.addEventListener("pointermove", (e) => {
    const g = gesture;
    if (!g || g.pointer !== e.pointerId) return;
    const distance = Math.hypot(e.clientX - g.x, e.clientY - g.y);
    if (!g.active) { if (distance > 10) cancel(); return; }
    e.preventDefault();
    if (distance > 8) g.moved = true;
    if (!g.moved) return;
    g.box.classList.add("dragging");
    const rect = g.grid.getBoundingClientRect();
    if (g.resizing) {
      const [w, h] = dimensions(g.start);
      const width = w + (e.clientX - g.x) / g.stepX, height = h + (e.clientY - g.y) / g.stepY;
      const [minW,minH] = minimumSize(g.item);
      g.next = { ...g.start, size: `${Math.max(minW,Math.round(width))}x${Math.max(minH,Math.round(height))}` };
    } else {
      g.next = { ...g.start, x: Math.round((e.clientX - rect.left - g.grabX) / g.stepX),
        y: Math.round((e.clientY - rect.top - g.grabY) / g.stepY) };
      g.box.style.transform = `translate(${e.clientX - g.x}px, ${e.clientY - g.y}px)`;
    }
    const valid = fits(g.next, g.others, g.cols);
    g.box.classList.toggle("invalid-drop", !valid);
    if (!g.marker) {
      g.marker = document.createElement("div");
      g.marker.className = "grid-drop-target";
      g.marker.setAttribute("aria-hidden", "true");
      g.grid.append(g.marker);
    }
    const [w, h] = dimensions(g.next);
    g.marker.hidden = !fits(g.next, [], g.cols);
    g.marker.classList.toggle("invalid", !valid);
    Object.assign(g.marker.style, { left: `${g.next.x * g.stepX}px`, top: `${g.next.y * g.stepY}px`,
      width: `${w * g.stepX - g.gapX}px`, height: `${h * g.stepY - g.gapY}px` });
    if (e.clientY > window.innerHeight - 70) window.scrollBy(0, 16);
    else if (e.clientY < 70) window.scrollBy(0, -16);
  });
  root.addEventListener("pointerup", (e) => {
    const g = gesture;
    if (!g || e.pointerId !== g.pointer) return;
    cancel();
    if (!enabled() || cols() !== g.cols) return;
    const choices = sizeChoices(g.item,g.cols);
    if (g.resizing && !g.moved) g.next = { ...g.start, size: choices[(choices.indexOf(g.start.size) + 1) % choices.length] };
    if (!g.resizing && !g.moved) return;
    suppressClick = true;
    if (!place(items(), g.cols, g.id, g.next)) error("That space is occupied or outside the grid. Move the tile or choose a smaller size.");
    render();
    const settled = root.querySelector(`[data-wid="${CSS.escape(g.id)}"]`);
    if (settled && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      settled.animate([{ opacity: .75, transform: "translateY(3px)" }, { opacity: 1, transform: "none" }],
        { duration: 200, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
    setTimeout(() => { suppressClick = false; }, 0);
  });
  root.addEventListener("pointercancel", cancel);
  root.addEventListener("lostpointercapture", cancel);
  root.addEventListener("click", (e) => {
    if (suppressClick) { e.preventDefault(); e.stopImmediatePropagation(); suppressClick = false; }
  }, { capture: true });
  root.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && gesture) { e.preventDefault(); cancel(); render(); return; }
    const directions = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const d = directions[e.key], box = e.target.closest(".layout-item"), resizing=e.target.hasAttribute("data-resize");
    if (!enabled() || !box || (!e.target.matches("[data-grip],[data-resize]") && e.target !== box) || !d) return;
    e.preventDefault();
    const id = box.dataset.wid, p = arrange(items(), cols()).get(id);
    const [w,h] = dimensions(p);
    const next = resizing ? {...p,size:`${w+d[0]}x${h+d[1]}`} : { ...p, x: p.x + d[0], y: p.y + d[1] };
    if (!place(items(), cols(), id, next)) error("Choose an empty space inside the grid and keep the minimum tile size.");
    render();
    const settled = root.querySelector(`[data-wid="${CSS.escape(id)}"]`);
    (settled?.querySelector(resizing ? "[data-resize]" : "[data-grip]") || settled)?.focus({preventScroll:true});
  });
  addEventListener("blur",cancel);
  return cancel;
}
