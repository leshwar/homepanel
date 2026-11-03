# app/ — the server

```
app/
├── main.py            entry point: argument parsing, logging, Starlette app, request logging
├── api/
│   └── routes.py      API layer: every /api/v1 route. Calls HomeService only.
├── core/
│   ├── adapter.py     the DeviceAdapter interface + shared vocabulary (Kind, Cap, Action, Key)
│   ├── service.py     HomeService: registry, polling, commands + middleware, scenes, events
│   ├── store.py       saves devices/rooms/scenes/accounts/settings to data/homepanel.json
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
