#!/usr/bin/env bash
# Removes the HomePanel service and kiosk autostart. Your data/ folder is kept.
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
sudo systemctl disable --now homepanel.service 2>/dev/null
sudo rm -f /etc/systemd/system/homepanel.service
sudo systemctl daemon-reload
sed -i '/homepanel/d' "$HOME/.config/labwc/autostart" "$HOME/.config/lxsession/LXDE-pi/autostart" 2>/dev/null
echo "HomePanel removed. Settings and devices are still in $APP_DIR/data (delete it to start fresh)."
