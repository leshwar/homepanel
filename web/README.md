# web/ — the touch UI

Plain HTML, CSS and JavaScript modules. No build step, no framework, no
internet needed at runtime — edit a file and reload the browser.

```
web/
├── index.html      page shell + the SVG icon set (<symbol id="i-…">)
├── app.css         base styles; design tokens at the top (:root)
├── shell.css       room rail, dock, top bar, Home widgets and edit mode, the Sky background
├── manifest.webmanifest, icon-*.png   "Add to Home Screen" (iPhone, iPad, Android)
├── photoframe.css  photo frame slideshow and its settings
├── clockfaces.css  resting clock faces and the face picker previews
├── voice.css       the voice sheet: big mic with a level ring, chat bubbles, typed box
├── controls.css    device sheets: light pill and color wheel, TV remote, robot vacuum
├── auth.css        profile picker, optional password form, avatars, the profile menu
└── js/
    ├── api.js      the ONLY file that calls the server (/api/v1) + live events
    ├── store.js    client state, optimistic commands, change notifications
    ├── render.js   unchanged-markup cache and in-place room count badges
    ├── util.js     escaping, icons, colors/glow, status text, toasts, storage
    ├── glass.js    glass transparency → CSS variable
    ├── app.js      the shell: room rail / dock / tabs, Rooms view, live updates, idle clock
    ├── auth.js     one-tap profiles, optional password sign-in, switch / sign out
    ├── profiles.js Settings → Profiles (admins) and Settings → Your profile
    ├── grid.js     shared responsive positions, collision checks, drag/resize and arrow keys
    ├── room-layout.js per-profile room tile layouts and their editor
    ├── home.js     the Home page: widgets (clock, other places' clocks, weather, scenes, rooms)
    │               and edit mode (hold to move, drag a corner to resize, hide, Done)
    ├── tiles.js    device tiles: tap = on/off, long-press or "…" = controls (+ haptics)
    ├── icons.js    inline SVG device and room icons; picks one from the device's name or kind
    ├── sky.js      weather from the server → html[data-sky] / [data-period] for the Sky background
    ├── weather-effects.js shared weather scenes and tile-only animation visibility
    ├── sheet.js    bottom sheet: light controls and the TV remote
    ├── voice.js    the mic: speech to text in the browser (or a typed box), reply, choices, confirm
    ├── remote.js   TV and speaker remote: D-pad / touchpad / number pad, rockers, apps, pointer
    ├── vacuum.js   robot vacuum: map, status, main button, rooms, Options, Maintenance
    ├── effects.js  light effects in the light sheet: searchable scenes (Scenes / DIY / Snapshots),
    │               music mode + sensitivity, strip parts (tap parts, then a color), toggles
    ├── photoframe.js  full-screen photo slideshow (crossfade, slow drift, touch to exit)
    ├── clockfaces.js  resting clock faces (digital, analog, words, date, night) + burn-in drift
    ├── locate.js   "Use my location": device location, else approximate from the server
    └── settings.js settings pages: add devices, edit, rooms, scenes, display, diagnostics
```

## Design

- **Sky.** The default background follows the weather outside (clear, partly cloudy,
  cloudy, fog, rain, snow, storm) and the time of day (dawn, day, dusk, night), with
  slow drifting clouds, rain, snow or stars. Weather is opt-in (Settings → Location and
  presence) and comes from the panel's own server; without it the sky follows the clock.
  Motion is transform-only and stops for "reduce motion".
- **Weather tile.** Sun rays or a moon/stars, clouds, rain, snow, fog and a gentle
  storm glow fill the tile behind high-contrast captions, independently of the
  chosen page background. Effects clip to the rounded tile at every size and
  never intercept touches. They pause offscreen, in background tabs and during
  editing; reduced motion uses a still scene. Unconfigured, loading and unavailable
  weather have explicit messages and no invented scene; unavailable weather has Retry.
- **Glass over a scene.** Or a static background (`.backdrop` in `index.html`:
  gradients plus soft SVG shapes; Ocean, Aurora or Night via `html[data-bg]`) sits
  behind frosted-glass tiles, sheets and buttons. Settings → Display has the
  background, a **Glass transparency** slider (sets `--glass-alpha`, see `js/glass.js`)
  and a **Frosted blur** switch (`html.glass`) for slow screens. Readability takes
  priority over making tiles completely clear: light tiles keep at least 72% backing
  (84% when on); dark wallpaper tiles keep at least 80% (86% when on). Offline tiles
  keep their backing too, with a disconnected icon and readable warning text rather
  than fading the whole tile. Labels and nested buttons use the tile's text colors,
  independently of the background-aware page title. Wallpaper rails also keep a
  minimum backing, and headings over the picture get a soft shadow.
- **Lit devices.** A device that is on gives off light: lamps glow in their real
  color, plugs in jade, TVs in indigo, and the background's top glow takes on the
  color of the lights that are on (`--room-glow`, `--warmth`).
- **Touch targets ≥ 48 px**, big sliders, no hover-only features.
- **Sign-in first.** `js/auth.js` asks `/auth/session` who is signed in before anything
  else loads. Signed out, `html[data-auth="out"]` hides the app and its data is wiped,
  so the last person's devices never show through the glass. Members get
  `html[data-role="member"]`, which hides shortcuts into admin-only settings (the server
  refuses them anyway). A 401 from any call fires `hp:signin` and the picker comes back.
