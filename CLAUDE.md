# CLAUDE.md — project guide for Claude Code

HomePanel is a touch-screen smart home panel for Raspberry Pi (Python server +
plain-JS web UI). Read `docs/ARCHITECTURE.md` before larger changes.

## Commands

```bash
make setup      # .venv + dev dependencies (+ Playwright Chromium)
make dev        # run with pretend devices: http://localhost:8080
make run        # run against real devices on this Wi-Fi
make test-unit         # tests/unit: logic only, no network
make test-integration  # tests/integration: real server, fake devices, browser UI
make test       # both, once on the final revision before merge
make check-tests  # PR rule: app/ or web/ changes need a unit AND an integration test
make lint       # ruff
make docker-demo  # demo in Docker → http://localhost:8081 (CI also builds and smoke-tests the image)
python -m unittest discover -s tests -t .    # tests without pytest
```

Logs: `logs/homepanel.log` (run with `--debug` for detail). In the UI: Settings → Diagnostics.

## Architecture rules (do not break)

- Layers: `web/` → `app/api/routes.py` → `app/core/service.py` → `app/core/adapter.py` → `app/adapters/*.py`.
- The API and UI are **brand-agnostic**. Never reference a specific adapter outside `app/adapters/`.
- New command types go into `Action`/`Cap`/`Key` in `app/core/adapter.py` first, then the adapters, then the UI.
- Cross-cutting behaviour (validation, limits, logging, retries) belongs in service middleware (`service.use()`), not in routes or adapters.
- Adapters import third-party libraries **inside methods** and list them in `requires`, so a missing library only disables that brand.
- Blocking libraries run in `asyncio.to_thread`.
- `device.config` and account data hold secrets: never return them from the API or log them.
- User-facing errors: `AdapterError("what happened and what to do")` in plain language.
- `web/js/api.js` is the only UI file that calls the server.
- No build step for the UI; no new frontend frameworks or CDN dependencies (the Pi may be offline).

## Working locally

Follow the `homepanel-dev` skill (`.claude/skills/homepanel-dev/SKILL.md`): the main
clone stays on `main`; each change gets a worktree from `scripts/dev/wt.sh new <branch>`.
See `docs/DEVELOPMENT.md`.

## Pull requests and tests

- Never push to `main`; work on a branch and open a PR. CI must be green.
- During development, run focused checks for the behavior being changed (for example,
  `.venv/bin/python -m pytest -q tests/unit/test_layout.py -k positions`).
  Do not run both full suites after every edit or commit. On the final revision,
  run `make lint`, `REQUIRE_UI_TESTS=1 make test`, and `make check-tests` once.
  Do not also run `make test-unit` and `make test-integration`: `make test` includes both.
  Fix failures and rerun affected checks; later product changes invalidate the
  affected results. Required CI still checks the final PR revision before merge.
- Every change to `app/` or `web/` must add/update a test in **both** `tests/unit/`
  and `tests/integration/` — CI rejects the PR otherwise. See `tests/README.md`.
- Tests must not need real devices or the internet; simulate devices with a small
  local server (see `tests/integration/test_fake_devices.py`).
- Read the relevant code and focused test files, not every test file or the entire
  documentation tree for each change. `tests/README.md` is the short test workflow.

## Adding a brand

Follow `app/adapters/README.md`. Copy `shelly.py`, register it in
`app/adapters/__init__.py`, add docs to `docs/DEVICE_SETUP.md` and the README
table, and add a test with a fake device.

## Testing with real devices

The cloud/CI environment can't reach anyone's home network. To test an adapter
against real hardware, run `make run` on a machine on the same Wi-Fi as the
device, watch `logs/homepanel.log`, and use `curl` against `/api/v1` (see `docs/API.md`).

## Style

- Python 3.11+, type hints where helpful, async everywhere in the server.
- UI copy: sentence case, plain verbs, say what will happen ("Add device", "Pair now").
- Keep touch targets ≥ 48 px; check portrait 720×1280 and landscape 1280×720.
- Update the relevant README when you change behaviour.
