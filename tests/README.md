# tests/

Two suites, in two folders. CI runs both on every pull request, and a pull
request that changes product code (`app/`, `web/`) **must add or change a test
in each folder** or it's rejected (see `scripts/ci/check_tests_included.py`).

```bash
make test-unit          # fast, no network or browser
make test-integration   # real server, simulated devices, real browser
make test               # both
python -m unittest discover -s tests -t .   # both, without pytest
```

## tests/unit/ — logic in isolation

No sockets, servers or browsers. Milliseconds per test.

| File | Covers |
|---|---|
| `test_service.py` | Service layer: middleware (validate, normalize, retry), commands, All off with `keep_on`, scenes, adding devices, persistence and file permissions, events, secret masking. Includes a fake adapter proving a new brand plugs in without other changes. |
| `test_adapters.py` | Every adapter's metadata contract, TV key mappings, LG sound bar wire format and state parsing, Tuya color maths, Govee capability parsing, color helpers. |
| `test_geolocate.py` | "Use my location" against faked lookup services: parsing each service, place names, rounding before sending, fallback order, offline and rate-limited errors. |
| `test_layout.py` | The Home page layout: the default (clocks for India and the US, device shortcuts), what a saved layout may contain, saving it in settings, the Sky default. |
| `test_weather.py` | Weather for the resting clock against a fake source: parsing, opt-in, rounded location, caching, back-off and stale readings, place name and unit settings. |
| `test_automations_energy.py` | Sunrise/sunset maths, energy integration, presence events, schedules (fire once, day/window rules, validation, presence → all off), demo energy history. |
| `test_voice.py` | Voice commands: a table of sentences mapped to commands (power, rooms, numbers and percentages, colors, TV, sound bar, vacuum rooms, scenes, questions), synonyms and misspellings, "Which lamp?" choices that resolve, a yes before risky commands, unknown phrases, and the runner going through the service middleware. |
| `test_ci_policy.py` | The "tests included" pull-request rule itself. |

## tests/integration/ — parts working together for real

| File | Covers |
|---|---|
| `test_api.py` | The real server (demo mode) called over HTTP: state has no secrets, commands and error codes, scenes, automations, energy, settings validation, health, logs, static UI. |
| `test_fake_devices.py` | Real adapters over real sockets against simulated devices: the built-in HTTP client, a Shelly Gen2 plug, Home Assistant, and an LG sound bar (encrypted TCP). |
| `test_voice.py` | The `/voice` API on its own demo server (commands run, "Which lamp?" choices, a yes before everything off, unknown sentences, bad requests), and the voice sheet in Chromium with the browser's speech recogniser faked: the typed box, choices, confirm and cancel, the one-time privacy notice, live words, push-to-talk, falling back to typing when speech fails, and touch target sizes at iPhone, iPad and panel sizes. |
| `test_ui.py` | The touch UI in headless Chromium (Playwright): tap toggles, TV opens the remote, sound bar sound modes, brightness slider, rooms, add flow, night clock and each clock face (with weather from a fake source, and without), energy chart, creating a schedule, "Use my location" (mocked device location, approximate fallback, offline), the Home page (clocks, device widgets, rooms), editing it (hide, resize, move, save, cancel), the Sky following the weather, device icons, and the room rail / dock with no sideways scrolling at iPhone, iPad and panel sizes. Skipped locally if Playwright isn't installed; **required in CI**. |

Shared helpers (free port, running the demo server) live in `tests/helpers.py`.

## Writing tests for a change

- **New adapter:** unit tests for parsing/maths in `tests/unit/test_adapters.py`;
  an integration test that runs the adapter against a small fake device server in
  `tests/integration/test_fake_devices.py` (copy the Shelly or Home Assistant example).
- **Service / API change:** unit test against `HomeService` directly; integration
  test through the HTTP API in `test_api.py`.
- **UI change:** integration test in `test_ui.py` that taps through the flow.

No test may need real devices or the internet.