- **Two pages.** **Home**: a grid of widgets, each profile's own, the same on every screen
  that profile uses (saved with `PUT /profiles/me/layout`, checked by `app/core/layout.py`). Long-press it (or the
  pencil) to edit: hold and drag into an empty grid cell, drag a corner (or tap it) for
  Small / Wide / Large, "…" for more (and the time zone of a clock), "−" to hide, **Add**
  to bring widgets back or add a clock; Cancel or Done. No devices on Home: the Rooms
  widget opens each room's page. **Rooms**: device tiles, All rooms (grouped by room) or
  one room at a time, titled with the room's name and with its own **Turn off**.
  **Edit tiles** in the room heading or Settings → Rooms opens the same placement
  and sizing controls. Arrow keys or the options menu move a tile one cell.
  Empty space stays empty; occupied or out-of-bounds placements are rejected.
  Room layouts save with `PUT /profiles/me/rooms/layout`, independently per profile.
- **Navigation.** iPad and the landscape panel (≥ 768 px): a rail down the left with
  Home, All rooms, then each room in the order set in Settings → Rooms (vertical tabs),
  and "Other" only when a device has no room. Phones and the portrait panel: a floating
  dock (Home, Rooms, Settings, +); Rooms shows the same list as tabs over the tiles.
  Only rooms with devices the signed-in profile can see are listed. The chosen room is
  remembered on each screen. Home has no repeated visible brand/page headings:
  its heading remains available to screen readers, with the status count and
  actions visible. Room page titles remain visible.
- **Tap = do the obvious thing** (toggle). Long-press or "…" = full controls (with a
  short vibration where the browser supports it). TVs, and devices with no on/off like
  a robot vacuum, open their controls on tap so they're never switched by accident.
- **Icons.** Each device gets an icon from its name ("Floor lamp", "Kettle plug") or
  kind, or one picked in Settings → device → Icon.
- **iPhone and iPad.** `viewport-fit=cover` with `env(safe-area-inset-*)` padding,
  `100dvh` heights, no sideways scrolling, and "Add to Home Screen" tags. Checked at
  320×568 through 393×852 (phones), 568×320 (phone landscape), 768×1024,
  820×1180, 1024×768 and 1180×820 (tablets), 720×1280 and 1280×720 (panels).
  The dock keeps a safe edge inset, long room names wrap, and short-screen rails
  scroll without shrinking their touch targets.
- **Animations** are short (150–300 ms) and only move or fade: tile press and "pop" when
  something turns on, tab and page switches, and the sheet sliding in and out.
- **Room tabs.** A sticky bar with "All", one tab per room and "Other" (devices
  without a room); the number on a tab is how many things are on. Swipe the grid
  sideways to change tab; the chosen tab is remembered. Each room has a heading with
  what's on and a **Turn off** button for that room (the header's **All off** is
  always everything). "Other" nudges you to give its devices a room.
- **Portrait first** (Touch Display 2 is 720×1280): Home and room tiles use 2, 4 or
  6 columns, stepping up when the content area reaches 600 or 960 px (after the
  sidebar and padding). `positions` keeps separate coordinates and sizes per
  column count. Unsaved sizes derive a non-overlapping layout without rewriting
  saved positions. Room cells are at least 160 px tall for readable device labels.
- Font: IBM Plex Sans (installed on the Pi by install.sh), falling back to Inter / system fonts.

Color tokens (`app.css`): `--night` page, `--dusk` surfaces, `--slate` controls,
`--paper` text, `--haze` secondary text, `--lamp` / `--jade` / `--indigo` "on"
colors, `--ember` warnings.

## How rendering works

`store.js` holds state and calls `emit()` on changes; `app.js` listens and
re-renders only what changed (a single tile for device updates). User actions go
through `store.command()`, which updates the tile instantly, calls the API, and
reverts with an error toast if it fails. Live updates from other screens and
phones arrive over Server-Sent Events. Navigation and Home room lists keep their
DOM nodes when their structure is unchanged; count badges update in place, preserving
focus and scroll. Updates to devices in another room don't rebuild the visible grid.

## Device sheets

Tap a tile's arrow (or long-press) for full controls. A sheet shows only what the
device can do (its `caps`):

- *Lights*: a tall brightness pill (tap = on/off, drag = dim, relative like Apple Home),
  a color wheel (the rim snaps to pure colors), a warm-to-cool slider and a few presets.
  Dragging previews live, at most one command every 300 ms, and the final value always wins.
  Lights that list effects add Scenes (search box, grouped Scenes / DIY / Snapshots, the
  playing one highlighted, Update list), Music (mode chips and a sensitivity slider), Strip
  parts (tap parts, then a color) and Options toggles (`effects.js`).
- *TV remote*: power, the TV's name with a "connected" dot, mute; a round D-pad with Menu,
  Input, Exit and List around it; a switch between D-pad, touchpad (TVs with `pointer`)
  and number pad; volume and channel rockers (hold to repeat), Home, Play/Pause, Back; and
  swipeable pages of apps then inputs. Fits a 393×852 phone without scrolling; two columns
  on big landscape screens. The touchpad sends pointer moves batched (one request in
  flight, ~30 ms apart): drag to move, tap to click, two fingers to scroll. On phones,
  **Aim** moves the pointer by tilting the phone (iOS asks for motion access first).
- *Speakers and sound bars* use the same sheet without remote keys: power, name and mute,
  a wide volume bar, then sound mode and input chips.
- *Robot vacuum*: map, status and battery, one main button (start, pause, keep cleaning,
  or clean the picked rooms), rooms as chips, Options (suction, mode, station jobs) and
  parts wear folded behind Maintenance.

## Adding a control for a new capability

1. Add the capability/action in `app/core/adapter.py` (`Cap`, `Action`).
2. Render it in `sheet.js` (TVs: `remote.js`, vacuums: `vacuum.js`, light effects: `effects.js`), guarded by the cap.
3. Send it with `command(d.id, "your_action", value, {optimistic state})`.
