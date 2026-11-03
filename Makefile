# Common tasks. Works on macOS, Linux and the Raspberry Pi.
# Windows: use the plain commands shown in README.md (or WSL).
PY ?= python3
VENV := .venv
BIN := $(VENV)/bin

.PHONY: help setup dev run test test-ui lint logs debug-bundle clean

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

test:            ## Run all tests (UI tests are skipped if Playwright isn't set up)
	$(BIN)/python -m pytest -q

test-ui:         ## Run only the browser UI tests
	$(BIN)/python -m pytest -q tests/test_ui.py

lint:            ## Check code style
	$(BIN)/ruff check app tests

logs:            ## Follow the log file
	tail -f logs/homepanel.log

debug-bundle:    ## Make a .tar.gz of logs + system info for a bug report
	./scripts/collect-logs.sh

clean:           ## Remove caches (keeps your data/ and logs/)
	find . -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
