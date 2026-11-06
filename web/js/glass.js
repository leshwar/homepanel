// Glass look: how see-through tiles and panels are.
// 0 = more solid … 100 = more transparent. Sets --glass-alpha; readable tile
// surfaces apply their own minimum backing, even at the highest transparency.
export function applyTransparency(t) {
  const alpha = 0.92 - Math.max(0, Math.min(100, Number(t))) * 0.0085;
  document.documentElement.style.setProperty("--glass-alpha", alpha.toFixed(3));
}
