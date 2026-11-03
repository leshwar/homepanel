# Testing with real devices

The automated tests prove the app, API, UI and protocol code work against
simulated devices. What they can't prove is that each brand's real hardware
behaves the way its documentation says. This guide is how to close that gap —
on a laptop first, no Raspberry Pi needed.

## What's verified so far

| Area | Status |
|---|---|
| Service layer, middleware, scenes, rooms, settings | Tested automatically |
| API and live updates | Tested automatically (real server) |
| Touch UI | Tested automatically in headless Chromium |
| Schedules, sunrise/sunset, presence logic, energy history | Tested automatically |
| Shelly adapter | Tested against a simulated Shelly Gen2 |
| Home Assistant adapter | Tested against a simulated Home Assistant |
| Tuya / Globe, Govee, Kasa/Tapo, WiZ, Hue, Samsung TV, LG TV | **Needs real-hardware testing** — protocol code follows each brand's docs/libraries |
| Raspberry Pi installer and kiosk | **Needs a test run on a Pi** |
| Presence with real phones | **Needs testing** (phones sleep Wi-Fi differently) |

## 1. Run it on your laptop

Requirements: Python 3.11+ and Git. The laptop must be on the **same Wi-Fi** as
your devices.

macOS / Linux:

```bash
git clone https://github.com/leshwar/homepanel.git
cd homepanel
make setup          # one time
make run            # real devices, verbose logs → http://localhost:8080
```

Windows (PowerShell):

```powershell
git clone https://github.com/leshwar/homepanel.git
cd homepanel
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m app.main --debug
```

Your settings and device keys are saved in `data/` on that laptop (git-ignored).
When you move to the Pi, add the devices again there — or copy `data/homepanel.json`.

## 2. Test each brand

Open http://localhost:8080 → Settings → Add a device → pick the brand.
Keep a second terminal open with `tail -f logs/homepanel.log`.

For each device, check and note the result:

- [ ] Found by **Search** (or added by IP)
- [ ] Shows the right **on/off state** when you change it from its own app (wait for the poll)
- [ ] **Tap** on the tile switches it, and the tile updates
- [ ] Lights: **brightness**, **white** and **color** work and look right
- [ ] TVs: **pairing prompt** appears and is remembered after a restart; **volume**, **D-pad**, **apps**, **inputs**
- [ ] TVs: **turn on** from off (needs the TV setting in DEVICE_SETUP.md)
- [ ] Survives a **server restart** (Ctrl+C, run again)
- [ ] Unplug it: shows **Offline** with a helpful message; plug back in: recovers

Then open an issue (or update the table in the README) with the brand, model,
what worked, and the log file if something didn't.

### Your devices first

| Device | What to expect |
|---|---|
| Globe Electric plugs | Move them to the Smart Life app, connect your Tuya developer project in Settings → Tuya, then Search. See DEVICE_SETUP.md. |
| Govee plugs | Paste your Govee API key, then Search. State changes from the Govee app show up within ~90 s. |
| Samsung TV | TV on → Search → Add → press Allow on the TV. |
| LG TV | TV on → Search → Add → press Accept on the TV. |

## 3. Use Claude Code to debug and improve it

Claude Code running on your laptop can see your home network, so it can run the
server, watch the logs, talk to your devices and fix what doesn't work. The repo's
`CLAUDE.md` tells it how the project is organised.

1. Install Claude Code: see https://docs.claude.com (search "Claude Code").
2. In a terminal: `cd homepanel` then `claude`.
3. Try prompts like:

   - "Run the server against my real devices and watch the logs while I add my Globe plugs. Fix anything that fails."
   - "My LG TV pairs but volume doesn't change. Reproduce it with curl against the API, find the cause in lg_tv.py, and add a test."
   - "Add a Roku TV adapter following app/adapters/README.md, with a test against a fake Roku."
   - "Run make test and make lint, then open a pull request with these changes."

Because `main` is protected (pull request + approval required), have Claude Code
work on a branch and open a PR; a friend reviews and approves it.

## 4. On the Raspberry Pi

Once the laptop tests look good, follow "Install on the Raspberry Pi" in the
README, then repeat the checklist on the touch screen itself (tap targets,
night clock, kiosk restart after reboot).
