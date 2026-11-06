# API reference (v1)

Base URL: `http://<panel>:8080/api/v1`. JSON in, JSON out. Errors return a
4xx/5xx status with `{"error": "message meant for people"}`.

The API is brand-agnostic: callers never need to know which adapter a device uses.

## Sign-in and profiles

Every route needs a signed-in session except `/auth/session`, `/auth/sign-in`,
`/auth/setup`, `/auth/sign-out` and a minimal `/health`. Without one you get
`401 {"error": "Sign in to use the panel.", "signin": true}` (`"setup": true` on the
first open after upgrading, `"locked": true` on a locked wall panel). A **member**
gets `403 {"error": "Only an admin can do that…"}` on admin-only routes, and a
device their profile can't see answers `404` exactly like one that doesn't exist.

The session is a cookie (`hp_session`: random, HttpOnly, SameSite=Strict, Secure
over HTTPS), stored on the panel only as a hash. Browsers stay signed in for 30
days after they're last used; the wall panel for about a year.

| Method | Path | Body / result |
|---|---|---|
| GET | `/auth/session` | `{signed_in, auto, setup, locked, panel, me, profiles, display, demo}`. `profiles` is the picker: `{id, name, initial, color, has_pin, has_password}` (no emails). `display` is the panel's look (background, clock face…) for the sign-in screen; it has the location only for a signed-in screen or the wall panel |
| POST | `/auth/sign-in` | `{"profile_id", "pin"}`, `{"profile_id", "password"}` or `{"email", "password"}`; admins may add `"panel": true` (this screen is the wall panel). Sets the cookie; returns the same as `/auth/session`. Wrong: 401. Too many tries (8 in 15 minutes per address and per profile): 429 with `Retry-After` |
| POST | `/auth/setup` | First open after upgrading only: `{"pin"}` or `{"email", "password"}`, optional `name`, `panel`. Protects the Owner profile and signs in |
| POST | `/auth/sign-out` | `{}` ends this browser's session. On the wall panel it locks instead (back to the profile picker); `{"forget": true}` really signs it out |
| POST | `/auth/lock` | Lock this screen now (the wall panel does this after `lock_after_minutes` idle). A locked panel can still read `/weather`, `/sun` and `/photos` for its resting clock and photo frame |
| POST | `/auth/panel` | admin: `{"panel": true}` makes this screen the wall panel, `false` makes it an ordinary browser |
| GET | `/profiles` | admin: `{"profiles": [{id, name, initial, color, email, role, devices, has_pin, has_password, custom_layout}]}` |
| POST | `/profiles` | admin: `{name, color?, email?, role: "admin"\|"member", pin?, password?, devices: "all"\|[device ids]}`. Needs a PIN (4–6 digits) or a password (8+ characters, with an email) |
| PATCH | `/profiles/{id}` | admin: any of the above. `pin`/`password`: a value sets it, `""` keeps it, `null` removes it. The panel always keeps one admin with a PIN or password |
| DELETE | `/profiles/{id}` | admin: removes the profile and signs out its screens (not your own) |
| PATCH | `/profiles/me` | your own `name`, `color`, `email`, `pin`, `password` |
| PUT | `/profiles/me/layout` | `{"home_layout": {...}}` your own Home page (see below); `null` = back to the default |

PINs and passwords are hashed with scrypt; they are never returned or logged.
`GET /state` adds `me` (your profile) and, for admins, `profiles`. For a member it
lists only their devices and the scenes made of them, and leaves out `adapters`,
`automations`, `presence` and `settings.presence`.

Members may: `GET /state`, `/events`, `/weather`, `/sun`, `/photos`, `/wallpapers`, the
energy, map and picture of their devices; `POST` commands and refresh to their devices, `/all-off` (their
devices only), `/scenes/{id}/run` (scenes made of their devices), `/auth/lock`; and
change their own profile and layout. Everything else is for admins.

Demo mode (`--demo`) doesn't ask anyone to sign in: requests without a session act
as the Owner. Add `--sign-in` (or `HOMEPANEL_SIGN_IN=1`) to try it like a real panel:
Owner's PIN is `1234` (or `owner@example.com` / `homepanel`), Sam's is `2468`.

```bash
# sign in once, keep the cookie, then use the API as that profile
curl -c hp.txt -X POST http://homepanel.local:8080/api/v1/auth/sign-in \
     -H 'Content-Type: application/json' -d '{"email":"me@example.com","password":"…"}'
curl -b hp.txt http://homepanel.local:8080/api/v1/state
```

## Reading state

