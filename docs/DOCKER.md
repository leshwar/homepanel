# Running with Docker

Docker is optional. It's handy if you already use it, want one-command updates,
or run other things on the same machine. The plain install (`make setup` on a
laptop, `./scripts/install.sh` on a Pi) works just as well.

## Where Docker makes sense

| Machine | Demo mode | Real devices | Recommendation |
|---|---|---|---|
| **Raspberry Pi / Linux** | Yes | **Yes**: host networking (set in the compose file) gives full device search | Docker or `install.sh` |
| **Mac (Apple silicon)** | Yes | Partly: control works, automatic Search doesn't | Docker for "same as the Pi" runs; native `make run` to search for devices |
| **Windows** | Yes | Partly (same as Mac) | Native install for real devices |

**Why a Mac is close to the Pi but not identical.** An Apple-silicon Mac runs
the very same `arm64` image the Pi 5 runs, with the same Linux, Python and
libraries. The difference is networking: Docker Desktop runs containers inside a
small Linux virtual machine. With **host networking** enabled (Docker Desktop
4.34 or newer), connections between the container and your Mac and out to a
device's IP address work over TCP and UDP. But the container has no direct
access to your Mac's network interfaces, so **broadcast and multicast discovery
(TVs, Tuya/Globe, Govee LAN lights, WiZ, TP-Link) doesn't reach your Wi-Fi.**
Cloud devices (Govee plugs, Home Assistant) and devices added by IP address work.

Practical routine on a Mac:

1. Find devices once with the native app (`make run` → Settings → Add a device → Search).
   Note each device's IP address (shown in the search results), or reserve IPs in your router.
2. Run the Docker version (below) and add the same devices with **Add by IP address**
   (Govee plugs and Home Assistant: just add the key or token).
3. Final check on the real Pi.

## Install Docker on the Mac

1. Download **Docker Desktop for Mac (Apple silicon)** from docs.docker.com
   (Get Docker → Mac), open the `.dmg`, and drag Docker to Applications.
   It's free for personal use.
2. Open Docker Desktop and sign in (host networking requires being signed in).
3. **Settings → Resources → Network** → turn on **Enable host networking** →
   **Apply and restart**.
4. Check in Terminal: `docker run --rm hello-world`.

Then, in the `homepanel` folder:

```bash
make docker-up        # the same command the Pi uses → http://localhost:8080
make docker-logs      # follow its logs
docker compose down   # stop it
```

## Comparing branches

`./scripts/dev/wt.sh demo <branch>` runs a branch's demo on its own free port, so
two branches (for example two UI designs) can run side by side. See
[DEVELOPMENT.md](DEVELOPMENT.md).

## Try it (any OS, pretend devices)

```bash
git clone https://github.com/leshwar/homepanel.git
cd homepanel
make docker-demo           # or: docker compose --profile demo up --build demo
```

Open http://localhost:8081. This works on any computer with Docker, no host
networking needed.

## Run it for real (Raspberry Pi / Linux)

```bash
# install Docker once: curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER  (then log out/in)
git clone https://github.com/leshwar/homepanel.git ~/homepanel
cd ~/homepanel
TZ=America/Los_Angeles docker compose up -d --build     # use your time zone
```

- Open `http://<pi>.local:8080` from any device.
- Settings, device keys and logs are in `~/homepanel/data` (keep it backed up; it's git-ignored).
- Logs: `docker compose logs -f homepanel` or `data/logs/homepanel.log`.
- Update: `git pull && docker compose up -d --build`, or use the image CI publishes
  after every merge: set `image: ghcr.io/leshwar/homepanel:latest` in
  `docker-compose.yml`, then `docker compose pull && docker compose up -d`.
- Starts on boot automatically (`restart: unless-stopped`).

**Full-screen touch panel with Docker:** run the server in Docker as above, then
add only the kiosk to the desktop session:

```bash
mkdir -p ~/.config/labwc && echo "$HOME/homepanel/scripts/kiosk.sh &" >> ~/.config/labwc/autostart
sudo apt install -y chromium fonts-ibm-plex     # chromium-browser on older Raspberry Pi OS
```

## Time zone

Schedules ("07:00", sunset) use the container's time zone. Set `TZ` to yours
(e.g. `America/Los_Angeles`, `Asia/Kolkata`) when starting the container.
