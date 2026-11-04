# web/ — the touch UI

Plain HTML, CSS and JavaScript modules. No build step, no framework, no
internet needed at runtime — edit a file and reload the browser.

```
web/
├── index.html      page shell + the SVG icon set (<symbol id="i-…">)
├── app.css         all styles; design tokens at the top (:root)
├── photoframe.css  photo frame slideshow and its settings
└── js/
    ├── api.js      the ONLY file that calls the server (/api/v1) + live events
    ├── store.js    client state, optimistic commands, change notifications
    ├── util.js     escaping, icons, colors/glow, status text, toasts, storage
    ├── app.js      home screen: clock, scenes, rooms, device grid, idle night clock
    ├── sheet.js    bottom sheet: light controls and the TV remote
    ├── photoframe.js  full-screen photo slideshow (crossfade, slow drift, touch to exit)
    └── settings.js settings pages: add devices, edit, rooms, scenes, display, diagnostics
```

## Design

- **Dark room, lit devices.** The page is dark slate; a device that is on gives
  off light — lamps glow in their real color, plugs in jade, TVs in indigo.
  That glow is the one bold element; everything else stays quiet.
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

## Adding a control for a new capability

1. Add the capability/action in `app/core/adapter.py` (`Cap`, `Action`).
2. Render it in `sheet.js` → `render()` guarded by `has("your_cap")`.
3. Send it with `command(d.id, "your_action", value, {optimistic state})`.
