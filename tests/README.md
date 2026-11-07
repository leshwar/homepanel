# Tests

Keep coverage; avoid redundant runs and reading unrelated tests. CI requires a
change in **both** `tests/unit/` and `tests/integration/` for product changes
(`app/` or `web/`). The rule lives in `scripts/ci/check_tests_included.py`.

## Development and final validation

During development, run the smallest relevant selection:

```bash
.venv/bin/python -m pytest -q tests/unit/test_layout.py -k positions
.venv/bin/python -m pytest -q tests/integration/test_ui.py -k edit_home_page
```

Once the final revision is ready for merge, run one complete pass:

```bash
make lint
REQUIRE_UI_TESTS=1 make test
make check-tests
```

`make test` runs unit **and** integration tests. Do not also run `make test-unit`
and `make test-integration`, or repeat full suites after every edit/commit.
If something fails, fix it and rerun affected checks. Later product edits
invalidate affected results; rerun the full pass only for broad changes or
failures that need it. Required CI still checks the final PR revision before
merge; retain its Python compatibility matrix, browser checks and native startup
smoke coverage. CI is independent verification, not a reason to remove useful coverage.

`make test-unit`, `make test-integration` and `make test-ui` remain convenient
subset commands. `python -m unittest discover -s tests -t .` is an alternative
without pytest, not an additional required pass.

## Where to add or find coverage

| Area | Unit tests | Integration tests |
|---|---|---|
| Service, adapters and commands | `test_service.py`, `test_adapters.py`, feature-named files | `test_api.py`, `test_fake_devices.py` |
| Profiles and access | `test_profiles.py` | `test_auth.py` (HTTP and Chromium) |
| Tile placement and rendering | `test_grid.py`, `test_layout.py`, `test_ui_render.py` | `test_ui.py`, `test_auth.py` |
| Voice, weather, photos and other features | Relevant `test_<feature>.py` | `test_voice.py`, `test_ui.py`, `test_api.py` |
| UI contrast and lifecycle | `test_ui_tone.py`, `test_main.py` | `test_readability.py`, `test_shutdown.py` |
| Weather tile animation | `test_weather_effects.py`, `test_weather.py` | `test_weather_tile.py` (mocked conditions, sizes, reduced motion and error/retry states) |
| Typography | `test_typography.py`, `test_service.py` | `test_typography.py` (three positions, preview/cancel/save, shared scope, font fallback and responsive layouts) |
| Speaker controls | `test_speaker_ui.py`, `test_adapters.py` | `test_speaker_ui.py`, `test_fake_devices.py` (opaque panels, touch/mouse volume safety, metadata IDs and state reconciliation) |
| Shared device panels | `test_device_controls.py` | `test_device_controls.py`, `test_ui.py` (all device types, themes/font sizes, focus, grouped controls, canceled gestures and explicit unavailable/error states) |
| Private photo source | `test_remote_photos.py` | `test_remote_photos.py` (fake Immich HTTP, profile grants, privacy/membership filters, redirect rejection, masked setup and tile lifecycle) |
| Test-inclusion rule | `test_ci_policy.py` | CI enforces the rule on the PR diff |

Read the relevant test file rather than loading the whole suite for each change.
Unit tests use no sockets, servers or browsers. JS unit tests use Node.js with
small fakes, no npm packages. Node is a development dependency only.

Integration tests start real HomePanel servers on free loopback ports with
temporary data and simulated devices. Shared helpers are in `tests/helpers.py`;
adapter examples are in `tests/integration/test_fake_devices.py`. No test needs
real devices or internet access. Device fixtures in `tests/fixtures/` are useful
recorded shapes, not redundant suites.
These fixtures are internal test infrastructure, not user-facing demo apps.
Never point mutation tests at the canonical 8080 instance or its household data.
User-facing previews and screenshots come only from the actual deployed app.

Run `make setup` when dev dependencies are missing. Chromium tests can skip in a
minimal local environment, but **must not skip for final validation or CI**:
`REQUIRE_UI_TESTS=1` makes a missing browser/dependency fail explicitly.
