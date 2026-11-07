"""JSON file persistence for devices, rooms, scenes, accounts, profiles and settings."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict

from .adapter import Device

DEFAULT_SETTINGS = {
    "home_name": "Home",
    "dim_after_seconds": 90,      # show the ambient clock after this much idle time (0 = never)
    "temperature_unit": "F",
    "clock_24h": False,
    "glass_effect": True,         # frosted-glass blur; turn off if a slow screen feels sluggish
    "glass_transparency": 45,     # 0 = solid tiles, 100 = almost clear glass
    "background": "sky",          # sky (follows the weather and time of day) | ocean | aurora | night | wallpaper
    "wallpaper": "shuffle",       # with background "wallpaper": a wallpaper id, or "shuffle" through them all
    "wallpaper_every": 60,        # shuffle: minutes per wallpaper (0 = a new one only when the page opens)
    "wallpaper_dim": 25,          # darken the wallpaper this much (0–80 %) so text stays readable
    "tile_style": "auto",         # tiles: auto (light on a dark background, dark on a light one) | light | dark
    "idle_screen": "clock",       # what to show when idle: "clock" (resting clock) or "photos"
    "clock_face": "digital",      # resting clock face: digital | analog | words | date | night
    "frame_seconds": 15,          # photo frame: seconds per photo
    "frame_shuffle": True,
    "frame_clock": True,          # small clock over the photos
    "frame_night_clock": True,    # 10 PM–7 AM show the dim clock instead of bright photos
    "latitude": None,             # for sunrise/sunset schedules
    "longitude": None,
    "place_name": "",             # shown on the resting clock, e.g. "Seattle"; typed by the user
    "weather_enabled": False,     # opt-in: fetch weather for the location (the only non-device internet call)
    "presence": [],               # [{"name": "Asha", "ip": "192.168.1.23"}] phones to watch
    "home_layout": None,          # shared default Home page for new profiles (app/core/layout.py); None = built-in
}

DEFAULT_ROOMS = ["Living room", "Bedroom", "Kitchen"]


class Store:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.devices: dict[str, Device] = {}
        self.rooms: list[str] = list(DEFAULT_ROOMS)
        self.scenes: list[dict] = []
        self.accounts: dict[str, dict] = {}
        self.automations: list[dict] = []
        self.profiles: list[dict] = []        # app/core/profiles.py; holds optional password hashes
        self.settings: dict = {**DEFAULT_SETTINGS, "presence": []}
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path) as f:
            data = json.load(f)
        self.rooms = data.get("rooms", self.rooms)
        self.scenes = data.get("scenes", [])
        self.accounts = data.get("accounts", {})
        self.automations = data.get("automations", [])
        self.profiles = data.get("profiles", [])
        self.settings = {**DEFAULT_SETTINGS, **data.get("settings", {})}
        for d in data.get("devices", []):
            d.pop("state", None)
            self.devices[d["id"]] = Device(**d)

    def save(self) -> None:
        data = {
            "version": 1,
            "rooms": self.rooms,
            "devices": [{k: v for k, v in asdict(d).items() if k != "state"} for d in self.devices.values()],
            "scenes": self.scenes,
            "automations": self.automations,
            "accounts": self.accounts,
            "profiles": self.profiles,
            "settings": self.settings,
        }
        with self._lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)  # holds API keys and device tokens
            except OSError:
                pass
