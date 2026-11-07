// Device pictures for tiles: the user's own photo, or a built-in illustration.
//
// Order: the photo uploaded for the device (Edit device → Picture), then, when the
// icon is left on "Auto", an illustration that matches what the device is (a TV,
// a TV backlight, a robot vacuum on its station…). Choosing an icon by hand keeps
// the simple line icon. Illustrations are inline SVG (no files, works offline);
// lights glow in their current color through var(--glow).

import { esc } from "./util.js";

const GLOW = "rgb(var(--glow, 255 196 120))";

const ART = {
  tv: `
    <defs><linearGradient id="a-tv" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#4a6cff"/><stop offset=".55" stop-color="#9b5cff"/><stop offset="1" stop-color="#ff6fb1"/></linearGradient></defs>
    <rect x="5" y="11" width="54" height="33" rx="3" fill="#0d1018" stroke="#3a4152" stroke-width="1.5"/>
    <rect x="8" y="14" width="48" height="27" rx="1.5" fill="url(#a-tv)" class="art-screen"/>
    <path d="M8 34c10-6 18 2 27-3s14-3 21 1v9H8z" fill="#fff" opacity=".12"/>
    <path d="M26 44h12l2 6H24z" fill="#3a4152"/><rect x="19" y="50" width="26" height="3" rx="1.5" fill="#545d72"/>`,
  "tv-backlight": `
    <defs><radialGradient id="a-bl" cx=".5" cy=".5" r=".6">
      <stop offset="0" stop-color="${GLOW}" stop-opacity=".95"/><stop offset="1" stop-color="${GLOW}" stop-opacity="0"/></radialGradient>
      <linearGradient id="a-rb" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#ff4d6d"/><stop offset=".25" stop-color="#ffb84d"/><stop offset=".5" stop-color="#5ee07a"/>
      <stop offset=".75" stop-color="#4f9bff"/><stop offset="1" stop-color="#b45cff"/></linearGradient></defs>
    <ellipse cx="32" cy="29" rx="31" ry="23" fill="url(#a-bl)" class="art-glow"/>
    <rect x="9" y="14" width="46" height="29" rx="3" fill="none" stroke="url(#a-rb)" stroke-width="2.5" class="art-strip"/>
    <rect x="11" y="16" width="42" height="25" rx="2" fill="#0d1018"/>
    <path d="M28 43h8l1.5 5h-11z" fill="#3a4152"/><rect x="21" y="48" width="22" height="2.5" rx="1.25" fill="#545d72"/>`,
  soundbar: `
    <defs><linearGradient id="a-sb" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#3b4254"/><stop offset="1" stop-color="#151922"/></linearGradient></defs>
    <rect x="3" y="26" width="58" height="13" rx="6.5" fill="url(#a-sb)"/>
    <g fill="#7d879c">${Array.from({ length: 13 }, (_, i) => `<circle cx="${10 + i * 3.7}" cy="32.5" r="1"/>`).join("")}</g>
    <rect x="28" y="36" width="8" height="1.2" rx=".6" fill="#7cc7a5" class="art-led"/>
    <path d="M14 22c3-3 6-3 9 0M41 22c3-3 6-3 9 0" stroke="#7d879c" stroke-width="1.6" fill="none" stroke-linecap="round" opacity=".6"/>`,
  speaker: `
    <defs><linearGradient id="a-sp" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#454c5e"/><stop offset="1" stop-color="#181c26"/></linearGradient></defs>
    <rect x="18" y="6" width="28" height="52" rx="9" fill="url(#a-sp)"/>
    <circle cx="32" cy="38" r="10" fill="#0d1018" stroke="#5d667a" stroke-width="1.5"/><circle cx="32" cy="38" r="4" fill="#3a4152"/>
    <circle cx="32" cy="18" r="5" fill="#0d1018" stroke="#5d667a" stroke-width="1.2"/>`,
  robot: `
    <defs><radialGradient id="a-rv" cx=".38" cy=".32" r=".8">
      <stop offset="0" stop-color="#ffffff"/><stop offset=".6" stop-color="#dfe4ee"/><stop offset="1" stop-color="#a9b2c4"/></radialGradient></defs>
    <ellipse cx="32" cy="50" rx="23" ry="4" fill="#000" opacity=".25"/>
    <circle cx="32" cy="32" r="23" fill="url(#a-rv)"/>
    <path d="M12 26a23 23 0 0 1 40 0" stroke="#8b94a8" stroke-width="2.5" fill="none"/>
    <circle cx="32" cy="27" r="7" fill="#2b3142"/><circle cx="32" cy="27" r="3" fill="#4f9bff" class="art-led"/>
    <path d="M24 44h16" stroke="#8b94a8" stroke-width="2" stroke-linecap="round"/>`,
  "robot-station": `
    <defs><linearGradient id="a-st" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#f6f8fc"/><stop offset="1" stop-color="#c9d0dd"/></linearGradient>
      <radialGradient id="a-rv2" cx=".38" cy=".32" r=".8">
      <stop offset="0" stop-color="#ffffff"/><stop offset=".6" stop-color="#dfe4ee"/><stop offset="1" stop-color="#a9b2c4"/></radialGradient></defs>
    <rect x="16" y="3" width="32" height="44" rx="5" fill="url(#a-st)"/>
    <rect x="20" y="8" width="24" height="12" rx="3" fill="#2b3142"/><rect x="23" y="11" width="18" height="2" rx="1" fill="#7cc7a5" class="art-led"/>
    <rect x="20" y="24" width="11" height="15" rx="2.5" fill="#dfe6f2" stroke="#aab3c4"/><rect x="33" y="24" width="11" height="15" rx="2.5" fill="#cfd9ea" stroke="#aab3c4"/>
    <ellipse cx="32" cy="57" rx="22" ry="3.5" fill="#000" opacity=".25"/>
    <ellipse cx="32" cy="50" rx="21" ry="8" fill="url(#a-rv2)"/>
    <ellipse cx="32" cy="47" rx="6" ry="2.6" fill="#2b3142"/>`,
  bulb: `
    <defs><radialGradient id="a-bu" cx=".5" cy=".42" r=".55">
      <stop offset="0" stop-color="#fff"/><stop offset=".45" stop-color="${GLOW}"/><stop offset="1" stop-color="${GLOW}" stop-opacity=".25"/></radialGradient></defs>
    <circle cx="32" cy="25" r="20" fill="${GLOW}" opacity=".18" class="art-glow"/>
    <path d="M32 6a17 17 0 0 0-10 30.7c2 1.6 3 3.6 3 6.3h14c0-2.7 1-4.7 3-6.3A17 17 0 0 0 32 6z" fill="url(#a-bu)" class="art-bulb"/>
    <rect x="25" y="44" width="14" height="4" rx="1.5" fill="#c9d0dd"/><rect x="25" y="49" width="14" height="4" rx="1.5" fill="#aab3c4"/>
    <path d="M28 55h8l-1.5 3h-5z" fill="#7d879c"/>`,
  lamp: `
    <defs><linearGradient id="a-la" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#f3e9d8"/><stop offset="1" stop-color="#d8c6a6"/></linearGradient></defs>
    <path d="M32 18L10 34h44z" fill="${GLOW}" opacity=".22" class="art-glow"/>
    <path d="M20 4h24l7 16H13z" fill="url(#a-la)"/>
    <path d="M14 20h36" stroke="${GLOW}" stroke-width="2" class="art-led"/>
    <rect x="31" y="20" width="2.5" height="34" fill="#7d879c"/><ellipse cx="32" cy="57" rx="12" ry="3" fill="#545d72"/>`,
  ceiling: `
    <path d="M32 2v14" stroke="#7d879c" stroke-width="1.5"/>
    <path d="M14 34a18 18 0 0 1 36 0z" fill="#2f3546"/>
    <ellipse cx="32" cy="38" rx="16" ry="10" fill="${GLOW}" opacity=".25" class="art-glow"/>
    <ellipse cx="32" cy="34" rx="7" ry="3" fill="${GLOW}" class="art-bulb"/>
    <path d="M10 46l-4 8M22 48l-2 9M42 48l2 9M54 46l4 8" stroke="${GLOW}" stroke-width="1.5" opacity=".5" stroke-linecap="round" class="art-glow"/>`,
  strip: `
    <defs><linearGradient id="a-ls" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#ff4d6d"/><stop offset=".25" stop-color="#ffb84d"/><stop offset=".5" stop-color="#5ee07a"/>
      <stop offset=".75" stop-color="#4f9bff"/><stop offset="1" stop-color="#b45cff"/></linearGradient></defs>
    <path d="M4 40c8-14 14-14 20 0s12 14 20 0 12-14 16 -4" stroke="url(#a-ls)" stroke-width="10" fill="none" opacity=".25" stroke-linecap="round" class="art-glow"/>
    <path d="M4 40c8-14 14-14 20 0s12 14 20 0 12-14 16 -4" stroke="url(#a-ls)" stroke-width="4" fill="none" stroke-linecap="round" class="art-strip"/>`,
  plug: `
    <defs><linearGradient id="a-pl" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#d3d9e4"/></linearGradient></defs>
    <rect x="14" y="8" width="36" height="46" rx="10" fill="url(#a-pl)"/>
    <rect x="23" y="22" width="3.5" height="10" rx="1.5" fill="#3a4152"/><rect x="37.5" y="22" width="3.5" height="10" rx="1.5" fill="#3a4152"/>
    <circle cx="32" cy="42" r="2.5" fill="#3a4152"/><circle cx="32" cy="14" r="1.8" fill="#7cc7a5" class="art-led"/>`,
  fan: `
    <circle cx="32" cy="26" r="20" fill="none" stroke="#7d879c" stroke-width="2"/>
    <g class="art-spin" style="transform-origin:32px 26px">
      <path d="M32 26c-2-9 1-16 6-15s4 9-6 15zM32 26c9-2 16 1 15 6s-9 4-15-6zM32 26c2 9-1 16-6 15s-4-9 6-15zM32 26c-9 2-16-1-15-6s9-4 15 6z" fill="#c9d0dd"/></g>
    <circle cx="32" cy="26" r="3" fill="#545d72"/><path d="M32 46v10M22 58h20" stroke="#7d879c" stroke-width="2.5" stroke-linecap="round"/>`,
};