| Method | Path | Returns |
|---|---|---|
| GET | `/state` | Everything the UI needs: `devices`, `rooms`, `scenes`, `settings`, `adapters`, `demo` |
| GET | `/events` | Server-Sent Events stream (see below) |
| GET | `/health` | `{ok, uptime_s, devices, online, adapters, unavailable, demo, in_container, phone_url}` signed in — `phone_url` is the address to open on a phone on the same Wi-Fi (`null` inside Docker, where it can't be known); just `{ok, time, sign_in}` without a session |
| GET | `/logs?level=WARNING` | Last 300 log records `{time, level, logger, message}` |
| GET | `/logs?format=text` | The full log file as a download |

A device looks like:

```json
{
  "id": "a1b2c3d4e5",
  "adapter": "tuya",
  "adapter_name": "Tuya / Smart Life",
  "name": "Desk lamp",
  "kind": "light",
  "room": "Office",
  "caps": ["power", "brightness", "color", "color_temp"],
  "keep_on": false,
  "state": {"online": true, "on": true, "brightness": 60, "color_temp": 2700, "color_mode": "temp"},
  "meta": {"model": "...", "apps": [{"id": "...", "name": "Netflix"}], "inputs": [...]},
  "pairing": false
}
```

## Controlling devices

`POST /devices/{id}/command` with `{"action": "...", "value": ...}`

| action | value | needs capability |
|---|---|---|
| `power` | `true` / `false` | power |
| `toggle` | — | power |
| `brightness` | 1–100 | brightness |
| `color` | `"#rrggbb"` or `{"r","g","b"}` | color |
| `color_temp` | Kelvin, e.g. `2700` | color_temp |
| `volume` | 0–100 | volume_level |
| `volume_up` / `volume_down` | — | volume |
| `mute` | `true` / `false` (omit to toggle) | mute |
| `channel_up` / `channel_down` | — | channel |
| `key` | `UP DOWN LEFT RIGHT OK BACK HOME MENU SOURCE PLAY PAUSE STOP REWIND FORWARD EXIT CHANNEL_LIST INFO` and the digits `0`–`9` | remote |
| `launch_app` | app id from `meta.apps` | apps |
| `set_input` | input id from `meta.inputs` | inputs |
| `clean` | `start` / `pause` / `resume` / `stop` | clean |
| `dock` | — (go back to the charging dock) | dock |
| `clean_rooms` | list of room ids from `meta.rooms`, e.g. `[1, 3]` | rooms |
| `set_suction` | id from `meta.suction_levels` | suction |
| `set_clean_mode` | id from `meta.clean_modes` (vacuum, mop, both…) | clean_mode |
| `station` | id from `meta.station_actions` (e.g. `empty_dustbin`) | station |
| `locate` | — (plays a sound) | locate |
| `set_sound_mode` | sound mode id from `meta.sound_modes` (other ids are rejected) | sound_mode |
| `pointer` | `{"dx": 12, "dy": -4}` to move, `{"click": true}` to click, `{"scroll": 40}` to scroll (positive = down). Moves are clamped to ±400 per message. | pointer |
| `set_effect` | id from `meta.effects` (a scene, DIY scene or snapshot) | effects |
| `update_effects` | — (read the device's scene lists again; they're cached) | effects |
| `set_music` | `{"mode": id from meta.music_modes, "sensitivity": 0–100}` (a bare mode id works; sensitivity defaults to 50) | music |
| `set_segments` | `{"segments": [0, 1, 2], "color": "#rrggbb"}` and/or `"brightness": 0–100`; parts are numbered from 0 to `meta.segments − 1` | segments |
| `set_toggle` | `{"id": id from meta.toggles, "on": true}` (`night_light`, `gradient`, `sync`) | toggles |

### Light effects

Lights that can play effects list them in `meta`, and the state says which one is showing:

```jsonc
"caps": ["power", "brightness", "color", "color_temp", "effects", "music", "segments", "toggles"],
"meta": {
  "effects": [{"id": "scene:129:111", "name": "Sunset", "group": "Scenes"},     // group: Scenes | DIY | Snapshots
              {"id": "diy:8216931", "name": "Movie night", "group": "DIY"}],
  "music_modes": [{"id": "1", "name": "Energic"}, {"id": "2", "name": "Rhythm"}],
  "segments": 15,                                     // parts of an RGBIC strip that can be colored apart
  "toggles": [{"id": "gradient", "name": "Gradient"}, {"id": "sync", "name": "Screen sync"}],
  "hint": "Add your … API key …"                     // only when effects need something set up first
},
"state": {
  "color_mode": "effect",                             // color | temp | effect | music | segments
  "effect": "scene:129:111", "music": null, "segments": null,
  "toggles": {"gradient": true}
}
```

Effect ids are opaque: send back what `meta.effects` lists. Scene lists come from
the device's brand once and are cached; `update_effects` reads them again (for
example after making a DIY scene in the brand's app). They are never polled.

`GET /devices/{id}/map` returns the floor plan as an image (SVG for Ecovacs) for
devices with the `map` capability. The state key `map_rev` changes when the map
does, so add it to the URL to refresh the picture.

Returns the updated device. `pointer` commands don't change the device's state, so they
aren't broadcast as live events; the UI batches moves (one request in flight, every
~30 ms) so the TV's pointer follows a finger smoothly.

