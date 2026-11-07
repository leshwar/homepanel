# Troubleshooting

First, look at the logs: **Settings → Diagnostics and logs → Problems only**, or
on the Pi run `journalctl -u homepanel -f`, or `tail -f logs/homepanel.log`.
Run with `--debug` (`make run` does) for more detail. If the panel is already
supervised, restart that service rather than launching a second instance.

To report a bug, run `./scripts/collect-logs.sh` and attach the `.tar.gz` to a
GitHub issue. It contains logs and system info but no API keys or device tokens.

| Problem | What to check |
|---|---|
| **Search finds nothing** | Panel and devices on the same network? Guest networks and some mesh/"band steering" setups separate them. Try "Add by IP address". |
| **A brand says "Not installed"** | Run `./scripts/install.sh` again, or `.venv/bin/pip install -r requirements.txt`. The log line at start-up lists unavailable adapters. |
| **Tuya/Globe device: "needs local key"** | Connect your Tuya developer project in Settings → Tuya (see DEVICE_SETUP.md), then search again. |
| **Tuya/Globe: "Wrong local key"** | The device was re-paired in its app, which changes the key. Search again to fetch the new one. |
| **Govee: "daily API limit"** | Govee caps calls per key per day. Wait for the reset; avoid many rapid taps on cloud plugs. |
| **Govee light not found** | Turn on LAN Control for that light in the Govee app. |
| **TV shows "Needs pairing"** | Turn the TV on, open it in the panel, tap **Pair now**, accept the prompt on the TV. |
| **TV won't turn on** | Enable "Power On with Mobile" (Samsung) or "Turn on via Wi-Fi"/Quick Start+ (LG). Wi-Fi TVs can't always wake from deep standby — a wired TV connection is more reliable. Check the device's MAC address is known (Settings → Devices → the TV). |
| **Device goes offline after a router restart** | Its IP changed. Reserve fixed IPs in your router, or search and re-add. |
| **Screen goes black** | That's the resting clock after inactivity (Settings → Display and clock, where you can also pick its face). Touch to wake. If the screen *powers off*, re-run install.sh (it disables screen blanking). |
| **Kiosk didn't start after reboot** | Is the Pi booting to the desktop with auto-login? `sudo raspi-config` → System → Boot / Auto login → Desktop Autologin. |
| **Exit the full-screen panel** | Plug in a keyboard and press Alt+F4, or SSH in and run `pkill chromium`. |
| **Port 8080 in use** | `HOMEPANEL_PORT=8090 python -m app.main`, or edit `/etc/systemd/system/homepanel.service`. |
