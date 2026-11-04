// Glass look: how see-through tiles and panels are.
// 0 = solid tiles … 100 = almost clear glass. Sets the --glass-alpha CSS variable.
export function applyTransparency(t) {
  const alpha = 0.92 - Math.max(0, Math.min(100, Number(t))) * 0.0085;
  document.documentElement.style.setProperty("--glass-alpha", alpha.toFixed(3));
}