Example:

```bash
curl -X POST http://homepanel.local:8080/api/v1/devices/a1b2c3d4e5/command \
     -H 'Content-Type: application/json' -d '{"action":"brightness","value":40}'
```

`POST /all-off` with optional `{"room": "Kitchen"}` turns off everything that's on
(skipping devices marked `keep_on`). `{"room": ""}` means devices that aren't in a
room (shown as "Other" on the panel). Returns `{"turned_off": n}`.

## Voice commands

`POST /voice` with `{"text": "turn off the lamp and vacuum the kitchen"}` turns an
everyday sentence into commands and runs them through the same pipeline as
`/devices/{id}/command` (validation, logging, retries and any middleware rules).
The text comes from the browser's speech recognition or from typing; the server
never receives audio. Text over 300 characters is cut.

It understands, matched loosely against your real device, room, scene, app,
input, sound mode and vacuum room names (with synonyms like lamp/light,
telly/TV, robot/hoover/vacuum, and numbers as words or digits):

| Say | Does |
|---|---|
| "turn on the floor lamp", "kitchen lights off", "turn the lamp on and the TV off" | `power` |
| "turn off the living room" | that room's All off (skips `keep_on`); "turn on the kitchen" turns on its lights |
| "set the lamp to 30%", "dim the lamp", "make the backlight blue / warm white" | `brightness`, `color`, `color_temp` |
| "set the backlight to sunset", "set the TV backlight to the aurora scene" | `set_effect` (names from `meta.effects`) |
| "TV volume up", "volume 20", "mute the sound bar", "next channel", "pause the TV" | `volume`/`volume_up`, `mute`, `channel_up`, `key` |
| "open YouTube", "put on Netflix in the bedroom", "switch to HDMI 2", "cinema mode" | `launch_app`, `set_input`, `set_sound_mode` |
| "start the vacuum", "vacuum the kitchen and den", "mop the hall", "send the vacuum home", "set the vacuum to max", "empty the dustbin" | `clean`, `clean_rooms`, `set_clean_mode`, `dock`, `set_suction`, `station` |
| "run movie night", "good morning" | runs the scene |
| "turn everything off" | All off, after a yes |
| "what's on in the bedroom?", "is the kettle on?" | answers, changes nothing |

Response (always 200 unless the body has no `text`):

```jsonc
{
  "heard": "set the lamp to 30%",
  "understood": true,
  "say": "Which lamp?",                 // what to show or speak
  "done": [],                           // [{kind, device_id, action, value, target}] that ran
  "failed": [],                         // [{device_id, action, error}]
  "question": "Which lamp?",            // set when it could mean several things
  "choices": [{"label": "Floor lamp", "detail": "Living room", "text": "set the floor lamp to 30 percent"}],
  "confirm": ""                         // set when it needs a yes first
}
```

- **Choices:** send a choice's `text` back as a new `/voice` request.
- **Confirm:** "everything off" and turning off a device marked `keep_on` don't run
  until you send the same `text` again with `"confirm": true`.
- **Not understood:** `understood: false` and `say` explains, e.g. `I couldn't find “garage”.`
  When only part of a sentence is understood, that part runs and `say` mentions the rest.

## Managing devices

| Method | Path | Body |
|---|---|---|
| POST | `/discover` | — → `{"found": [{adapter, adapter_name, uid, name, kind, caps, detail, needs_pairing, added}], "searched": [adapter ids], "failed": [{adapter, adapter_name, error}], "needs_account": [{adapter, adapter_name}]}`. Searches every brand at once; brands that need an account first are listed, not searched. Add a result with `POST /devices` `{"adapter", "uid"}`. |
| POST | `/adapters/{adapter}/discover` | — → `{"found": [{uid, name, kind, caps, detail, needs_pairing, added}]}` |
| POST | `/devices` | `{"adapter", "uid"}` from discovery, **or** `{"adapter", "manual": {...fields}}`, plus optional `name`, `room` |
| PATCH | `/devices/{id}` | any of `name`, `room`, `icon`, `kind`, `keep_on` |
| DELETE | `/devices/{id}` | — |
| POST | `/devices/{id}/pair` | — (retry TV pairing; accept the prompt on the TV) |
| POST | `/devices/{id}/refresh` | — (poll now) |

