# web/ — the touch UI

Plain HTML, CSS and JavaScript modules. No build step, no framework, no
internet needed at runtime — edit a file and reload the browser.

```
web/
├── index.html      page shell + the SVG icon set (<symbol id="i-…">)
├── app.css         all styles; design tokens at the top (:root)
├── controls.css    device sheets: light pill and color wheel, TV remote, robot vacuum
├── photoframe.css  photo frame slideshow and its settings
├── clockfaces.css  resting clock faces and the face picker previews
└── js/
    ├── api.js      the ONLY file that calls the server (/api/v1) + live events
    ├── store.js    client state, optimistic commands, change notifications
    ├── util.js     escaping, icons, colors/glow, status text, toasts, storage
    ├── glass.js    glass transparency → CSS variable
    ├── app.js      home screen: clock, scenes, rooms, device grid, idle night clock
    ├── sheet.js    bottom sheet: frame, light controls (brightness pill, color wheel, warm-to-cool)
    ├── remote.js   TV remote: D-pad / touchpad / number pad, rockers, app pages, batched pointer
    ├── vacuum.js   robot vacuum: map, status, main button, rooms, Options, Maintenance
    ├── photoframe.js  full-screen photo slideshow (crossfade, slow drift, touch to exit)
    ├── clockfaces.js  resting clock faces (digital, analog, words, date, night) + burn-in drift
    └── settings.js settings pages: add devices, edit, rooms, scenes, display, diagnostics
```

## Design

- **Glass over a scene.** A static background (`.backdrop` in `index.html`:
  gradients plus soft SVG shapes; Ocean, Aurora or Night via `html[data-bg]`) sits
  behind frosted-glass tiles, sheets and buttons. Settings → Display has the
  background, a **Glass transparency** slider (sets `--glass-alpha`, see `js/glass.js`)
  and a **Frosted blur** switch (`html.glass`) for slow screens.
- **Lit devices.** A device that is on gives off light: lamps glow in their real
  color, plugs in jade, TVs in indigo, and the background's top glow takes on the
  color of the lights that are on (`--room-glow`, `--warmth`).
- **Touch targets ≥ 48 px**, big sliders, no hover-only features.
- **Tap = do the obvious thing** (toggle). Long-press or the arrow = full controls.
  TVs open the remote on tap so they're never switched off by accident.
- **Portrait first** (Touch Display 2 is 720×1280), 4–5 columns in landscape.
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
