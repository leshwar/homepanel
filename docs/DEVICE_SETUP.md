# Setting up each brand

General rule: set each device up in its **own app first** (so it's on your
Wi-Fi), then add it in HomePanel → Settings → Add a device → pick the brand →
**Search my Wi-Fi**. The panel and the devices must be on the same network
(many routers put "guest" networks or 5 GHz/2.4 GHz bands on separate subnets —
that's a common reason devices aren't found).

To look for everything at once, tap **Search all brands** at the top of
Add a device. It searches every brand in one go and lists what it found with
the brand name, so you can add each device from there. Brands that need an
account first (for example Tuya) are skipped until you connect them;
the list says which ones, and tapping one takes you to its setup.

Typing keys is easiest from a phone or laptop: open `http://homepanel.local:8080`.

---

## Globe Electric and other Tuya / Smart Life devices

Globe Electric (Globe Suite app), Feit, Gosund, Treatlife, Teckin and most
"works with Smart Life" plugs and bulbs are built on Tuya. HomePanel controls
them **locally**, but needs each device's *local key* once. The panel can fetch
the keys for you from a free Tuya developer project:

1. **Use the Smart Life app.** In most cases the Globe Suite app can't be linked
   to a developer project, so add your Globe devices to the **Smart Life** app
   instead (factory-reset the plug — usually hold its button ~5 s until it blinks
   fast — then add it in Smart Life). Community users report Globe plugs and
   bulbs work fine this way.
2. Create a free account at **iot.tuya.com** → Cloud → Development → **Create Cloud Project**.
   Pick the **data center** for your region (US West for most of the US) and the
   "Smart Home" development method.
3. In the project: **Devices → Link App Account → Add App Account**, and scan the
   QR code from the Smart Life app (Me → scan icon). Your devices appear in the list.
4. Copy the **Access ID** and **Access Secret** from the project's Overview.
5. In HomePanel: Add a device → **Tuya / Smart Life** → enter the data center,
   Access ID and Access Secret → **Save** → **Search my Wi-Fi**.

The keys are stored on the panel; day-to-day control never touches the cloud.
If you re-pair a device in the app, its key changes: just search again.

Already have keys (e.g. from `python -m tinytuya wizard`)? Use **Add by IP address**
and paste the device ID, local key and IP.

## Govee

**Plugs** use Govee's official cloud API:

1. Govee Home app → **Profile** → ⚙ **Settings** → **Apply for API Key**. The key arrives by email.
2. HomePanel: Add a device → **Govee** → paste the key → **Save** → **Search my Wi-Fi**.

Govee limits how many API calls each key can make per day, so the panel checks
cloud devices about every 90 seconds. If you change a plug from the Govee app,
the panel may take up to that long to notice.

**Lights** (bulbs, strips) that support **LAN Control** work locally and update
instantly: in the Govee app open the light → ⚙ → turn on **LAN Control**. They'll
show up in the same search marked "local".

### Scenes, music mode and strip parts

With the API key saved, a Govee light's controls also show what the light can do
beyond plain color (only the sections your light supports appear):

- **Scenes**: Govee's built-in scenes, your **DIY** scenes and saved **Snapshots**,
  with a search box. The highlighted one is playing.
- **Music**: Energic, Rhythm, Spectrum, Rolling (names come from the light), and a
  sensitivity slider. The light listens with its own microphone.
