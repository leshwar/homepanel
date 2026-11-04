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

## Home Assistant

Already running Home Assistant? You can add its devices here:

1. In Home Assistant: click your name (bottom left) → **Security** → **Long-lived
   access tokens** → **Create token**. Copy it (it's shown once).
2. HomePanel: Add a device → **Home Assistant** → enter the address
   (e.g. `http://homeassistant.local:8123`) and the token → **Save** → **Search my Wi-Fi**.

Lights, switches, fans and media players appear, already sorted into your Home
Assistant areas. TVs added this way get volume, inputs and play/pause; for the
full D-pad remote, add Samsung/LG TVs directly with their own adapters.

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
