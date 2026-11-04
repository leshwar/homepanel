"""JSON file persistence for devices, rooms, scenes, accounts and settings."""
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
    "background": "ocean",        # ocean | aurora | night
    "idle_screen": "clock",       # what to show when idle: "clock" (resting clock) or "photos"
    "clock_face": "digital",      # resting clock face: digital | analog | words | date | night
    "frame_seconds": 15,          # photo frame: seconds per photo
    "frame_shuffle": True,
    "frame_clock": True,          # small clock over the photos
    "frame_night_clock": True,    # 10 PM–7 AM show the dim clock instead of bright photos
    "latitude": None,             # for sunrise/sunset schedules
    "longitude": None,
    "presence": [],               # [{"name": "Asha", "ip": "192.168.1.23"}] phones to watch
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
