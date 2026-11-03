# Adding a device brand

Each brand is one module here that subclasses `DeviceAdapter`
(`app/core/adapter.py`). Nothing in the API, service or UI needs to change: the
Add-device screen, setup forms, controls and scenes all come from what your
adapter declares.

| Module | Brand | Transport | Library |
|---|---|---|---|
| `demo.py` | Pretend devices for `--demo` | in memory | — |
| `tuya.py` | Globe Electric, Feit, Gosund, any Smart Life | local TCP (Tuya protocol) | tinytuya |
| `govee.py` | Govee plugs (cloud) + LAN lights | HTTPS / local UDP | — |
| `kasa.py` | TP-Link Kasa, Tapo | local | python-kasa |
| `shelly.py` | Shelly Gen1/Gen2+ | local HTTP | — |
| `wiz.py` | WiZ bulbs | local UDP | — |
| `hue.py` | Philips Hue via bridge | local HTTP | — |
| `samsung_tv.py` | Samsung Tizen TVs | local WebSocket + REST, Wake-on-LAN | samsungtvws |
| `lg_tv.py` | LG webOS TVs | local WebSocket, Wake-on-LAN | aiowebostv |

`shelly.py` is the simplest complete example — copy it.

## Step by step

1. Create `app/adapters/mybrand.py`:

```python
from ..core.adapter import Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found, Kind, register
from ..core.net import http


@register
class MyBrandAdapter(DeviceAdapter):
    id = "mybrand"                      # stable, saved with each device — never rename
    name = "MyBrand"                    # shown on the Add-device screen
    brands = "MyBrand plugs and bulbs"  # what people will recognise
    kinds = (Kind.PLUG,)
    description = "Local control. No account needed."
    requires = ()                       # e.g. ("mybrandlib",) — missing = brand disabled, not a crash
    poll_interval = 10                  # seconds between refresh() calls
    account_fields = []                 # e.g. [Field("api_key", "API key", "password")]
    manual_fields = [Field("name", "Name", required=True), Field("ip", "IP address", required=True)]

    async def discover(self, timeout=6.0):
        # Find devices (broadcast, cloud list, subnet scan …). Return Found objects.
        return [Found(adapter=self.id, uid="AA:BB:CC:DD:EE:FF", name="Desk plug", kind=Kind.PLUG,
                      caps=[Cap.POWER], config={"ip": "192.168.1.50"}, detail="192.168.1.50")]

    def from_manual(self, values):
        if not values.get("ip"):
            raise AdapterError("IP address is required.")
        return Found(adapter=self.id, uid=values["ip"], name=values.get("name") or "MyBrand",
                     kind=Kind.PLUG, caps=[Cap.POWER], config={"ip": values["ip"]})

    async def refresh(self, device: Device) -> dict:
        s = await http("GET", f"http://{device.config['ip']}/status")
        return {"on": s["relay"]}

    async def command(self, device: Device, action: str, value=None):
        if action == Action.POWER:
            await http("GET", f"http://{device.config['ip']}/relay?on={int(value)}")
            return {"on": value}          # what changed — shown immediately in the UI
        raise AdapterError("Not supported")
```

2. Add `"mybrand"` to `MODULES` in `app/adapters/__init__.py`.
3. If you use a library, add it to `requirements.txt` and to `requires`.
4. Run `make test` — the contract tests in `tests/test_adapters.py` check every
   adapter's metadata automatically. Add a test with a fake device if you can
   (see `test_shelly_adapter_end_to_end`).
5. Add a row to the table above, the root README, and setup steps in `docs/DEVICE_SETUP.md`.

## The contract

| Method | Required | Notes |
|---|---|---|
| `refresh(device) -> dict` | yes | Current state. Raise `OSError`/`ConnectionError` if unreachable; the service marks it offline after 2 failures. |
| `command(device, action, value) -> dict` | yes | `action` is already validated and normalized (toggle is converted to power; numbers are clamped; colours are `{r,g,b}`). Return the changed state keys. |
| `discover() -> list[Found]` | for Search | `uid` must be stable (MAC or device ID) to prevent duplicates. Put secrets in `config` — they never reach the browser. |
| `from_manual(values) -> Found` | for "Add by IP" | Validate and raise `AdapterError` with a clear message. |
| `setup(device)` | optional | First connection. Raise `PairingRequired` if the person must approve something (TV prompts). You may update `device.config`, `device.caps`, `device.meta`. |
| `start()` / `stop()` | optional | Open/close shared sockets (see `govee.py`). |
| `run_account_action(id)` | optional | Buttons like "Connect to bridge" (see `hue.py`). |
| `forget(device)` | optional | Clean up tokens/connections when removed. |

### State keys the UI understands

`on`, `brightness` (1–100), `color` `{r,g,b}`, `color_temp` (Kelvin),
`color_mode` (`"color"` or `"temp"`), `volume` (0–100), `muted`, `app`,
`input`, `power_w`. Put lists of TV apps/inputs in `device.meta["apps"]` /
`["inputs"]` as `[{id, name}]`.

### Writing good error messages

They appear on the touch screen. Say what happened and what to do:
`"Wrong local key. Re-pairing the device in its app changes the key — search again."`,
not `"decrypt failed"`.
