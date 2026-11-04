# HomePanel

An open-source, touch-screen smart home panel for the Raspberry Pi. One dark,
simple screen for the lights, plugs and TVs in your home — from many brands at
once — controlled directly over your Wi-Fi.

<p align="center">
  <img src="docs/screenshots/home.png" width="270" alt="Home screen: lit lamp tiles glowing in their colors, a TV tile with volume buttons, plugs">
  <img src="docs/screenshots/room.png" width="270" alt="Home screen filtered to the Living room">
  <img src="docs/screenshots/night.png" width="270" alt="Night clock shown when the panel is idle">
</p>
<p align="center">
  <img src="docs/screenshots/landscape.png" width="830" alt="Home screen in landscape on a 1280x720 display">
</p>

- **Touch-first glass UI.** A **Home page** of widgets you arrange yourself (long-press to edit): a big clock, clocks for India and the US, weather, scenes, rooms and device shortcuts, the same on every screen. A **Rooms** page with a tab for each room, down the side on an iPad or a landscape panel. Tap a tile to switch it, long-press (or tap "…") for full controls.
- **A sky that matches outside.** The background follows the weather and time of day (or pick Ocean, Aurora or Night), under frosted-glass tiles with adjustable transparency. Lit lights glow in their real color.
- **Works on iPhone and iPad too.** Safe areas, no sideways scrolling, and "Add to Home Screen" for a full-screen app.
- **Many brands, one screen.** Globe Electric / Tuya / Smart Life, Govee, TP-Link Kasa & Tapo, Shelly, WiZ, Philips Hue, Samsung TVs, LG TVs and LG sound bars.
- **Local first.** Everything except Govee plugs is controlled directly on your network — it keeps working when the internet is down.
- **Privacy.** The panel makes no internet calls of its own unless you turn on weather (Settings → Location and presence). Then the server asks [Open-Meteo](https://open-meteo.com) (free, no account) for the weather about every 20 minutes, sending only your location rounded to about 1 km. The place name shown on the clock is the one you type; your coordinates aren't sent anywhere to look it up.
- **Voice commands.** Tap or hold the mic and say "turn off the living room", "set the lamp to 30%", "open YouTube", "vacuum the kitchen and hall" or "run movie night". It asks "Which lamp?" when it isn't sure, and asks before turning everything off. Where the browser can't listen (e.g. the Pi's own screen), type the command instead. See [Voice commands](#voice-commands).
- **Scenes and rooms.** "Movie night", "Bedtime", or "All off" for a room or the whole house.
- **Schedules and automations.** At a time of day, at sunset/sunrise (computed locally), or when everyone leaves / someone comes home (phones on Wi-Fi).
- **Resting clock faces.** When nobody has touched the panel for a while it shows a dim clock: big digital, analog with hands, a word clock ("It's quarter past ten"), date and day (with sunrise, sunset and lights on), or a very dim red night face. With weather turned on, the faces also show the temperature and a drawn weather icon, plus your place name. Pick one with a preview in Settings → Display and clock. The clock drifts slowly around the screen to avoid burn-in, and touching it only wakes the panel.
- **Photo frame.** A full-screen slideshow of family photos, added from any phone's browser. It can start by itself when the panel is idle, switches to a dim clock at night, and one touch goes back to the controls.
- **Energy history.** Plugs that measure power show watts now, kWh today and a 7-day chart.
- **Works with Home Assistant.** Already run Home Assistant? Add its lights, switches and TVs here, rooms included.
- **Works from phones too.** Open `http://homepanel.local:8080` in any browser on your Wi-Fi.
- **Built to extend.** A stable API on top, one small file per brand underneath. See [Adding a device brand](app/adapters/README.md).

## Supported devices

| Brand | Devices | How it connects | Setup |
|---|---|---|---|
| Globe Electric, Feit, Gosund, Treatlife, any Smart Life app device | Plugs, switches, bulbs | Local (Tuya protocol) | One-time Tuya developer key, [guide](docs/DEVICE_SETUP.md#globe-electric-and-other-tuya--smart-life-devices) |
| Govee | Plugs | Govee cloud API | Free API key, [guide](docs/DEVICE_SETUP.md#govee) |
| Govee | Lights with "LAN Control" | Local | Toggle LAN Control in the Govee app |
| TP-Link Kasa / Tapo | Plugs, switches, bulbs | Local | TP-Link login for newer models |
| Shelly | Plugs, relays | Local | None |
| WiZ / Philips WiZ | Bulbs | Local | None |
| Philips Hue | Bulbs, strips, plugs | Local via Hue Bridge | Press the bridge button once |
| Samsung | Tizen smart TVs (2016+) | Local | Accept the prompt on the TV once |
| LG | webOS smart TVs | Local | Accept the prompt on the TV once |
| LG | Sound bars with Wi-Fi (2018+) | Local | None, [guide](docs/DEVICE_SETUP.md#lg-sound-bars) |
| Home Assistant | Anything it controls: lights, switches, fans, TVs, speakers | Local (Home Assistant REST API) | Long-lived access token |
| Ecovacs Deebot | Robot vacuums | Ecovacs cloud | Ecovacs Home app login; needs Python 3.14, [guide](docs/DEVICE_SETUP.md#ecovacs-deebot-robot-vacuums) |

Want another brand? It's usually one file — see [app/adapters/README.md](app/adapters/README.md).

## What to buy

| Item | Notes |
|---|---|
| **Raspberry Pi 5, 2GB** | Plenty for this app. More RAM costs much more in 2026 and doesn't help here. |
| **Raspberry Pi Touch Display 2 (7")** | Official screen, no drivers needed, 720×1280, 5-finger touch. The 5" version is cheaper if space is tight. |
| **Official 27W USB-C power supply** | Under-powered chargers cause random freezes. |
| **32–64GB microSD card** (A2 rated) | SanDisk or Samsung. |
| **Case or stand made for Pi 5 + Touch Display 2** | Must say *Touch Display 2*; cases for the original 7" screen don't fit. |
| Active Cooler (optional) | Recommended in a closed case. |

Details and prices: [docs/HARDWARE.md](docs/HARDWARE.md).

## Try it on your computer first (no hardware needed)

Needs Python 3.11 or newer.

```bash
git clone https://github.com/leshwar/homepanel.git
cd homepanel
make setup        # creates .venv and installs everything
make dev          # pretend devices → open http://localhost:8080
```

Without `make` (e.g. Windows):

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.main --demo --debug
```

To control **your real devices** from your laptop (same Wi-Fi), run `make run`
(or `python -m app.main --debug`), open http://localhost:8080, then Settings → Add a device.

## Install on the Raspberry Pi

1. Flash **Raspberry Pi OS (64-bit, with desktop)** with Raspberry Pi Imager. In the Imager's settings, set the hostname to `homepanel`, your Wi-Fi, and a username.
2. Connect the Touch Display 2 (ribbon cable + the two power wires to the GPIO pins), boot, then:

```bash
git clone https://github.com/leshwar/homepanel.git ~/homepanel
cd ~/homepanel
./scripts/install.sh
sudo reboot
```

The panel opens full-screen after boot. Add devices from the panel, or more
comfortably from your phone at `http://homepanel.local:8080` (typing API keys
is easier there).

Server-only (no screen): `./scripts/install.sh --no-kiosk`.

Prefer Docker? `docker compose up -d --build` runs the server (host networking,
so device search works on the Pi). Try it on any computer with
`make docker-demo`. Details and Mac caveats: [docs/DOCKER.md](docs/DOCKER.md).

## Voice commands

Tap the mic at the top of the screen and speak, or hold it while you speak and
let go. What you said appears as you talk; the panel then does it and says what
it did ("Turned off the Floor lamp."). It understands your own device, room,
scene, app and input names, and simple words like lamp/light, telly/TV and
robot/vacuum. If it isn't sure ("set the lamp to 30%" with two lamps) it shows
the choices as buttons, and it asks before turning everything off or turning
off a device marked "keep on". Turn on **Read replies aloud** in the voice
sheet to hear the answer (off by default; remembered per screen).

**Where your voice goes.** Turning speech into text is done by your browser,
not by HomePanel:

- **Chrome** (and Edge) sends the recording to Google's speech service.
- **Safari** on iPhone, iPad and Mac may send it to Apple's servers.
- HomePanel itself only ever gets the text. **Typed commands stay on your network.**

The panel shows this once, the first time you use the mic. Browsers only allow
the microphone on `https://` pages or `localhost`, so on a phone opening
`http://homepanel.local:8080`, and on the Pi's own Chromium (which has no speech
service), the voice sheet shows a box to type the command instead, with a few
suggestions to tap. The commands are understood by simple rules on the panel,
not an AI service. See `POST /api/v1/voice` in [docs/API.md](docs/API.md#voice-commands).

## Logs and debugging

| What | Where |
|---|---|
| Log file (rotates, 5 × 2 MB) | `logs/homepanel.log` |
| On the Pi, live | `journalctl -u homepanel -f` |
| In the app | Settings → Diagnostics and logs (and "Download log file") |
| Verbose logging | add `--debug` (or `make dev` / `make run`, which already do) |
| Bug-report bundle | `./scripts/collect-logs.sh` → attach the `.tar.gz` to an issue (no keys or tokens included) |

Common fixes are in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## More screens

| Light controls | TV remote | Energy |
|---|---|---|
| <img src="docs/screenshots/light.png" width="240" alt="Brightness slider, white and color swatches"> | <img src="docs/screenshots/tv.png" width="240" alt="D-pad, volume and channel rockers, apps and inputs"> | <img src="docs/screenshots/energy.png" width="240" alt="Watts now, kWh today and this week, 7-day bar chart"> |

| Display: background and glass | Solid, clear, and Aurora |
|---|---|
| <img src="docs/screenshots/display.png" width="240" alt="Background choices Ocean, Aurora, Night, a glass transparency slider and a frosted blur switch"> | <img src="docs/screenshots/glass-compare.png" width="520" alt="Three versions of the home screen: 15% transparency, 85% transparency, and the Aurora background"> |

| Photo frame | Photo frame, landscape | Photo frame settings |
|---|---|---|
| <img src="docs/screenshots/photo-frame.png" width="240" alt="Full-screen photo with the time in the corner"> | <img src="docs/screenshots/photo-frame-landscape.png" width="240" alt="The slideshow in landscape"> | <img src="docs/screenshots/photo-frame-settings.png" width="240" alt="Thumbnails, Add photos, seconds per photo, shuffle, idle and night options"> |

| Automations | New automation | Location and presence |
|---|---|---|
| <img src="docs/screenshots/automations.png" width="240" alt="List of schedules with on/off toggles"> | <img src="docs/screenshots/automation-new.png" width="240" alt="When: time of day with day chips. Do: run a scene"> | <img src="docs/screenshots/location.png" width="240" alt="Latitude and longitude for sunset times, and people's phones"> |

## How it's built

```
web/  (touch UI: HTML + CSS + JS, no build step)
  │  HTTP + live events (/api/v1)
app/api/        stable API — never changes when brands are added
app/core/       service: registry, state, polling, scenes, middleware (validate → normalize → log → retry),
                automations (time / sun / presence), energy history (SQLite), presence
app/core/adapter.py   the DeviceAdapter interface every brand implements
app/adapters/   one file per brand: tuya.py, govee.py, kasa.py, shelly.py, wiz.py, hue.py, samsung_tv.py, lg_tv.py,
                lg_soundbar.py, home_assistant.py, ecovacs.py
```

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full picture and
[docs/API.md](docs/API.md) for the API reference.

## Contributing

New brands, fixes and UI ideas are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md).
If you use Claude Code, the project conventions are in [CLAUDE.md](CLAUDE.md).

```bash
make test-unit          # logic tests (no network)
make test-integration   # real server, simulated devices, browser UI
make lint
```

Every pull request runs lint, unit tests, integration tests and a Docker build;
pull requests that change code must include both kinds of tests. Merges to
`main` publish a Docker image for the Pi. See [docs/CI_AND_BRANCH_RULES.md](docs/CI_AND_BRANCH_RULES.md).

## Status

Early but working: the app, UI, demo mode and test suite run end to end. The
device adapters follow each brand's documented protocol or library; the Shelly
and Home Assistant adapters are tested against simulated devices, and the others
still need testing against real hardware. Reports are welcome: open an issue
with your device model and a log bundle. See [docs/TESTING_WITH_DEVICES.md](docs/TESTING_WITH_DEVICES.md).

## License

[MIT](LICENSE)
