#!/usr/bin/env bash
# Opens the HomePanel UI full-screen once the server is up. Started by the desktop
# session (see install.sh). Exit kiosk mode: plug in a keyboard and press Alt+F4.
PORT="${HOMEPANEL_PORT:-8080}"
URL="http://localhost:$PORT/"

for _ in $(seq 1 60); do
  curl -fs "http://localhost:$PORT/api/v1/health" >/dev/null && break
  sleep 1
done

BROWSER="$(command -v chromium || command -v chromium-browser)"
EXTRA=""
[ -n "${WAYLAND_DISPLAY:-}" ] && EXTRA="--ozone-platform=wayland"

# Restart the browser if it ever crashes or is closed by accident.
while true; do
  "$BROWSER" --kiosk --app="$URL" $EXTRA \
    --noerrdialogs --disable-infobars --no-first-run --disable-session-crashed-bubble \
    --disable-features=Translate,TouchpadOverscrollHistoryNavigation --overscroll-history-navigation=0 \
    --check-for-update-interval=31536000 --password-store=basic --incognito
  sleep 3
done
