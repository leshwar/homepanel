// Small, owned DOM regions should survive unrelated live device updates. Keeping
// their nodes also keeps keyboard focus and a room/scene list's scroll position.
const markupByElement = new WeakMap();
export const invalidateMarkup = (el) => markupByElement.delete(el);

export function setMarkup(el, markup) {
  if (markupByElement.get(el) === markup) return false;
  el.innerHTML = markup;
  markupByElement.set(el, markup);
  return true;
}

// Counts change much more often than the navigation structure. Patch the badges
// instead of replacing the buttons under a finger or the keyboard focus.
export function updateRoomCounts(root, countFor) {
  root.querySelectorAll('[data-room-count]').forEach((badge) => {
    const n = countFor(badge.dataset.roomCount);
    const label = `${n} on`;
    badge.hidden = !n;
    if (badge.textContent !== String(n)) badge.textContent = String(n);
    if (badge.getAttribute('aria-label') !== label) badge.setAttribute('aria-label', label);
  });
}
