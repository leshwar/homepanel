# app/ — the server

```
app/
├── main.py            entry point: argument parsing, logging, Starlette app, request logging
├── api/
│   ├── routes.py      API layer: every /api/v1 route. Calls HomeService only.
│   └── auth.py        sign-in middleware: session cookie → current_viewer; 401 / 403 / hidden device 404
├── core/
│   ├── adapter.py     the DeviceAdapter interface + shared vocabulary (Kind, Cap, Action, Key)
│   ├── service.py     HomeService: registry, polling, commands + middleware, scenes, events
│   ├── store.py       saves devices/rooms/scenes/accounts/profiles/settings to data/homepanel.json
│   ├── profiles.py    one-tap profiles, optional scrypt passwords, sessions (data/sessions.json), rate limits,
│   │                  the current viewer and what they may see
│   ├── layout.py      Home/room layout validation, responsive positions and overlap checks
│   ├── voice.py       voice commands: sentence → generic commands (rules today; Parser is the seam for others)
│   ├── automations.py schedules: time of day, sunrise/sunset, presence → scene / all off / command
│   ├── sun.py         sunrise/sunset calculation (no internet)
│   ├── presence.py    who's home, by checking family phones on the Wi-Fi
│   ├── history.py     power samples and kWh per day (SQLite in data/history.db)
│   ├── photos.py      photo frame library: uploads made screen-ready, stored in data/photos/
│   ├── net.py         dependency-free HTTP, UDP, SSDP, Wake-on-LAN and colour helpers
│   └── logs.py        console + rotating file (logs/) + in-memory buffer for the UI
└── adapters/          one module per brand — see adapters/README.md
```

## Rules of the road

1. **API → Service → Adapter.** Routes never import adapters; adapters never
   import routes or the service. The service is the only bridge.
2. **The API speaks the generic vocabulary** (`Action`, `Cap`, `Key` in
   `core/adapter.py`). If you need a new kind of command, add it there first,
   then teach the adapters that support it.
3. **Adapters own brand details.** IPs, keys, tokens and protocol quirks stay in
   `device.config` and the adapter module.
4. **Third-party libraries are imported inside adapter methods**, so a missing
   library only disables that brand (see `requires` on each adapter).
5. **Errors people will see** are raised as `AdapterError("plain-language message")`.
   Network errors (`OSError`, `ConnectionError`, timeouts) are retried once by the
   service, then shown as "didn't respond".
6. **Blocking libraries** (tinytuya, samsungtvws) run in `asyncio.to_thread` so the
   server never freezes.

## Running

```bash
python -m app.main --demo --debug     # pretend devices
python -m app.main                    # real devices
python -m app.main --help             # all options (host, port, data dir, logs dir)
```

Environment variables: `HOMEPANEL_HOST`, `HOMEPANEL_PORT`, `HOMEPANEL_DATA`, `HOMEPANEL_LOGS`.
