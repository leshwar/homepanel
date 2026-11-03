#!/usr/bin/env bash
# HomePanel installer for Raspberry Pi OS (Bookworm or Trixie, 64-bit, Desktop).
#
#   git clone https://github.com/leshwar/homepanel.git ~/homepanel
#   cd ~/homepanel && ./scripts/install.sh            # server + full-screen touch UI
#   ./scripts/install.sh --no-kiosk                    # server only (use from phones)
#
# Safe to run again: it updates packages and restarts the service.
set -euo pipefail

KIOSK=1
for arg in "$@"; do
  case "$arg" in
    --no-kiosk) KIOSK=0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="$(id -un)"
PORT="${HOMEPANEL_PORT:-8080}"
say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your normal user (not with sudo). It asks for sudo when needed."; exit 1
fi

say "Installing system packages"
sudo apt-get update -y
PKGS="python3 python3-venv python3-pip avahi-daemon"
if [ "$KIOSK" = 1 ]; then
  # Chromium package name differs between releases
  if apt-cache show chromium >/dev/null 2>&1; then PKGS="$PKGS chromium"; else PKGS="$PKGS chromium-browser"; fi
  PKGS="$PKGS fonts-ibm-plex"
fi
# shellcheck disable=SC2086
sudo apt-get install -y $PKGS

say "Creating Python environment in $APP_DIR/.venv"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

mkdir -p "$APP_DIR/data" "$APP_DIR/logs"

say "Installing the HomePanel service (starts on boot)"
sed -e "s#__USER__#$APP_USER#g" -e "s#__DIR__#$APP_DIR#g" -e "s#__PORT__#$PORT#g" \
  "$APP_DIR/scripts/homepanel.service" | sudo tee /etc/systemd/system/homepanel.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable homepanel.service
sudo systemctl restart homepanel.service

if [ "$KIOSK" = 1 ]; then
  say "Setting up full-screen kiosk mode"
  chmod +x "$APP_DIR/scripts/kiosk.sh"
  # Wayland / labwc (default on Raspberry Pi OS Bookworm+ on Pi 4/5)
  mkdir -p "$HOME/.config/labwc"
  touch "$HOME/.config/labwc/autostart"
  grep -q "homepanel" "$HOME/.config/labwc/autostart" || \
    echo "$APP_DIR/scripts/kiosk.sh &  # homepanel" >> "$HOME/.config/labwc/autostart"
  # X11 / LXDE fallback (older setups)
  mkdir -p "$HOME/.config/lxsession/LXDE-pi"
  if [ -f /etc/xdg/lxsession/LXDE-pi/autostart ] && [ ! -f "$HOME/.config/lxsession/LXDE-pi/autostart" ]; then
    cp /etc/xdg/lxsession/LXDE-pi/autostart "$HOME/.config/lxsession/LXDE-pi/autostart"
  fi
  touch "$HOME/.config/lxsession/LXDE-pi/autostart"
  grep -q "homepanel" "$HOME/.config/lxsession/LXDE-pi/autostart" || \
    echo "@$APP_DIR/scripts/kiosk.sh  # homepanel" >> "$HOME/.config/lxsession/LXDE-pi/autostart"
  # Keep the screen awake; the panel shows its own dim night clock instead.
  if command -v raspi-config >/dev/null; then
    sudo raspi-config nonint do_blanking 1 || true
    sudo raspi-config nonint do_boot_behaviour B4 || true   # desktop, auto-login
  fi
fi

say "Checking the server"
for _ in $(seq 1 30); do
  if curl -fs "http://localhost:$PORT/api/v1/health" >/dev/null; then break; fi
  sleep 1
done
if curl -fs "http://localhost:$PORT/api/v1/health" >/dev/null; then
  echo "HomePanel is running."
  echo "  On this Pi:      http://localhost:$PORT"
  echo "  From your phone: http://$(hostname).local:$PORT"
  echo "  Logs:            journalctl -u homepanel -f   or   $APP_DIR/logs/homepanel.log"
  [ "$KIOSK" = 1 ] && echo "Reboot to start the full-screen panel: sudo reboot"
else
  echo "The server didn't start. See: journalctl -u homepanel -n 50"; exit 1
fi
