# Roadmap

Ideas, roughly in priority order. Each is a good first issue to claim — comment
on (or open) an issue before starting so work isn't duplicated.

## Done

- Schedules: time of day, sunrise/sunset (computed offline), presence triggers.
- Energy history and 7-day chart for plugs that report watts.
- Presence: "all off when everyone leaves" using phones on the Wi-Fi.
- Home Assistant adapter (REST API, areas become rooms).
- One-tap profiles with optional email/password, member device access, admin-only settings.
- Add to Home Screen icons and full-screen mode on phones and tablets.
- Weather widgets and weather-aware backgrounds/resting clocks (opt-in).
- Per-profile Home and room tiles: position in free grid space, resize, and save across screens.
- Room pages with their own Turn off button.
- Voice/typed commands, photo frame, wallpapers and device pictures.

## Phones and tablets (later)

Today any phone uses the panel as a web page. Ideas for later, in order:
- Optional phone approval/pairing with a code shown on the hub, in addition to
  the existing optional email/password sign-in.
- iPhone/iPad and Android apps (e.g. Capacitor wrapping the same web UI) that
  find the hub on the Wi-Fi.
- A guided setup for reaching the hub away from home (e.g. Tailscale/VPN).

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

## Photo frame sources

Photos are uploaded from a browser or copied into `data/photos/` today. Possible
additional sources, each as its own module next to `app/core/photos.py`:

- **Google Photos (Picker API).** Since March 31, 2025 Google no longer lets apps
  read a library or albums; apps can only receive photos the person picks in
  Google's own picker. A "Pick from Google Photos" button could open the picker on
  a phone and copy the chosen photos to the panel. Needs a Google Cloud project
  with OAuth set up.
- **Immich** (self-hosted Google Photos alternative) — has an API with albums, so
  a live "show this album" source is possible.
- **A USB stick**: show photos from a stick plugged into the Pi.
- **Shared folder** (Nextcloud / SMB) synced to `data/photos/`.

## UI

- Favourite-device shortcuts (Home and room tiles already support grid placement and resizing).
- Indoor temperature and an optional weather summary in the header.
- Per-room "All off" directly from the room tab (long-press); room pages already have Turn off.
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
