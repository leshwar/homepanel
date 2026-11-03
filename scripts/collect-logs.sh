#!/usr/bin/env bash
# Bundles everything needed to debug a problem into one file you can attach to a
# GitHub issue. API keys and device tokens are NOT included.
#
#   ./scripts/collect-logs.sh            -> homepanel-debug-<date>.tar.gz
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${HOMEPANEL_PORT:-8080}"
OUT="homepanel-debug-$(date +%Y%m%d-%H%M%S)"
TMP="$(mktemp -d)/$OUT"
mkdir -p "$TMP"

cp "$APP_DIR"/logs/homepanel.log* "$TMP/" 2>/dev/null || echo "no log files" > "$TMP/no-logs.txt"
if command -v journalctl >/dev/null; then
  journalctl -u homepanel -n 2000 --no-pager > "$TMP/journal.txt" 2>&1 || true
fi
curl -fs "http://localhost:$PORT/api/v1/health" > "$TMP/health.json" 2>&1 || echo "server not reachable" > "$TMP/health.json"
# Device list without secrets (the API never returns config/keys)
curl -fs "http://localhost:$PORT/api/v1/state" > "$TMP/state.json" 2>&1 || true

{
  echo "date: $(date)"
  echo "host: $(hostname)"
  uname -a
  cat /etc/os-release 2>/dev/null | head -4
  cat /proc/device-tree/model 2>/dev/null; echo
  echo "python: $("$APP_DIR/.venv/bin/python" --version 2>&1 || python3 --version)"
  echo "--- packages"
  "$APP_DIR/.venv/bin/pip" freeze 2>/dev/null | grep -iE "starlette|uvicorn|tinytuya|kasa|samsungtvws|aiowebostv" || true
  echo "--- git"
  git -C "$APP_DIR" log -1 --oneline 2>/dev/null || true
  echo "--- network"
  ip -brief addr 2>/dev/null || ifconfig 2>/dev/null | head -20
  echo "--- temperature / throttling"
  vcgencmd measure_temp 2>/dev/null; vcgencmd get_throttled 2>/dev/null
  echo "--- disk"
  df -h / 2>/dev/null
} > "$TMP/system.txt" 2>&1

tar -czf "$OUT.tar.gz" -C "$(dirname "$TMP")" "$OUT"
rm -rf "$(dirname "$TMP")"
echo "Created $OUT.tar.gz — attach it to your GitHub issue."
