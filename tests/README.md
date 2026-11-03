# tests/

Run everything with `make test` (pytest) or, with no extra tools installed,
`python -m unittest discover -s tests -t .`

| File | Covers |
|---|---|
| `test_service.py` | Service layer: middleware pipeline (validate, normalize, retry), commands, All off with `keep_on`, scenes (capture + run), adding devices, persistence and file permissions, events, secret masking. Includes a fake adapter showing a new brand plugs in without other changes. |
| `test_adapters.py` | Contract checks for every adapter's metadata, TV key mappings, Tuya colour maths, Govee capability parsing, colour helpers, the built-in HTTP client, and the Shelly adapter end-to-end against a simulated device. |
| `test_api.py` | Starts the real server in demo mode and calls the HTTP API: state has no secrets, commands and error codes, scenes, health, logs, static UI. |
| `test_features.py` | Sunrise/sunset maths, energy integration, presence events, schedules (fire once, day/window rules, validation, presence → all off), and the Home Assistant adapter against a simulated Home Assistant. |
| `test_ui.py` | Drives the touch UI in headless Chromium (Playwright): tap toggles, TV opens the remote, brightness slider, rooms, add flow, night clock, energy chart, creating a schedule. Skipped if Playwright isn't installed (`pip install playwright && playwright install chromium`). |

No test needs real devices or the internet. When you add an adapter, add a test
that runs it against a small fake server or fake library (see
`test_shelly_adapter_end_to_end`).
