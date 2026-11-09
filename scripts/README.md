# scripts/ — Raspberry Pi install and maintenance

| Script | What it does |
|---|---|
| `install.sh` | Installs packages, creates `.venv`, installs the `homepanel` systemd service (starts on boot, restarts on crash), sets up the full-screen kiosk, disables screen blanking. Safe to re-run to update. `--no-kiosk` for server-only. |
| `kiosk.sh` | Waits for the server, then opens Chromium full-screen on the panel UI; restarts it if it closes. Started by the desktop session. Uses its own browser profile (`~/.config/homepanel-kiosk`) so the wall panel stays signed in across restarts. |
| `homepanel.service` | systemd unit template (install.sh fills in user, folder and port). |
| `collect-logs.sh` | Creates `homepanel-debug-<date>.tar.gz` with logs, journal, health and system info (no secrets) for bug reports. |
| `dev/wt.sh` | Source worktree management under `.worktrees/`; no parallel app/demo launch. See `docs/DEVELOPMENT.md`. |
| `uninstall.sh` | Removes the service and kiosk autostart. Keeps `data/`. |

## Updating the panel

```bash
cd ~/homepanel
git pull
./scripts/install.sh      # re-installs requirements and restarts the service
```

## Useful commands on the Pi

```bash
systemctl status homepanel          # is it running?
sudo systemctl restart homepanel    # restart the server
journalctl -u homepanel -f          # live logs
pkill chromium                      # restart the kiosk browser (it relaunches itself)
```
