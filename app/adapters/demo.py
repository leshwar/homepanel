"""Pretend devices so the panel can be tried without any hardware (run with --demo)."""
from __future__ import annotations

import asyncio
import random

from ..core.adapter import Action, Activity, Cap, Clean, Device, DeviceAdapter, Found, Kind, register

LIGHT_CAPS = [Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR, Cap.COLOR_TEMP]
TV_CAPS = [Cap.POWER, Cap.VOLUME, Cap.VOLUME_LEVEL, Cap.MUTE, Cap.CHANNEL, Cap.REMOTE, Cap.MEDIA, Cap.APPS, Cap.INPUTS]
POINTER_TV_CAPS = [*TV_CAPS, Cap.POINTER]   # like an LG TV: has a touchpad pointer
SPEAKER_CAPS = [Cap.POWER, Cap.VOLUME, Cap.VOLUME_LEVEL, Cap.MUTE, Cap.INPUTS, Cap.SOUND_MODE]

DEMO = [
    ("lr-ceiling", "Ceiling light", Kind.LIGHT, "Living room", [Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR_TEMP],
     {"on": True, "brightness": 80, "color_temp": 3000, "color_mode": "temp"}),
    ("lr-lamp", "Floor lamp", Kind.LIGHT, "Living room", LIGHT_CAPS,
     {"on": True, "brightness": 45, "color_temp": 2400, "color_mode": "temp"}),
    ("lr-strip", "TV backlight", Kind.LIGHT, "Living room", LIGHT_CAPS,
     {"on": False, "brightness": 60, "color": {"r": 120, "g": 80, "b": 255}, "color_mode": "color"}),
    ("lr-tv", "Samsung TV", Kind.TV, "Living room", TV_CAPS,
     {"on": True, "volume": 18, "muted": False, "app": "netflix", "input": None}),
    ("lr-soundbar", "Sound bar", Kind.SPEAKER, "Living room", SPEAKER_CAPS,
     {"on": True, "volume": 12, "muted": False, "input": "arc", "sound_mode": "ai"}),
    ("lr-plug", "Speaker plug", Kind.PLUG, "Living room", [Cap.POWER], {"on": True}),
    ("bd-lamp", "Bedside lamp", Kind.LIGHT, "Bedroom", LIGHT_CAPS,
     {"on": False, "brightness": 30, "color_temp": 2200, "color_mode": "temp"}),
    ("bd-tv", "LG TV", Kind.TV, "Bedroom", POINTER_TV_CAPS,
     {"on": False, "volume": 12, "muted": False, "app": "youtube", "input": None}),
    ("bd-fan", "Fan plug", Kind.PLUG, "Bedroom", [Cap.POWER], {"on": False}),
    ("kt-pendant", "Pendant lights", Kind.LIGHT, "Kitchen", [Cap.POWER, Cap.BRIGHTNESS],
     {"on": False, "brightness": 100}),
    ("kt-kettle", "Kettle plug", Kind.PLUG, "Kitchen", [Cap.POWER], {"on": False}),
    ("kt-fridge", "Fridge plug", Kind.PLUG, "Kitchen", [Cap.POWER], {"on": True}),
    ("lr-vacuum", "Robot vacuum", Kind.VACUUM, "Living room",
     [Cap.CLEAN, Cap.DOCK, Cap.MAP, Cap.ROOMS, Cap.SUCTION, Cap.CLEAN_MODE, Cap.STATION, Cap.LOCATE],
     {"on": False, "activity": Activity.DOCKED, "battery": 100, "suction": "standard", "clean_mode": "vacuum",
      "map_rev": 1, "last_clean": {"area_m2": 46, "minutes": 38},
      "parts": [{"id": "filter", "name": "Filter", "percent": 18}, {"id": "side_brush", "name": "Side brush", "percent": 64},
                {"id": "brush", "name": "Main brush", "percent": 82}]}),
]

VACUUM_META = {
    "model": "Demo vacuum",
    "rooms": [{"id": 1, "name": "Living room"}, {"id": 2, "name": "Kitchen"}, {"id": 3, "name": "Bedroom"},
              {"id": 4, "name": "Hall"}],
    "suction_levels": [{"id": "quiet", "name": "Quiet"}, {"id": "standard", "name": "Standard"},
                       {"id": "strong", "name": "Strong"}, {"id": "max", "name": "Max+"}],
    "clean_modes": [{"id": "vacuum", "name": "Vacuum"}, {"id": "mop", "name": "Mop"},
                    {"id": "vacuum_and_mop", "name": "Vacuum and mop"}],
    "station_actions": [{"id": "empty_dustbin", "name": "Empty dustbin"}, {"id": "wash_mop", "name": "Wash mop"}],
}

