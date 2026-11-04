# Contributing

Thanks for helping! Bug reports from real hardware are just as valuable as code.

## Getting set up

```bash
git clone https://github.com/leshwar/homepanel.git
cd homepanel
make setup
make dev        # http://localhost:8080 with pretend devices
make test
```

Using Claude Code? It picks up [CLAUDE.md](CLAUDE.md) automatically, which
describes the layers and rules below.

## Where things go

| I want to… | Look at |
|---|---|
| Support a new brand | [app/adapters/README.md](app/adapters/README.md) |
| Change how a command is handled for every device | `app/core/service.py` (middleware) |
| Add an API endpoint | `app/api/routes.py` + [docs/API.md](docs/API.md) |
| Change the UI | [web/README.md](web/README.md) |
| Change the Pi installer | [scripts/README.md](scripts/README.md) |

## Working on several branches

Use git worktrees so each branch has its own folder: `./scripts/dev/wt.sh new feature/x`.
See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Workflow

`main` is protected: every change, including the owner's, goes through a pull
request, and CI must pass. Pull requests from anyone other than the owner also
need the owner's approval. Details: [docs/CI_AND_BRANCH_RULES.md](docs/CI_AND_BRANCH_RULES.md).

1. Open an issue first for bigger changes so we can agree on the approach.
2. Create a branch: `git checkout -b add-mybrand-adapter`.
3. Write the change **with tests in both folders** (below). Update docs alongside code.
4. Run `make lint`, `make test-unit`, `make test-integration` and `make check-tests`.
5. Push and open a pull request using the template; include screenshots for UI
   changes and the device models you tested for adapter changes.
6. CI runs lint, unit tests, integration tests and a Docker build. When it's green
   and approved, the owner merges. Merging to `main` publishes a new Docker image.

## Tests (required)

A pull request that changes anything under `app/` or `web/` is rejected unless
it also adds or changes:

- a **unit test** in `tests/unit/` (logic only, no network), **and**
- an **integration test** in `tests/integration/` (real server, simulated devices, or the UI in a browser).

Docs-only and script-only changes don't need tests. See [tests/README.md](tests/README.md)
for what goes where.

## Reporting a bug

Run `./scripts/collect-logs.sh` (or Settings → Diagnostics → Download log file)
and attach the result to a [bug report](../../issues/new?template=bug_report.md).
Include the device brand and model.

## Code of conduct

Be kind and constructive. Assume good intent, explain your reasoning, and help
newcomers.
