// Device and room icons, drawn as inline SVG (no icon font, works offline).
//
// A device's icon is, in order: the icon picked for it (device.icon), a guess from
// its name ("Floor lamp" → lamp, "Kettle plug" → kettle), then its kind. Names are
// whatever the user typed, so this stays brand-neutral.

const P = {
  bulb: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1.1 2V16h5v-.2c.1-.8.5-1.5 1.1-2A6 6 0 0 0 12 3z"/>',
  lamp: '<path d="M8 3h8l3.2 7.5H4.8L8 3zM12 10.5V20M8 20.5h8"/>',
  ceiling: '<path d="M12 2.5V6M5 12a7 7 0 0 1 14 0H5zM9.6 15.2a2.4 2.4 0 0 0 4.8 0M7.2 18.5l-1 1.5M16.8 18.5l1 1.5M12 19.5V21"/>',
  strip: '<path d="M3 15c2.5-4.5 4.5-4.5 6 0s3.5 4.5 6 0 3.5-4.5 6 0"/><path d="M5.5 8v.01M12 6v.01M18.5 8v.01" stroke-width="3"/>',
  plug: '<rect x="4.5" y="3.5" width="15" height="17" rx="4.5"/><path d="M9.5 9.5v3M14.5 9.5v3M12 16v.5"/>',
  switch: '<rect x="6" y="2.5" width="12" height="19" rx="2.5"/><rect x="9.5" y="6" width="5" height="7" rx="1.5"/>',
  tv: '<rect x="2.5" y="4" width="19" height="12.5" rx="2"/><path d="M12 16.5V20M8 20.5h8"/>',
  fan: '<circle cx="12" cy="12" r="1.6"/><path d="M12 10.4C12 6 13 3 15.5 3S19 6 12 10.4zM13.6 12c4.4 0 7.4 1 7.4 3.5S18 19 13.6 12zM12 13.6c0 4.4-1 7.4-3.5 7.4S5 18 12 13.6zM10.4 12C6 12 3 11 3 8.5S6 5 10.4 12z"/>',
  speaker: '<rect x="6" y="2.5" width="12" height="19" rx="3"/><circle cx="12" cy="14.5" r="3.2"/><path d="M12 7v.01" stroke-width="3"/>',
  soundbar: '<rect x="2" y="9" width="20" height="6.5" rx="3.25"/><path d="M6 12.25v.01M9.5 12.25v.01M14.5 12.25v.01M18 12.25v.01" stroke-width="2.6"/>',
  kettle: '<path d="M7 9.5h9l1.6 10.5H5.4L7 9.5zM8.6 9.5l.9-4h4l.9 4M16.3 11.6l2.4-1.4 1 4.3-2.3 1.2M11.5 3.5h0"/>',
  fridge: '<rect x="6" y="2.5" width="12" height="19" rx="2"/><path d="M6 9.5h12M9 5.5v1.6M9 12.5v3.5"/>',
  vacuum: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="9" r="2.2"/><path d="M6.5 15.5h11"/>',
  heater: '<rect x="4" y="4.5" width="16" height="12.5" rx="2"/><path d="M8 8v5.5M12 8v5.5M16 8v5.5M7 20.5h10"/>',
  ac: '<rect x="3" y="4.5" width="18" height="8.5" rx="2"/><path d="M6.5 9.5h11M8 16c0 1.5 1 2 1 3.5M12 16v4M16 16c0 1.5-1 2-1 3.5"/>',
  coffee: '<path d="M4 8h13v6a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V8zM17 10h1.5a2.5 2.5 0 0 1 0 5H17M8 2.5v2.5M12 2.5v2.5"/>',
  washer: '<rect x="4.5" y="2.5" width="15" height="19" rx="2"/><circle cx="12" cy="13" r="4.5"/><path d="M8 6v.01M11 6v.01" stroke-width="2.6"/>',
  camera: '<rect x="2.5" y="6.5" width="13.5" height="11" rx="2.5"/><path d="M16 11l5.5-3v8L16 13"/>',
  lock: '<rect x="5" y="10.5" width="14" height="10" rx="2.5"/><path d="M8 10.5v-3a4 4 0 0 1 8 0v3M12 14.5V17"/>',
  blinds: '<path d="M3.5 3.5h17M5 3.5v14h14v-14M5 7.5h14M5 11.5h14M5 15.5h14M12 17.5v3"/>',
  router: '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 16.5v.01M10.5 16.5v.01" stroke-width="2.6"/><path d="M8.5 9.5a5 5 0 0 1 7 0M6 7a8.5 8.5 0 0 1 12 0"/>',
  purifier: '<rect x="6" y="2.5" width="12" height="19" rx="3"/><path d="M9 7h6M9 10.5h6M9 14h6"/>',
  power: '<path d="M12 3v8M6.4 6.6a8 8 0 1 0 11.2 0"/>',
  // rooms and navigation
  home: '<path d="M3.5 11L12 4l8.5 7M5.5 9.5V20h4.5v-5.5h4V20h4.5V9.5"/>',
  all: '<rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/>',
  other: '<path d="M3.5 7.5L12 3l8.5 4.5v9L12 21l-8.5-4.5v-9zM3.5 7.5L12 12l8.5-4.5M12 12v9"/>',
  sofa: '<path d="M5 10.5V8a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v2.5M3.5 10.5A1.5 1.5 0 0 1 5 12v2h14v-2a1.5 1.5 0 0 1 3 0v6H2v-6a1.5 1.5 0 0 1 1.5-1.5zM4.5 18v2M19.5 18v2"/>',
  bed: '<path d="M3 19V6M3 13.5h18V19M21 13.5a2.5 2.5 0 0 0-2.5-2.5H13v2.5M5.5 11h4a1.5 1.5 0 0 1 1.5 1.5v1"/>',
  pot: '<path d="M4.5 10h15v5.5a4.5 4.5 0 0 1-4.5 4.5H9a4.5 4.5 0 0 1-4.5-4.5V10zM2 10h20M9.5 7c0-1.2 1-1.6 1-3M13.5 7c0-1.2 1-1.6 1-3"/>',
  bath: '<path d="M3 12h18v2a5 5 0 0 1-5 5H8a5 5 0 0 1-5-5v-2zM6 12V5.5a2 2 0 0 1 2-2h.5a2 2 0 0 1 2 2M7 19l-1 2M17 19l1 2"/>',
  desk: '<path d="M3 9.5h18M5 9.5V20M19 9.5V20M14 9.5V15h5M9 4.5h6v5H9z"/>',
  car: '<path d="M5 15.5V11l2-4.5h10l2 4.5v4.5M3 15.5h18v3H3zM6.5 18.5V20M17.5 18.5V20"/><path d="M7 13v.01M17 13v.01" stroke-width="2.6"/>',
  plant: '<path d="M12 21v-8M12 13c0-4-3-6-7-6 0 4 3 6 7 6zM12 11c0-4 3-6 7-6 0 4-3 6-7 6zM8 21h8"/>',
  door: '<path d="M5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v17M3 21h18M15 12v.01" />',
  dining: '<path d="M7 3v6a2 2 0 0 0 2 2v10M11 3v6a2 2 0 0 1-2 2M9 3v5M16.5 21V3c-2 1.5-3 4-3 7h3"/>',
  star: '<path d="M12 3.5l2.6 5.3 5.9.9-4.2 4.1 1 5.8L12 16.9l-5.3 2.7 1-5.8-4.2-4.1 5.9-.9L12 3.5z"/>',
  // controls
  dots: '<path d="M6 12h.01M12 12h.01M18 12h.01" stroke-width="3.2"/>',
  pencil: '<path d="M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4"/>',
  resize: '<path d="M20 13v7h-7M20 20l-6.5-6.5"/>',
  hide: '<path d="M6 12h12"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
};

