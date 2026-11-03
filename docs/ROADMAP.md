# Roadmap

Ideas, roughly in priority order. Each is a good first issue to claim — comment
on (or open) an issue before starting so work isn't duplicated.

## Next

- **Real-hardware testing** of every adapter (Globe/Tuya, Govee plugs, Samsung,
  LG first). Report models that work in the README table.
- **Schedules** — run a scene or command at a time of day or at sunset/sunrise
  (service-layer feature + a "Schedules" settings page).
- **Energy history** — record `power_w` from plugs that report it (Tuya metering
  plugs, Shelly) and show a simple daily graph.

## Adapters

- **Home Assistant adapter** — connect to an existing Home Assistant over its
  WebSocket API and expose its lights/switches/media players as HomePanel devices.
  Gives access to everything Home Assistant supports while keeping this UI.
- **Matter adapter** — talk to a local [matterjs-server](https://github.com/matter-js)
  (the successor of the archived python-matter-server). Newer Govee plugs and many
  2024+ devices speak Matter.
- Roku and Android TV / Google TV remotes.
- Sonos volume and play/pause.
- Yeelight, LIFX, Nanoleaf (all have local APIs).

## UI

- Drag to reorder tiles; pin favourites to the top.
- Weather and indoor temperature in the header.
- Per-room "All off" from the room tab (long-press).
- Optional PIN for Settings (the panel is reachable by anyone on the Wi-Fi).
- Backlight control on the official display (dim at night instead of showing the night clock).

## Presence and automations

- "All off when everyone leaves" using phone presence on Wi-Fi.
- Simple rules: "when the TV turns on after sunset, set the backlight to 20%".

## Reference material

- [home-assistant/core](https://github.com/home-assistant/core) (Apache-2.0)
  contains mature integrations for Tuya, LG webOS, Samsung TV, TP-Link, Govee,
  Shelly and WiZ built on the same libraries we use. Read them for edge cases.
  If you copy code, keep the Apache-2.0 notice on those files.
- Do not bundle brand logos (trademarks) or code from projects without a
  compatible license.