export const ART_NAMES = Object.keys(ART);

// Which illustration fits a device, from what it is and what it's called. null = use the line icon.
export function artName(d) {
  if (d.icon) return null;                              // an icon picked by hand wins
  const text = `${d.name || ""} ${d.meta?.model || ""}`.toLowerCase();
  switch (d.kind) {
    case "tv": return "tv";
    case "speaker": return /speaker|stereo/.test(text) && !/sound ?bar/.test(text) ? "speaker" : "soundbar";
    case "vacuum": return d.caps?.includes("station") || /omni|station|dock/.test(text) ? "robot-station" : "robot";
    case "fan": return "fan";
    case "light":
      if (/backlight|tv|monitor|behind/.test(text)) return "tv-backlight";
      if (/strip|led|rgbic|neon|rope/.test(text)) return "strip";
      if (/lamp/.test(text)) return "lamp";
      if (/ceiling|pendant|chandelier/.test(text)) return "ceiling";
      return "bulb";
    case "plug": case "switch":
      return /fan/.test(text) ? "fan" : /tv/.test(text) ? "tv" : /speaker/.test(text) ? "speaker" : "plug";
    default: return null;
  }
}

// Each drawing gets its own gradient ids: many tiles are on screen at once, and a
// light's gradient uses that tile's own --glow color.
let seq = 0;
export function artSvg(name, cls = "", scope = "") {
  if (!ART[name]) return "";
  const n = scope ? `s-${[...scope].map(c => c.codePointAt(0).toString(16)).join("-")}` : ++seq;
  const body = ART[name].replace(/(id="|url\(#)(a-[\w-]+)/g, `$1$2-${n}`);
  return `<svg class="art ${cls}" viewBox="0 0 64 64" aria-hidden="true">${body}</svg>`;
}

// What goes in a tile's picture spot: {html, kind: "photo"|"art"} or null for the line icon.
export function devicePicture(d, scope = "") {
  if (d.picture_url) {
    const png = /\.png(\?|$)/i.test(d.picture_url.split("v=")[1] || "");
    return { kind: "photo", html: `<img class="dev-photo ${png ? "cutout" : ""}" src="${esc(d.picture_url)}" alt="" loading="lazy" draggable="false">` };
  }
  const name = artName(d);
  return name ? { kind: "art", html: artSvg(name, "", scope) } : null;
}