export const ICON_NAMES = Object.keys(P);
export const svg = (name, cls = "") =>
  `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[name] || P.power}</svg>`;

// Icons a user can pick for a device (Settings → device → Icon).
export const DEVICE_ICONS = ["bulb", "lamp", "ceiling", "strip", "plug", "switch", "tv", "soundbar", "speaker", "fan",
  "kettle", "fridge", "coffee", "heater", "ac", "purifier", "washer", "vacuum", "router", "camera", "lock", "blinds", "power"];

const KIND = { light: "bulb", plug: "plug", switch: "switch", tv: "tv", fan: "fan", vacuum: "vacuum",
               speaker: "soundbar", other: "power" };

// Checked in order; the first word found in the device's name wins.
const NAME_HINTS = [
  [/\b(tv|television)\b/, "tv"], [/sound ?bar/, "soundbar"], [/speaker|stereo/, "speaker"],
  [/kettle/, "kettle"], [/fridge|freezer/, "fridge"], [/coffee|espresso/, "coffee"],
  [/heater|radiator/, "heater"], [/\bac\b|air ?con|cooler/, "ac"], [/purifier|humidifier/, "purifier"],
  [/wash|dryer|laundry/, "washer"], [/vacuum|robot|mop/, "vacuum"], [/router|wi-?fi|modem/, "router"],
  [/camera|cam\b/, "camera"], [/lock|door/, "lock"], [/blind|shade|curtain/, "blinds"], [/\bfan\b/, "fan"],
  [/floor lamp|desk lamp|lamp/, "lamp"], [/ceiling|pendant|chandelier|downlight|spot/, "ceiling"],
  [/strip|backlight|\bled\b/, "strip"], [/light|bulb/, "bulb"],
];

export function deviceIconName(d) {
  if (d.icon && P[d.icon]) return d.icon;
  const name = String(d.name || "").toLowerCase();
  // A light's name decides only between light shapes; a plug's name says what's plugged in.
  for (const [re, ic] of NAME_HINTS) {
    if (!re.test(name)) continue;
    if (d.kind === "light" && !["lamp", "ceiling", "strip", "bulb"].includes(ic)) continue;
    if (d.kind === "tv" && ic !== "tv") continue;
    if (d.kind === "speaker" && !["speaker", "soundbar"].includes(ic)) continue;   // "TV sound bar" is still a sound bar
    if (d.kind === "vacuum" && ic !== "vacuum") continue;
    return ic;
  }
  return KIND[d.kind] || "power";
}
export const deviceIcon = (d, cls = "") => svg(deviceIconName(d), cls);

const ROOM_HINTS = [
  [/living|lounge|family|den|tv room/, "sofa"], [/bed|guest|master|nursery/, "bed"], [/kitchen|pantry/, "pot"],
  [/bath|toilet|shower|wc/, "bath"], [/office|study|desk/, "desk"], [/garage|car/, "car"],
  [/garden|yard|patio|balcony|porch|outside/, "plant"], [/dining/, "dining"], [/kid|play/, "star"],
  [/laundry|utility/, "washer"], [/hall|entry|stairs|landing/, "door"],
];
export function roomIconName(room) {
  if (room === "all") return "all";
  if (room === "") return "other";
  const name = String(room).toLowerCase();
  return (ROOM_HINTS.find(([re]) => re.test(name)) || [null, "door"])[1];
}
export const roomIcon = (room, cls = "") => svg(roomIconName(room), cls);
