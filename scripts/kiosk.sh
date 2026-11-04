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

# Its own browser profile (not incognito), so the panel's sign-in survives restarts and
# reboots: the wall panel stays signed in and locks back to the profile picker when idle.
PROFILE_DIR="${HOMEPANEL_KIOSK_PROFILE:-$HOME/.config/homepanel-kiosk}"
mkdir -p "$PROFILE_DIR"

# Restart the browser if it ever crashes or is closed by accident.
while true; do
  # After a power cut Chromium would offer to "restore pages"; tell it it closed cleanly.
  sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[^"]*"/"exit_type":"Normal"/' \
    "$PROFILE_DIR/Default/Preferences" 2>/dev/null || true
  "$BROWSER" --kiosk --app="$URL" $EXTRA \
    --noerrdialogs --disable-infobars --no-first-run --disable-session-crashed-bubble \
    --disable-features=Translate,TouchpadOverscrollHistoryNavigation --overscroll-history-navigation=0 \
    --check-for-update-interval=31536000 --password-store=basic --user-data-dir="$PROFILE_DIR"
  sleep 3
done
