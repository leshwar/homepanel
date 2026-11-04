# Architecture

HomePanel is split into layers so that the UI and API stay the same no matter
how many device brands are added underneath.

```
┌──────────────────────────────────────────────────────────────┐
│ web/  Touch UI (HTML/CSS/JS modules, no build step)          │
│       talks only to /api/v1 via web/js/api.js                │
├──────────────────────────────────────────────────────────────┤
│ app/api/routes.py   API layer                                │
│   /api/v1/...  JSON + Server-Sent Events. Brand-agnostic.    │
├──────────────────────────────────────────────────────────────┤
│ app/core/service.py   Service layer (HomeService)            │
│   device registry · state cache · polling · scenes · rooms   │
│   accounts · event bus · command middleware pipeline         │
├──────────────────────────────────────────────────────────────┤
│ app/core/adapter.py   Adapter interface (DeviceAdapter)      │
│   discover() · setup() · refresh() · command()               │
│   shared vocabulary: Kind, Cap, Action, Key                  │
├──────────────────────────────────────────────────────────────┤
│ app/adapters/*.py   One adapter per brand/protocol           │
│   tuya · govee · kasa · shelly · wiz · hue · samsung_tv ·    │
│   lg_tv · lg_soundbar · home_assistant · demo                │
└──────────────────────────────────────────────────────────────┘
        app/core/voice.py: spoken/typed sentences → generic commands → HomeService (rules-based; swappable Parser)
        app/core/automations.py: schedules (time, sunrise/sunset, presence) → scenes/commands
        app/core/sun.py: sunrise/sunset maths (offline)
        app/core/presence.py: who's home, from phones on the Wi-Fi
        app/core/history.py: power samples → kWh per day (SQLite, data/history.db)
        app/core/net.py: shared HTTP/UDP/SSDP/Wake-on-LAN/color helpers
        app/core/store.py: JSON persistence (data/homepanel.json)
        app/core/profiles.py + app/api/auth.py: profiles, sign-in, sessions, who sees which device
        app/core/logs.py: console + rotating file + in-memory log buffer
```

## The generic vocabulary

Every device is described the same way, whatever the brand:

| Concept | Values | Defined in |
|---|---|---|
| **Kind** — what it is | `light`, `plug`, `switch`, `tv`, `fan`, `speaker`, `other` | `Kind` |
| **Capabilities** — what it can do | `power`, `brightness`, `color`, `color_temp`, `volume`, `volume_level`, `mute`, `channel`, `remote`, `media`, `apps`, `inputs`, `sound_mode`, `effects`, `music`, `segments`, `toggles` | `Cap` |
| **Actions** — commands you can send | `power`, `toggle`, `brightness`, `color`, `color_temp`, `volume`, `volume_up/down`, `mute`, `channel_up/down`, `key`, `launch_app`, `set_input`, `set_sound_mode`, `set_effect`, `update_effects`, `set_music`, `set_segments`, `set_toggle` | `Action` |
| **Keys** — remote buttons | `UP DOWN LEFT RIGHT OK BACK HOME MENU SOURCE PLAY PAUSE STOP REWIND FORWARD` | `Key` |
| **State** — current status | `online`, `on`, `brightness` (0-100), `color` `{r,g,b}`, `color_temp` (K), `color_mode`, `volume`, `muted`, `app`, `input`, `sound_mode`, `effect`, `music`, `segments`, `toggles`, `power_w` | free-form dict |

The UI draws controls purely from capabilities: a device with `brightness`
gets a slider; one with `remote` gets a D-pad. A new brand gets the full UI
for free by declaring its capabilities.

## A command, end to end

```
UI tap ──► POST /api/v1/devices/{id}/command {"action":"toggle"}
            │
            ▼  HomeService.command()
   mw_validate       known action? device has the capability? valid key?
   mw_normalize      toggle → power true/false, clamp 1-100, "#ff8000" → {r,g,b}
   mw_log            "Floor lamp power=False ok (102 ms)" → logs/homepanel.log
   mw_timeout_retry  10 s timeout, 1 retry on network errors
            │
            ▼  adapter.command(device, "power", False)   ← the only brand-specific step
            │
   returns changed keys {"on": false} → merged into state → event pushed to every open UI
   1.5 s later: adapter.refresh() confirms the real state
```

Custom middleware can be added without touching anything else:

```python
async def quiet_hours(ctx, call_next):
    if ctx.action == "volume_up" and is_night():
        raise AdapterError("Volume is limited at night")
    return await call_next(ctx)

service.use(quiet_hours)
```

## State and polling

- Each device has a poll loop running `adapter.refresh()` every `poll_interval`
  seconds (set per adapter; cloud APIs poll slowly to stay within limits).
- Two failed polls in a row mark the device offline with a readable error.
- State changes are pushed to browsers over Server-Sent Events (`/api/v1/events`).
  The UI also applies optimistic updates so taps feel instant, and reverts with
  an error message if the command fails.

## Profiles and sign-in

```
browser ──cookie hp_session──► app/api/auth.py (ASGI middleware, before every /api/ route)
                                 session → profile → Viewer → current_viewer (a contextvar)
                                 no session 401 · member on an admin route 403 · hidden device 404
                                     │
                                     ▼  HomeService reads current_viewer
                       snapshot(): only that profile's devices, scenes and Home layout
                       mw_access (first command middleware): hidden device → "not found"
                       events: each listener's filter re-checks its session per event
```

No viewer means the panel itself is acting (polling, automations): nothing is
filtered. Admins see everything; a member's profile lists `devices: "all"` or ids.
Each profile keeps its own `home_layout`; `settings.home_layout` is the shared
default for profiles that haven't made one. Sessions are random tokens kept only as
SHA-256 hashes in `data/sessions.json`; PINs and passwords are scrypt hashes. On the
first start after upgrading, an "Owner" admin is created with everything and the
UI asks for a PIN or password before anything else works. Demo mode without
`--sign-in` acts as the Owner when there's no session.

## Secrets

Adapter-private data (IPs, local keys, TV tokens) lives in `device.config` and
account keys in `store.accounts`, saved to `data/homepanel.json` (mode 600), along
with the profiles' PIN and password hashes (never returned by the API).
`config` is never included in API responses, and password-type account fields
come back masked. `data/` and `logs/` are git-ignored.

## Why these choices

- **Python** — the best-maintained open-source device libraries (tinytuya,
  python-kasa, aiowebostv, samsungtvws) are Python; Home Assistant uses the same ones.
- **Starlette + uvicorn** — small, async, fast to start on a Pi. FastAPI is
  built on Starlette; we don't need its extras.
- **Plain JS modules, no build step** — anyone can edit the UI with a text editor;
  nothing to compile on the Pi.
- **Server-Sent Events** instead of WebSockets — one-way updates are all the UI
  needs, and SSE reconnects automatically.
- **Libraries are optional** — each adapter declares `requires`; if a library
  is missing only that brand is disabled and Settings says how to install it.

## Automations, presence and energy

These are service-layer features, so they work for every brand automatically:

- `Automations` checks every 15 s whether a time or sunrise/sunset target has
  passed (within a 2-minute window, so a restart doesn't skip it) and runs the
  scene or command through `HomeService` — same middleware, logs and retries as a tap.
- `Presence` probes each person's phone every 30 s and raises `all_away` /
  `someone_home` after a 10-minute grace period; automations listen for those.
- `History` stores one power sample per minute per metering plug and integrates
  them into kWh per day.

See [ROADMAP.md](ROADMAP.md) for what's next (Matter, more adapters, UI ideas).