## Brand accounts

| Method | Path | Body |
|---|---|---|
| GET | `/adapters/{adapter}/account` | → saved values (passwords masked as `••••••`) |
| PUT | `/adapters/{adapter}/account` | field values; a blank password keeps the saved one |
| POST | `/adapters/{adapter}/actions/{action}` | e.g. `hue` / `pair` |

## Rooms, scenes, settings

| Method | Path | Body |
|---|---|---|
| PUT | `/rooms` | `{"rooms": ["Living room", "Bedroom"]}` (order = display order) |
| POST | `/scenes` | `{"name", "icon", "actions": [{device_id, action, value}]}` **or** `{"name", "icon", "capture": [device ids]}` to save devices as they are now |
| DELETE | `/scenes/{id}` | — |
| POST | `/scenes/{id}/run` | — → `{"ok": n, "failed": [messages]}` |
| PUT | `/settings` | admin: `lock_after_minutes` (the wall panel locks after this idle time, 0 = never), `dim_after_seconds`, `clock_24h`, `home_name`, `temperature_unit`, `latitude`, `longitude`, `presence`, `background` (`sky` (default: follows the weather and time of day)/`ocean`/`aurora`/`night`), `home_layout` (the shared default Home page for profiles that haven't made their own, see below; `null` = the built-in default), `glass_transparency` (0–100), `glass_effect` (blur on/off), `clock_face` (`digital`/`analog`/`words`/`date`/`night`), `place_name` (shown on the clock, max 40 characters), `weather_enabled` (opt-in), `temperature_unit` (`C`/`F`) |

`home_layout` is one object per profile, the same on every screen that profile uses.
`GET /state` returns the signed-in profile's own one (save it with `PUT
/profiles/me/layout`), else the shared default from `PUT /settings`, else the built-in
default. There are no devices on Home: they're on the Rooms pages (All rooms, then one
page per room), which only list rooms with devices the profile can see.

```json
{"version": 2, "widgets": [
  {"id": "clock",   "type": "clock",   "size": "2x2", "hidden": false, "options": {}},
  {"id": "zone-in", "type": "zone",    "size": "1x1", "hidden": false, "options": {"tz": "Asia/Kolkata", "label": "India"}},
  {"id": "zone-us", "type": "zone",    "size": "1x1", "hidden": false, "options": {"tz": null, "label": "US"}},
  {"id": "rooms",   "type": "rooms",   "size": "2x2", "hidden": false, "options": {}}]}
```

Types: `clock`, `zone` (a clock for another place; `tz: null` = the screen's own zone
if it's in the US, else US Eastern), `weather`, `scenes`, `rooms` (each room opens its
page). Sizes are grid columns × rows: `1x1`, `2x1`, `2x2`. Up to 40 widgets; a bad
layout gets a 400 that says what's wrong. Version 1 layouts could also hold `device`
widgets: the server drops them when it starts (and from anything an older screen
saves), so nobody is left with an empty slot.

## Energy

`GET /devices/{id}/energy?days=7` (devices that report `power_w`) →

```json
{"days": [{"date": "2026-11-03", "kwh": 0.84}, ...], "today_kwh": 0.84, "week_kwh": 8.6,
 "power": [{"t": 1793700000, "w": 118.2}, ...]}
```

`power` is the last 24 hours in 15-minute averages (`w` is `null` where there's no data).

## Automations

| Method | Path | Body |
|---|---|---|
| GET | `/automations` | → `{"automations": [...]}` each with `next_run` (unix time or null) |
| POST | `/automations` | create/update (include `id` to update), see below |
| DELETE | `/automations/{id}` | — |
| POST | `/automations/{id}/run` | run it now |
| GET | `/sun` | today's `sunrise` / `sunset` (unix time) once a location is set |
| POST | `/location/lookup` | Find the home's location for Settings → "Use my location". Body `{latitude, longitude}` (from the browser) → only a place name is looked up; empty body → approximate location from the panel's internet address. Returns `{latitude, longitude, place_name, source: "device"\|"approximate"}` with coordinates rounded to 2 decimals. Saves nothing. 400 with a plain message when the services are offline or busy |
| GET | `/weather` | `{available, temperature, high, low, unit, condition, label, is_day, updated}`; `condition` is one of `clear`, `partly-cloudy`, `cloudy`, `fog`, `drizzle`, `rain`, `snow`, `storm`. `{available: false}` when weather is off, there's no location, or the source can't be reached. Fetched on the server and cached for 20 minutes |
| GET | `/presence` | `{"people": [{name, ip, home, last_seen}]}` |

```json
{
  "name": "Porch light at sunset",
  "enabled": true,
  "when": {"type": "time", "at": "07:00", "days": [0, 1, 2, 3, 4]},
  "do": {"type": "scene", "scene_id": "morning"}
}
```

`when` is one of `{"type":"time","at":"HH:MM","days":[0-6, 0 = Monday]}`,
`{"type":"sun","event":"sunset"|"sunrise","offset_min":-15}`, or
`{"type":"presence","event":"all_away"|"someone_home"}`.
`do` is one of `{"type":"scene","scene_id":...}`, `{"type":"all_off"}`, or
`{"type":"command","device_id":...,"action":"power","value":true}`.

Location and people are settings: `PUT /settings` with `latitude`, `longitude`,
and `presence: [{"name": "Asha", "ip": "192.168.1.23"}]`.

## Photo frame

| Method | Path | Body / result |
|---|---|---|
| GET | `/photos` | `{"photos": [{id, name, size, added, url}]}` newest first |
| POST | `/photos?name=IMG_1.jpg` | the image file itself as the body (`Content-Type: image/*`), one per request, max 30 MB; returns the stored photo |
| DELETE | `/photos/{id}` | — |
| GET | `/photos/{id}/image` | the image |

### Wallpapers and device pictures

Wallpapers are the user's own background pictures (Settings → Display and clock →
Wallpaper). Uploads take JPEG, PNG, WebP, GIF or TIFF (TIFF is converted to JPEG, or
PNG when it has transparency, since browsers can't show TIFF), are shrunk to at most
2560 px and lose their metadata.

| Method | Path | Body → Response |
|---|---|---|
| GET | `/wallpapers` | `{"wallpapers": [{id, name, size, added, width, height, url}]}` |
| POST | `/wallpapers?name=sky.tiff` | the image file as the body; returns the stored wallpaper (admins) |
| DELETE | `/wallpapers/{id}` | — (if it was the chosen one, the setting goes back to `"shuffle"`) (admins) |
| GET | `/wallpapers/{id}/image` | the image |
| PUT | `/devices/{id}/picture` | the image file as the body: the user's own photo for the device's tile, at most 512 px; a PNG with transparency stays PNG (admins) |
| DELETE | `/devices/{id}/picture` | — back to the built-in drawing (admins) |
| GET | `/devices/{id}/picture` | the image; a device's `picture_url` in `/state` points here when it has one |

Settings: `background` can be `"wallpaper"`; `wallpaper` is a wallpaper id or `"shuffle"`;
`wallpaper_every` is minutes per wallpaper when shuffling (0, 15, 60, 240 or 1440; 0 = a new
one each time a screen opens); `wallpaper_dim` darkens it, 0–80 %. `tile_style` is `"auto"` (light tiles on a dark background, dark
tiles on a light one, measured from the wallpaper itself), `"light"` or `"dark"`.

Photos are stored in `data/photos/`, rotated upright, resized to 2560 px on the
long side and saved without metadata (no GPS). Settings: `idle_screen`
(`clock`/`photos`), `frame_seconds`, `frame_shuffle`, `frame_clock`, `frame_night_clock`.

```bash
curl -X POST "http://homepanel.local:8080/api/v1/photos?name=beach.jpg" \
     -H "Content-Type: image/jpeg" --data-binary @beach.jpg
```

## Live events

`GET /events` is a Server-Sent Events stream. Each message is JSON:

- `{"type": "device", "device": {...}}` — one device changed
- `{"type": "layout"}` — devices, rooms, scenes, settings or profiles changed; reload `/state`
- `{"type": "automation", "name": "...", "result": "ok"}` — an automation just ran (admins only)

Each event is checked against the listener's profile as it's sent: device events only
for devices that profile can see. The stream ends when the session does, and when the
server shuts down or restarts (so a restart never waits on open panels); reconnect when
it ends — `EventSource` does this by itself, every 2 s (`retry: 2000`).

```js
const es = new EventSource("/api/v1/events");
es.onmessage = (m) => console.log(JSON.parse(m.data));
```