- **Strip parts** (RGBIC strips and TV backlights): tap parts, then a color.
- **Options**: Gradient, Screen sync (Govee's DreamView) and Night light, where listed.

These only exist in Govee's cloud API, so they need the API key even for lights with
LAN Control (on/off, brightness and color still go over your Wi-Fi). The list of scenes
is read once when the light is added (or on its first check after upgrading) and kept;
made a new DIY scene or snapshot in the Govee app? Tap **Update list** under Scenes.
A light added by IP address alone can't use scenes: remove it and add it with **Search**.

Govee's cloud allows a couple of commands a second per light and about 10,000
requests a day per key. The panel never polls scenes and slows down a burst of
changes; if it's still too much it says so instead of failing quietly. Govee doesn't
report which scene is playing, so after a scene started from the Govee app the
panel keeps showing the last one it set.

Newer Govee devices with **Matter** support are a future option (see the roadmap).

## TP-Link Kasa / Tapo

Search finds them automatically. Tapo devices and newer Kasa firmware need your
TP-Link account email and password (entered once in Settings → TP-Link). Control
stays local.

## Shelly

No account needed. Search scans your network; or add by IP. Gen 1 and Gen 2+
(Plus/Pro) devices are both supported.

## WiZ / Philips WiZ

No account needed. Make sure "Allow local communication" is on in the WiZ app
(Settings → Security), then search.

## Philips Hue

Add a device → **Philips Hue** → press the round button on top of the Hue
Bridge → tap **Connect to bridge** within 30 seconds → **Search my Wi-Fi**.

## Samsung TVs (2016 and newer)

1. Turn the TV on. Search finds it.
2. Tap **Add**. A prompt appears **on the TV** ("Allow HomePanel?") — press Allow
   with the TV remote. If you missed it, open the device and tap **Pair now**.
3. To turn the TV **on** from the panel, enable on the TV:
   Settings → General → Network → Expert Settings → **Power On with Mobile**.

Volume shows as +/− buttons (Samsung doesn't report the exact level).

## LG TVs (webOS)

1. Turn the TV on. Search finds it.
2. Tap **Add** and press **Accept** on the TV's prompt.
3. To turn the TV **on** from the panel, enable on the TV:
   Settings → General → Devices → TV Management → **Quick Start+**, and
   Settings → General → Network → **Turn on via Wi-Fi** (menu names vary by year).
4. The remote has a **touchpad** like the Magic Remote: open the TV, tap the hand icon
   under the D-pad, then drag to move the TV's pointer, tap to click and use two fingers
   to scroll. On a phone, **Aim** moves the pointer by tilting the phone. TVs added before
   this get the touchpad automatically the next time the panel talks to them.

## LG sound bars

LG sound bars with Wi-Fi (2018 and newer, the ones the LG Sound Bar / ThinQ app
can control) work over the local network. No account or pairing.

1. Set the sound bar up on your Wi-Fi with the LG app first.
2. **Search** finds it (it answers on port 9741). If it doesn't, choose
   **Add by IP address**; the app shows the IP under the sound bar's settings, or
   look it up in your router's device list.
3. Open it on the panel for volume, mute, inputs (TV / HDMI ARC, HDMI, Bluetooth,
   Wi-Fi …) and sound modes (AI Sound Pro, Cinema, Music …). Each model lists only
   what it has. Newer modes the panel doesn't have a name for yet show as
   "Sound mode 23" and so on.

It works while the TV is off, and alongside the TV: volume changed with the TV
remote shows up on the panel within about 10 seconds. The power button puts the
sound bar in standby and wakes it, as long as its network stays on in standby
(the default after it has been set up with the app).

## Home Assistant

Already running Home Assistant? You can add its devices here:

1. In Home Assistant: click your name (bottom left) → **Security** → **Long-lived
   access tokens** → **Create token**. Copy it (it's shown once).
2. HomePanel: Add a device → **Home Assistant** → enter the address
   (e.g. `http://homeassistant.local:8123`) and the token → **Save** → **Search my Wi-Fi**.

Lights, switches, fans and media players appear, already sorted into your Home
Assistant areas. TVs added this way get volume, inputs and play/pause; for the
full D-pad remote, add Samsung/LG TVs directly with their own adapters.

## Ecovacs Deebot robot vacuums

Deebots are controlled through the Ecovacs cloud, with the same account as the
**Ecovacs Home** app, so the panel needs internet. Set the vacuum up in that app first.

This brand needs **Python 3.14** (its library, deebot-client, is only published
for 3.14). Elsewhere it shows as "not installed" and the rest of the panel works.
On a Mac: `brew install python@3.14`, then `make setup PY=python3.14`.

1. HomePanel: Add a device → **Ecovacs Deebot** → your Ecovacs email (or phone
   number), password and country → **Save**.
2. Tap **Search my Wi-Fi**. If it says Ecovacs wants to confirm this panel, tap
   **Email me a code**, type the code from the email into **Email code**, then
   tap **Confirm code** and search again. This only happens once.
3. Tap **Add** next to your vacuum.

Tap the vacuum's tile for **Start cleaning**, **Pause**, **Keep cleaning** and
**Back to dock**, plus the battery level. Models with a map (most current
Deebots) also get:

- the **map** of your home, from the Ecovacs app (it appears after the first clean);
- **Rooms**: tap rooms to pick them, then **Clean these rooms**;
- **Suction** and **Mode** (vacuum, mop, or both);
- station jobs such as **Empty dustbin** and **Wash mop**, and **Find my vacuum**;
- **Parts**: how worn the brushes, filter and mop pads are.

Rooms come from the map you made in the Ecovacs app; rename or split them there.
The first time the panel connects, these can take up to a minute to appear. Older models that the Ecovacs app
lists as "legacy" (for example the N79) aren't supported.

## Schedules, sunset and "everyone left"

- **Location** (Settings → Location and presence): enter latitude and longitude
  for sunrise/sunset schedules. They're used only on the panel to calculate times.
- **People**: add each person's name and their phone's IP address (reserve a
  fixed IP for each phone in your router). Someone counts as away after about
  10 minutes without their phone on the Wi-Fi.
- **Automations** (Settings → Schedules and automations): pick *when* (time,
  sunrise/sunset, everyone leaves, someone comes home) and *what* (a scene,
  all off, or one device on/off).

## Give devices fixed IP addresses (recommended)

In your router's settings, reserve an IP address ("DHCP reservation") for each
device and the panel. Devices found by search remember their IP; if the router
hands out a new one, the device shows as offline until you search again.
