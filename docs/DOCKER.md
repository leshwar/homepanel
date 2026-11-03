# Running with Docker

Docker is optional. It's handy if you already use it, want one-command updates,
or run other things on the same machine. The plain install (`make setup` on a
laptop, `./scripts/install.sh` on a Pi) works just as well.

## Where Docker makes sense

| Machine | Demo mode | Real devices | Recommendation |
|---|---|---|---|
| **Raspberry Pi / Linux** | Yes | **Yes**, with host networking (the compose file sets it) | Either Docker or `install.sh` |
| **macOS / Windows** (Docker Desktop) | Yes | Partly | Use the native install (`make run`) for real devices |

Why only "partly" on a Mac or Windows PC: Docker Desktop runs containers inside
a small Linux virtual machine. Normal connections out to a device's IP address
work, so devices added by IP and cloud ones (Govee plugs, Home Assistant) are
fine. But **Search** relies on broadcast and multicast messages on your Wi-Fi
(TVs, Tuya/Globe, Govee LAN lights, WiZ, TP-Link), and those don't pass through
that virtual machine. For testing your real devices on a Mac, run natively.

The touch screen is always just a browser pointed at the server. With Docker on
a Pi, the container runs the server and `scripts/kiosk.sh` opens the screen
(see below).

## Try it (any OS, pretend devices)

```bash
git clone https://github.com/leshwar/homepanel.git
cd homepanel
make docker-demo           # or: docker compose --profile demo up --build demo
```

Open http://localhost:8081.

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
- Update: `git pull && docker compose up -d --build`.
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
