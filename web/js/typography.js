export const FONT_SIZES = ["small", "medium", "large"];
export const FONT_SIZE_NAMES = { small: "Small", medium: "Medium", large: "Large" };

let saved = "medium", preview = null;
function valid(size) {
  if (size == null) return "medium";
  if (FONT_SIZES.includes(size)) return size;
  console.warn("Unknown font size; using Medium.");
  return "medium";
}

export function applyTypography(size = saved) {
  saved = valid(size);
  document.documentElement.dataset.fontSize = preview || saved;
}

export function previewTypography(size = null) {
  preview = size == null ? null : valid(size);
  applyTypography();
}
