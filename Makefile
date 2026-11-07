# Common tasks. Works on macOS, Linux and the Raspberry Pi.
# Windows: use the plain commands shown in README.md (or WSL).
PY ?= python3
VENV := .venv
BIN := $(VENV)/bin

.PHONY: help setup dev run test test-unit test-integration test-ui check-tests lint logs debug-bundle clean wt-new wt-get wt-list wt-demo wt-remove

help:            ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-13s %s\n", $$1, $$2}'

setup:           ## Create .venv and install everything (incl. test tools)
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt
	-$(BIN)/playwright install chromium

dev:             ## Run with pretend devices on http://localhost:8080 (auto-reload not needed)
	$(BIN)/python -m app.main --demo --debug

run:             ## Run against real devices on your Wi-Fi
	$(BIN)/python -m app.main --debug

test:            ## Final unit + integration pass (do not also run the separate suites)
	$(BIN)/python -m pytest -q tests/unit tests/integration

test-unit:       ## Fast tests: logic only, no network or browser
	$(BIN)/python -m pytest -q tests/unit

test-integration: ## Real server, simulated devices, and the UI in a browser
	$(BIN)/python -m pytest -q tests/integration

test-ui:         ## Only the browser UI tests
	$(BIN)/python -m pytest -q tests/integration/test_ui.py

check-tests:     ## Would CI accept this branch? (code changes need unit + integration tests)
	git fetch -q origin main && $(BIN)/python scripts/ci/check_tests_included.py --base origin/main

lint:            ## Check code style
	$(BIN)/ruff check app tests scripts

logs:            ## Follow the log file
	tail -f logs/homepanel.log

debug-bundle:    ## Make a .tar.gz of logs + system info for a bug report
	./scripts/collect-logs.sh

wt-new:          ## New branch from main in its own folder: make wt-new b=feature/x
	./scripts/dev/wt.sh new $(b)

wt-get:          ## Existing branch (e.g. a PR) in its own folder: make wt-get b=ui/glass-look
	./scripts/dev/wt.sh get $(b)

wt-list:         ## List worktree folders
	./scripts/dev/wt.sh list

wt-demo:         ## Native demo of a branch on a free port: make wt-demo b=ui/glass-look
	./scripts/dev/wt.sh demo $(b)

wt-remove:       ## Remove a branch's folder: make wt-remove b=ui/glass-look
	./scripts/dev/wt.sh remove $(b)

clean:           ## Remove caches (keeps your data/ and logs/)
	find . -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
