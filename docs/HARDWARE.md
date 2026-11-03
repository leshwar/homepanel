# Hardware

## Shopping list

| Item | Why | Approx. US price (Nov 2026) |
|---|---|---|
| **Raspberry Pi 5, 2GB** | Fast enough for the UI and dozens of devices. | $77.50 list (raised Oct 1, 2026) |
| **Raspberry Pi Touch Display 2, 7"** | Official, plug-and-play, 720×1280, 5-point touch, powered from the Pi. | $60 list |
| *or* Touch Display 2, 5" | Same resolution, smaller and cheaper. | $40 list |
| **Official Raspberry Pi 27W USB-C power supply** | The Pi 5 is picky about power; weak chargers cause freezes. | ~$12 |
| **microSD card, 32–64 GB, A2 rated** | SanDisk Extreme / Samsung EVO. | ~$10–15 |
| **Case or stand for Pi 5 + Touch Display 2** | e.g. SmartiPi Touch Pro 3, KKSB display stand. Must say *Touch Display 2*. | ~$15–40 |
| Active Cooler (optional) | Keeps the Pi 5 cool in a closed case. | ~$5 |

Raspberry Pi prices rose several times during 2025–2026 because of memory costs,
mostly on the 4GB+ models — which is why the 2GB model is the sweet spot for this
project. Check an Approved Reseller (PiShop.us, CanaKit, Adafruit, Micro Center) for
current prices.

**Why not a Pi 4?** It works (2GB is fine), and it's slightly cheaper, but the
Pi 5 makes Chromium noticeably snappier on the touch screen.

**Why not a Pi Zero 2 W?** It has no DSI display connector, so it can't drive the
official touch display, and Chromium is slow on it. Fine for `--no-kiosk` (server-only) use.

**Other screens.** Any HDMI touch screen that works with Raspberry Pi OS will
work — the UI adapts to portrait and landscape. The official display just avoids
driver hassle.

## Assembly

1. Attach the Pi to the back of the display with the included screws.
2. Connect the **DSI ribbon cable** (use the 22-to-15-pin cable included for the Pi 5)
   to the Pi's DSI port (CAM/DISP 1 or 0).
3. Connect the display's power wires to the Pi's GPIO: **5V (pin 2 or 4)** and **GND (pin 6)**.
4. Put it in the case/stand, insert the microSD card, connect power.

## Portrait or landscape?

The Touch Display 2 is natively **portrait** (720 wide × 1280 tall), which suits a
wall-mounted panel; the UI is designed for it. For landscape on a table, rotate
the screen in Raspberry Pi OS: **Menu → Preferences → Screen Configuration →
right-click the display → Orientation**. The UI switches to a 4-column layout
automatically.

## Wall mounting tips

- Power: a USB-C cable from a recessed outlet or an in-wall USB outlet; keep the
  official 27W supply.
- Keep it off direct sunlight; the display is easier to read and the Pi runs cooler.
- Wi-Fi: the Pi 5 has 2.4 and 5 GHz Wi-Fi. Many smart plugs are 2.4 GHz only —
  make sure your router puts both bands on the same network.
