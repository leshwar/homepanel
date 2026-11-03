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
│   lg_tv · demo                                               │
└──────────────────────────────────────────────────────────────┘
        app/core/net.py: shared HTTP/UDP/SSDP/Wake-on-LAN/color helpers
        app/core/store.py: JSON persistence (data/homepanel.json)
        app/core/logs.py: console + rotating file + in-memory log buffer
```

## The generic vocabulary

Every device is described the same way, whatever the brand:

| Concept | Values | Defined in |
|---|---|---|
| **Kind** — what it is | `light`, `plug`, `switch`, `tv`, `fan`, `other` | `Kind` |
| **Capabilities** — what it can do | `power`, `brightness`, `color`, `color_temp`, `volume`, `volume_level`, `mute`, `channel`, `remote`, `apps`, `inputs` | `Cap` |
| **Actions** — commands you can send | `power`, `toggle`, `brightness`, `color`, `color_temp`, `volume`, `volume_up/down`, `mute`, `channel_up/down`, `key`, `launch_app`, `set_input` | `Action` |
| **Keys** — remote buttons | `UP DOWN LEFT RIGHT OK BACK HOME MENU SOURCE PLAY PAUSE STOP REWIND FORWARD` | `Key` |
| **State** — current status | `online`, `on`, `brightness` (0-100), `color` `{r,g,b}`, `color_temp` (K), `color_mode`, `volume`, `muted`, `app`, `input`, `power_w` | free-form dict |

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

## Secrets

Adapter-private data (IPs, local keys, TV tokens) lives in `device.config` and
account keys in `store.accounts`, saved to `data/homepanel.json` (mode 600).
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

## Future directions

- **Matter adapter** talking to [matterjs-server](https://github.com/matter-js) (the
  successor of python-matter-server), for the growing number of Matter devices.
- **Home Assistant adapter** — control anything Home Assistant supports while
  keeping this UI.
- Schedules / automations (time-based scenes) as a service-layer feature.
