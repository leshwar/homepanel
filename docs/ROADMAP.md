# Roadmap

Ideas, roughly in priority order. Each is a good first issue to claim — comment
on (or open) an issue before starting so work isn't duplicated.

## Done

- Schedules: time of day, sunrise/sunset (computed offline), presence triggers.
- Energy history and 7-day chart for plugs that report watts.
- Presence: "all off when everyone leaves" using phones on the Wi-Fi.
- Home Assistant adapter (REST API, areas become rooms).

## Next

- **Real-hardware testing** of every adapter (Globe/Tuya, Govee plugs, Samsung,
  LG first). See [TESTING_WITH_DEVICES.md](TESTING_WITH_DEVICES.md).
- Home Assistant adapter: switch from polling to its WebSocket API for instant updates.
- Energy: monthly totals and an estimated cost (price per kWh setting).

## Adapters

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

## Automations

- Device-state triggers: "when the TV turns on after sunset, set the backlight to 20%".
- Conditions ("only if someone is home") and a vacation mode that randomises lights.

## Reference material

- [home-assistant/core](https://github.com/home-assistant/core) (Apache-2.0)
  contains mature integrations for Tuya, LG webOS, Samsung TV, TP-Link, Govee,
  Shelly and WiZ built on the same libraries we use. Read them for edge cases.
  If you copy code, keep the Apache-2.0 notice on those files.
- Do not bundle brand logos (trademarks) or code from projects without a
  compatible license.