# A simple pretend floor plan: four rooms and the dock.
VACUUM_MAP = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 260">
<g fill="#3b4a5c" stroke="#8fa3b8" stroke-width="3">
<rect x="10" y="10" width="220" height="140" rx="4"/><rect x="230" y="10" width="160" height="140" rx="4"/>
<rect x="10" y="150" width="150" height="100" rx="4"/><rect x="160" y="150" width="230" height="100" rx="4"/></g>
<g fill="#cfd9e3" font-family="sans-serif" font-size="16" text-anchor="middle">
<text x="120" y="85">Living room</text><text x="310" y="85">Kitchen</text>
<text x="85" y="205">Hall</text><text x="275" y="205">Bedroom</text></g>
<circle cx="40" cy="225" r="9" fill="#7cc7a5"/></svg>"""

# What a pretend vacuum does after each cleaning command.
CLEAN_TO_ACTIVITY = {Clean.START: Activity.CLEANING, Clean.RESUME: Activity.CLEANING,
                     Clean.PAUSE: Activity.PAUSED, Clean.STOP: Activity.IDLE}

WATTS = {"lr-plug": (6.8, 8.0), "bd-fan": (34, 42), "kt-kettle": (1450, 1550), "kt-fridge": (95, 130)}

APPS = [{"id": "netflix", "name": "Netflix"}, {"id": "youtube", "name": "YouTube"},
        {"id": "prime", "name": "Prime Video"}, {"id": "disney", "name": "Disney+"},
        {"id": "spotify", "name": "Spotify"}, {"id": "hulu", "name": "Hulu"}]
INPUTS = [{"id": "tv", "name": "TV"}, {"id": "hdmi1", "name": "HDMI 1"},
          {"id": "hdmi2", "name": "HDMI 2"}, {"id": "hdmi3", "name": "HDMI 3"}]
SPEAKER_META = {"inputs": [{"id": "arc", "name": "TV (HDMI ARC)"}, {"id": "bt", "name": "Bluetooth"},
                           {"id": "wifi", "name": "Wi-Fi"}, {"id": "optical", "name": "Optical"}],
                "sound_modes": [{"id": "ai", "name": "AI Sound Pro"}, {"id": "standard", "name": "Standard"},
                                {"id": "cinema", "name": "Cinema"}, {"id": "music", "name": "Music"},
                                {"id": "voice", "name": "Clear voice"}],
                "model": "Demo sound bar"}


@register
class DemoAdapter(DeviceAdapter):
    id = "demo"
    name = "Demo devices"
    description = "Pretend devices for trying the panel without hardware."
    kinds = (Kind.LIGHT, Kind.PLUG, Kind.TV, Kind.SPEAKER)
    poll_interval = 30
    hidden = True

    def __init__(self, account, data_dir):
        super().__init__(account, data_dir)
        self._state = {uid: dict(state) for uid, *_rest, state in DEMO}

    async def discover(self, timeout=6.0):
        return [Found(adapter=self.id, uid=uid, name=name, kind=kind, caps=caps,
                      config={"room": room}, detail="Demo")
                for uid, name, kind, room, caps, _ in DEMO]

    async def setup(self, device: Device):
        if device.kind == Kind.TV:
            device.meta = {"apps": APPS, "inputs": INPUTS, "model": "Demo TV"}
        elif device.kind == Kind.VACUUM:
            device.meta = dict(VACUUM_META)
        elif device.kind == Kind.SPEAKER:
            device.meta = dict(SPEAKER_META)
        await self.refresh(device)

    async def map_image(self, device: Device):
        return ("image/svg+xml", VACUUM_MAP.encode()) if device.kind == Kind.VACUUM else None

    async def refresh(self, device: Device) -> dict:
        await asyncio.sleep(0.02)
        if device.kind == Kind.TV and not device.meta:
            device.meta = {"apps": APPS, "inputs": INPUTS, "model": "Demo TV"}
        if device.kind == Kind.VACUUM and not device.meta:
            device.meta = dict(VACUUM_META)
        if device.kind == Kind.SPEAKER and not device.meta:
            device.meta = dict(SPEAKER_META)
        state = dict(self._state.setdefault(device.config["_uid"], {"on": False}))
        if device.config["_uid"] in WATTS:          # these demo plugs measure power
            lo, hi = WATTS[device.config["_uid"]]
            state["power_w"] = round(random.uniform(lo, hi), 1) if state.get("on") else 0.0
        return state

    async def command(self, device: Device, action: str, value=None):
        await asyncio.sleep(random.uniform(0.03, 0.12))   # feel like a real network
        s = self._state.setdefault(device.config["_uid"], {})
        if action == Action.POWER:
            s["on"] = value
        elif action == Action.BRIGHTNESS:
            s.update(on=True, brightness=value)
        elif action == Action.COLOR:
            s.update(on=True, color=value, color_mode="color")
        elif action == Action.COLOR_TEMP:
            s.update(on=True, color_temp=value, color_mode="temp")
        elif action == Action.VOLUME:
            s["volume"] = value
        elif action == Action.VOLUME_UP:
            s["volume"] = min(100, s.get("volume", 0) + 1)
        elif action == Action.VOLUME_DOWN:
            s["volume"] = max(0, s.get("volume", 0) - 1)
        elif action == Action.MUTE:
            s["muted"] = value
        elif action == Action.LAUNCH_APP:
            s.update(on=True, app=value, input=None)
        elif action == Action.SET_INPUT:
            s.update(input=value, app=None)
        elif action == Action.CLEAN:
            activity = CLEAN_TO_ACTIVITY[value]
            s.update(activity=activity, on=activity == Activity.CLEANING)
        elif action == Action.DOCK:
            s.update(activity=Activity.RETURNING, on=True)
        elif action == Action.CLEAN_ROOMS:
            s.update(activity=Activity.CLEANING, on=True)
        elif action == Action.SET_SUCTION:
            s["suction"] = value
        elif action == Action.SET_CLEAN_MODE:
            s["clean_mode"] = value
        elif action in (Action.STATION, Action.LOCATE):
            pass
        elif action == Action.SET_SOUND_MODE:
            s["sound_mode"] = value
        elif action in (Action.KEY, Action.CHANNEL_UP, Action.CHANNEL_DOWN):
            pass
        elif action == Action.POINTER:
            return {}
        return dict(s)
