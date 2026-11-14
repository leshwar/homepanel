# Setting up each brand

General rule: set each device up in its **own app first**, then add it in
HomePanel → Settings → Add a device → pick the brand → **Search**.
Local adapters need the panel and devices on the same network
(many routers put "guest" networks or 5 GHz/2.4 GHz bands on separate subnets —
that's a common reason local devices aren't found). Cloud-backed accounts such
as Ecovacs and VeSync need internet/account access, not LAN proximity to the panel.

To look for everything at once, tap **Search all brands** at the top of
Add a device. It searches every brand in one go and lists what it found with
the brand name, so you can add each device from there. Brands that need an
account first (for example Tuya) are skipped until you connect them;
the list says which ones, and tapping one takes you to its setup.

Typing keys is easiest from a phone or laptop: open `http://homepanel.local:8080`.

## Immich photo library

This is a Home **Photos tile**, separate from the uploaded full-screen photo frame.
In **Settings → Photo library**, enter the existing server's base URL and a
read-only API key with **`album.read`, `asset.read`, `asset.view`**. Do not enter
an Immich account password. Use a direct URL on a trusted LAN/private network or
HTTPS; redirects are deliberately refused. No network exposure is configured.

Connect and verify checks server/version and album access. Choose the albums
intended for the wall display and the profiles allowed to see them, then save.
Image permission is checked when the tile requests a preview. Photos are visible
to those permitted panel viewers; never select a private album unintentionally.
An unprotected one-tap profile is not a security boundary: use optional profile
passwords and trusted-network access when the selected photos are private.
Add the tile with **Home → Edit → Add → Photos**, and move/resize it normally.
Only timeline images from the selected albums are eligible; no entire-library
shuffle, original downloads, EXIF display or face metadata is requested.

