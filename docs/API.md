# API reference (v1)

Base URL: `http://<panel>:8080/api/v1`. JSON in, JSON out. Errors return a
4xx/5xx status with `{"error": "message meant for people"}`.

The API is brand-agnostic: callers never need to know which adapter a device uses.

## Reading state

| Method | Path | Returns |
|---|---|---|
| GET | `/state` | Everything the UI needs: `devices`, `rooms`, `scenes`, `settings`, `adapters`, `demo` |
| GET | `/events` | Server-Sent Events stream (see below) |
| GET | `/health` | `{ok, uptime_s, devices, online, adapters, unavailable, demo}` |
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
| `key` | `UP DOWN LEFT RIGHT OK BACK HOME MENU SOURCE PLAY PAUSE STOP REWIND FORWARD` | remote |
| `launch_app` | app id from `meta.apps` | apps |
| `set_input` | input id from `meta.inputs` | inputs |
| `set_sound_mode` | sound mode id from `meta.sound_modes` (other ids are rejected) | sound_mode |

Returns the updated device. Example:

```bash
curl -X POST http://homepanel.local:8080/api/v1/devices/a1b2c3d4e5/command \
     -H 'Content-Type: application/json' -d '{"action":"brightness","value":40}'
```

`POST /all-off` with optional `{"room": "Kitchen"}` turns off everything that's on
(skipping devices marked `keep_on`). Returns `{"turned_off": n}`.

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
| PUT | `/settings` | `dim_after_seconds`, `clock_24h`, `home_name`, `temperature_unit`, `latitude`, `longitude`, `presence`, `background` (`ocean`/`aurora`/`night`), `glass_transparency` (0–100), `glass_effect` (blur on/off), `clock_face` (`digital`/`analog`/`words`/`date`/`night`), `place_name` (shown on the clock, max 40 characters), `weather_enabled` (opt-in), `temperature_unit` (`C`/`F`) |

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
