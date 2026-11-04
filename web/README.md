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
├── controls.css    device sheets: light pill and color wheel, TV remote, robot vacuum
├── auth.css        sign-in screens (picker, PIN pad, email, setup), avatars, the profile menu
└── js/
    ├── api.js      the ONLY file that calls the server (/api/v1) + live events
    ├── store.js    client state, optimistic commands, change notifications
    ├── util.js     escaping, icons, colors/glow, status text, toasts, storage
    ├── glass.js    glass transparency → CSS variable
    ├── app.js      the shell: room rail / dock / tabs, Rooms view, live updates, idle clock
    ├── auth.js     sign-in: profile picker, PIN pad, email + password, first-run setup, the
    │               profile button (switch / sign out) and the wall panel's idle lock
    ├── profiles.js Settings → Profiles and sign-in (admins) and Settings → Your profile
    ├── home.js     the Home page: widgets (clock, other places' clocks, weather, scenes, rooms,
    │               devices) and edit mode (hold to move, drag a corner to resize, hide, Done)
    ├── tiles.js    device tiles: tap = on/off, long-press or "…" = controls (+ haptics)
    ├── icons.js    inline SVG device and room icons; picks one from the device's name or kind
    ├── sky.js      weather from the server → html[data-sky] / [data-period] for the Sky background
    ├── sheet.js    bottom sheet: light controls and the TV remote
    ├── remote.js   TV and speaker remote: D-pad / touchpad / number pad, rockers, apps, pointer
    ├── vacuum.js   robot vacuum: map, status, main button, rooms, Options, Maintenance
    ├── photoframe.js  full-screen photo slideshow (crossfade, slow drift, touch to exit)
    ├── clockfaces.js  resting clock faces (digital, analog, words, date, night) + burn-in drift
    └── settings.js settings pages: add devices, edit, rooms, scenes, display, diagnostics
```

## Design

- **Sky.** The default background follows the weather outside (clear, partly cloudy,
  cloudy, fog, rain, snow, storm) and the time of day (dawn, day, dusk, night), with
  slow drifting clouds, rain, snow or stars. Weather is opt-in (Settings → Location and
  presence) and comes from the panel's own server; without it the sky follows the clock.
  Motion is transform-only and stops for "reduce motion".
- **Glass over a scene.** Or a static background (`.backdrop` in `index.html`:
  gradients plus soft SVG shapes; Ocean, Aurora or Night via `html[data-bg]`) sits
  behind frosted-glass tiles, sheets and buttons. Settings → Display has the
  background, a **Glass transparency** slider (sets `--glass-alpha`, see `js/glass.js`)
  and a **Frosted blur** switch (`html.glass`) for slow screens.
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
  pencil) to edit: widgets wiggle; hold and drag to move, drag a corner (or tap it) for
  Small / Wide / Large, "…" for more (and the time zone of a clock), "−" to hide, **Add**
  to bring widgets back or add devices; Cancel or Done. **Rooms**: device tiles by room.
- **Navigation.** iPad and the landscape panel (≥ 768 px): a rail down the left with
  Home and every room (vertical tabs). Phones and the portrait panel: a floating dock
  (Home, Rooms, Settings, +) and room tabs over the tiles.
- **Tap = do the obvious thing** (toggle). Long-press or "…" = full controls (with a
  short vibration where the browser supports it). TVs, and devices with no on/off like
  a robot vacuum, open their controls on tap so they're never switched by accident.
- **Icons.** Each device gets an icon from its name ("Floor lamp", "Kettle plug") or
  kind, or one picked in Settings → device → Icon.
- **iPhone and iPad.** `viewport-fit=cover` with `env(safe-area-inset-*)` padding,
  `100dvh` heights, no sideways scrolling, and "Add to Home Screen" tags. Checked at
  393×852 (iPhone 15 Pro), 820×1180 and 1180×820 (iPad Air), 720×1280 and 1280×720.
- **Animations** are short (150–300 ms) and only move or fade: tile press and "pop" when
  something turns on, tab and page switches, the sheet sliding in and out, edit-mode
  wiggle.
- **Room tabs.** A sticky bar with "All", one tab per room and "Other" (devices
  without a room); the number on a tab is how many things are on. Swipe the grid
  sideways to change tab; the chosen tab is remembered. Each room has a heading with
  what's on and a **Turn off** button for that room (the header's **All off** is
  always everything). "Other" nudges you to give its devices a room.
- **Portrait first** (Touch Display 2 is 720×1280): device tiles in 2 columns on a
  phone, 3 in portrait, 4–5 in landscape (they size to their column, not the window).
  Home widgets sit on a square grid of 2, 4 or 6 columns.
- Font: IBM Plex Sans (installed on the Pi by install.sh), falling back to Inter / system fonts.

Color tokens (`app.css`): `--night` page, `--dusk` surfaces, `--slate` controls,
`--paper` text, `--haze` secondary text, `--lamp` / `--jade` / `--indigo` "on"
colors, `--ember` warnings.

## How rendering works

`store.js` holds state and calls `emit()` on changes; `app.js` listens and
re-renders only what changed (a single tile for device updates). User actions go
through `store.command()`, which updates the tile instantly, calls the API, and
reverts with an error toast if it fails. Live updates from other screens and
phones arrive over Server-Sent Events.

## Device sheets

Tap a tile's arrow (or long-press) for full controls. A sheet shows only what the
device can do (its `caps`):

- *Lights*: a tall brightness pill (tap = on/off, drag = dim, relative like Apple Home),
  a color wheel (the rim snaps to pure colors), a warm-to-cool slider and a few presets.
  Dragging previews live, at most one command every 300 ms, and the final value always wins.
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
2. Render it in `sheet.js` (TVs: `remote.js`, vacuums: `vacuum.js`), guarded by the cap.
3. Send it with `command(d.id, "your_action", value, {optimistic state})`.