The adapter verifies the Immich 2.x/3.x contract and rejects incompatible versions/
privacy responses rather than retrying a broad search. It uses the official
[random search](https://api.immich.app/endpoints/search/searchRandom),
[album membership](https://api.immich.app/endpoints/albums/getAllAlbums) and
[preview](https://api.immich.app/endpoints/assets/viewAsset) APIs; no AGPL server
implementation or additional SDK is copied. The 2.0.0 DTO contract was checked
alongside current API documentation. The user's own server is not connected
until its address and scoped key are entered here.

---

## Levoit Core300S / VeSync

Set up the Core300S in the VeSync app first. In **Settings → Add a device →
VeSync / Levoit**, save the VeSync email, password and account country. Use the
password field in the app, never chat. **Verify connection** only signs in and
lists supported devices; it does not operate them. Then Search and add the
purifier to a room. No Home Assistant installation is required.

The adapter uses pinned [pyvesync 3.5.0](https://github.com/webdjoe/pyvesync/tree/3.5.0)
(MIT, Python 3.11+, asynchronous API), with upstream redaction enabled and verbose
logging disabled. Its verified Core300S model map includes Core300S and
LAP-C301S-WJP / LAP-C302S-WUSB / LAP-C301S-WAAA / LAP-C302S-WGC. Other models are
not offered by this focused adapter.

Controls are power, the reported manual speeds, and Manual/Automatic/Sleep modes.
Selecting a speed enters Manual mode; speed/mode commands turn the purifier on.
Filter life, PM2.5 and air-quality labels are shown only when supported/reported.
Unknown readings stay unknown; no extra sensors or filter-reset commands are
invented. Cloud status polls once a minute. Provider failures receive a
service-managed cooldown; authentication/rate-limit failures wait five minutes.
Changing credentials clears the cooldown, but re-saving identical credentials
does not bypass it.

The account is stored in the panel's private data file, masked in the API and
absent from public snapshots. Signing in to an actual account remains necessary;
fake SDK/cloud tests do not establish a connection to a household purifier.

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
  with a search box. The highlight is the last selection requested through HomePanel,
  not confirmation of the light's current mode.
- **Music**: Energic, Rhythm, Spectrum, Rolling (names come from the light), and a
  sensitivity slider. The light listens with its own microphone.
- **Strip parts** (RGBIC strips and TV backlights): tap parts, then a color.
- **Options**: Gradient, DreamView group sync and Night light, where listed. Status
  distinguishes a device-reported value from the last requested value.

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

### Camera-based TV Video mode (H605C)

The H605C camera backlight's advertised API capabilities do not include a direct
Video-mode command. `dreamViewToggle` is documented as DreamView on/off; it is
grouped-light synchronization, **not verified camera Video-mode selection**.
HomePanel does not relabel that toggle as camera sync or send guessed scene IDs.

The supported workaround is a saved snapshot: select/calibrate Video in Govee Home
once, save a snapshot there, then in HomePanel use **Scenes → Update list →
Snapshots** to recall the actual saved action. The user must identify which snapshot
contains Video; a name alone is not proof of its behavior. A snapshot can restore
brightness and other settings as well. If the API exposes no saved snapshots,
HomePanel cannot create or select camera Video mode through the current connection.
No new MQTT service, account-password capture or raw undocumented opcode is used.

Sources: [Govee control API](https://developer.govee.com/reference/control-you-devices)
documents DreamView separately from modes; [govee2mqtt's pinned Video-effects FAQ](https://github.com/wez/govee2mqtt/blob/6f5a8449ca63da8bdc7cc696288a993681ff2a69/docs/FAQ.md#how-do-i-enable-video-effects-for-a-light)
describes the snapshot/Tap-to-Run workaround. The latter is not direct Video-mode support.

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
3. To turn the TV **on** from the panel, enable **Quick Start+** and **Turn on via Wi-Fi**.
   On webOS 23–25, Quick Start+ is under Settings → All Settings → General → System →
   Additional Settings. Older versions can use General → Devices → TV Management;
   the network-wake menu also varies by model/year.
4. The remote has a **touchpad** like the Magic Remote: open the TV, tap the hand icon
   under the D-pad, then drag to move the TV's pointer, tap to click and use two fingers
   to scroll. On a phone, **Aim** moves the pointer by tilting the phone. TVs added before
   this get the touchpad automatically the next time the panel talks to them.

**Open Home instead of the previous HDMI input:** in HomePanel, open the TV's
settings and choose **After HomePanel turns this TV on → TV Home**, then **Save**.
The default remains **Previous input (TV default)** until you select Home.
This setting only affects a HomePanel-initiated wake from off: the panel waits
for an authenticated, active TV and its input socket, then sends Home once.
An already-on TV, polling, reconnecting or repeated On commands never send Home.
Newer input/app/remote-key/off actions cancel an unfinished wake. Startup has a
bounded wait and reports an error instead of claiming the TV woke after a timeout.
No background task repeatedly sends Home or fights later HDMI input changes.

**For the physical TV remote:** LG's webOS 23–25 guidance (including a G4 on
webOS 24) is Settings → All Settings → General → System → Additional Settings →
Home Settings → **Power On Screen → Home**. LG notes that physical TV-button
startup and some models behave differently; do not assume Wake-on-LAN honors this
setting. webOS 26+ can omit the General step.

If PS5 later takes over the input, HDMI-CEC/device-link behavior is a possible
contributor, not something HomePanel has confirmed. Review the TV and console
settings with their remotes; do not disable global SIMPLINK/CEC indiscriminately,
because it can affect soundbar ARC/eARC, audio and linked power behavior.

Sources: [LG startup screen guidance](https://www.lg.com/us/support/help-library/how-to-set-the-startup-screen-on-your-lg-tv--20155412183664),
[LG default input guidance](https://www.lg.com/us/support/help-library/lg-tv-how-to-set-the-default-input--20153711388714).
Paired readiness and the single Home input command are implemented against the
`aiowebostv` active-state and input-socket API. Version 0.10 or newer is required
for the pre-registration identity guard; 0.10 supports Python 3.11, while 1.x
requires Python 3.12 or newer. The same guard is exercised on both versions.

### TV is on, but the panel cannot connect

A router can assign a different IP address when its DHCP lease changes, the TV
reconnects, or its network interface changes. An address change alone does not prove
which router event caused it. HomePanel now treats an unreachable address as
**Unavailable**, with current power unknown, rather than reporting **Off**.
The last reported power is labeled as stale. A verified standby/power-off report
still appears as Off.

For an already paired TV with a saved SSDP UUID, the adapter checks that exact
identity at most once per minute after connection failure. It accepts only one
matching candidate in the panel's local IPv4 /24, validates its non-redirected local
description, checks the saved model before sending the existing key (or an already
verified MAC when no model is saved), and corroborates the TV's reported MAC and
authenticated control/input sockets before saving the new address. Device identity,
pairing and Home startup preferences stay intact. No polling or rediscovery sends
wake, Home, input or media commands.

Unknown/ambiguous identities, a different model or MAC, blocked multicast, and
rejected pairing leave the saved address unchanged and show a connection problem.
Use **Try again** to recheck the connection; **Send power-on request** remains
available when a known MAC supports waking the TV, even while its status is unknown.
Closed input sockets reconnect before the next deliberate command. A command with
an uncertain delivery result is not automatically replayed.

For network-level prevention, configure a **DHCP reservation** in your router for
the TV's actual active-interface MAC (Wi-Fi and Ethernet can differ). This is not
changed automatically. Reservation setup is router-specific; do not choose an
arbitrary static address that could collide with another device. Automatic recovery
is not a static-IP guarantee and cannot bypass guest-network/multicast isolation.

## LG sound bars

LG sound bars with Wi-Fi (2018 and newer) work over the local network. No account
or pairing is needed by HomePanel. Use the LG Soundbar app for the S95TR, not ThinQ.

1. Set the sound bar up on your Wi-Fi with the LG app first.
2. **Search** finds it (it answers on port 9741). If it doesn't, choose
   **Add by IP address**; the app shows the IP under the sound bar's settings, or
   look it up in your router's device list.
3. Open it on the panel for volume, mute, inputs (TV / HDMI ARC, HDMI, Bluetooth,
   Wi-Fi …) and sound modes (AI Sound Pro, Cinema, Music …). Choices come from
   the device's reported lists. Undocumented IDs such as 23–26 stay under
   **Device-reported modes**, without guessed preset names. Format-dependent
   entries such as Dolby Atmos are also advanced, not promised selectable EQ presets.

It works while the TV is off, and alongside the TV: volume changed with the TV
remote shows up on the panel within about 10 seconds. The power button puts the
sound bar in standby and wakes it, as long as its network stays on in standby
(the default after it has been set up with the app).

**Spotify on S95TR:** start a track in the Spotify mobile app, tap its device
icon, and select the soundbar. Use the same Wi-Fi for the first connection; on
iPhone, allow Spotify's Local Network permission if the speaker is missing.
The panel's Music sound mode changes EQ, not playback. No Spotify account/token
is stored by HomePanel.

Sources: [LG S95TR specifications](https://www.lg.com/au/speakers/soundbars/s95tr/),
[Spotify Connect help](https://support.spotify.com/us/article/spotify-connect/).
Protocol IDs are checked against
[Temescal's tables at 7460c04](https://github.com/mjg59/python-temescal/blob/7460c04ff6bec1be58462399bdb9b72ec0a212c3/temescal/__init__.py)
and [Home Assistant's equivalent-input handling](https://github.com/home-assistant/core/blob/dev/homeassistant/components/lg_soundbar/media_player.py).
These sources do not name IDs 23–26; the panel does not infer a mapping from a
manual's list order.

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
