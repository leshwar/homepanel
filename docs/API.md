# API reference (v1)

Base URL: `http://<panel>:8080/api/v1`. JSON in, JSON out. Errors return a
4xx/5xx status with `{"error": "message meant for people"}`.

The API is brand-agnostic: callers never need to know which adapter a device uses.

## Reading state

| Method | Path | Returns |
|---|---|---|
| GET | `/state` | Everything the UI needs: `devices`, `rooms`, `scenes`, `settings`, `adapters`, `demo` |
| GET | `/events` | Server-Sent Events stream (see below) |
| GET | `/health` | `{ok, uptime_s, devices, online, adapters, unavailable, demo, in_container, phone_url}` — `phone_url` is the address to open on a phone on the same Wi-Fi (`null` inside Docker, where it can't be known) |
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
| PUT | `/settings` | `dim_after_seconds`, `clock_24h`, `home_name`, `temperature_unit`, `latitude`, `longitude`, `presence`, `background` (`sky` (default: follows the weather and time of day)/`ocean`/`aurora`/`night`), `home_layout` (the Home page widgets, see below; `null` = the default), `glass_transparency` (0–100), `glass_effect` (blur on/off), `clock_face` (`digital`/`analog`/`words`/`date`/`night`), `place_name` (shown on the clock, max 40 characters), `weather_enabled` (opt-in), `temperature_unit` (`C`/`F`) |

`home_layout` is one object, the same for every screen. `GET /state` returns the
default (built from your devices) until someone saves one:

```json
{"version": 1, "widgets": [
  {"id": "clock",   "type": "clock",   "size": "2x2", "hidden": false, "options": {}},
  {"id": "zone-in", "type": "zone",    "size": "1x1", "hidden": false, "options": {"tz": "Asia/Kolkata", "label": "India"}},
  {"id": "zone-us", "type": "zone",    "size": "1x1", "hidden": false, "options": {"tz": null, "label": "US"}},
  {"id": "dev-lr-tv", "type": "device", "size": "2x1", "hidden": false, "options": {"device_id": "lr-tv"}}]}
```

Types: `clock`, `zone` (a clock for another place; `tz: null` = the screen's own zone
if it's in the US, else US Eastern), `weather`, `scenes`, `rooms`, `device`. Sizes are
grid columns × rows: `1x1`, `2x1`, `2x2`. Up to 40 widgets; a bad layout gets a 400
that says what's wrong.

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
- `{"type": "layout"}` — devices, rooms, scenes or settings changed; reload `/state`
- `{"type": "automation", "name": "...", "result": "ok"}` — an automation just ran

```js
const es = new EventSource("/api/v1/events");
es.onmessage = (m) => console.log(JSON.parse(m.data));
```
