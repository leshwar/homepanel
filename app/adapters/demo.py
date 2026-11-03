"""Pretend devices so the panel can be tried without any hardware (run with --demo)."""
from __future__ import annotations

import asyncio
import random

from ..core.adapter import Action, Cap, Device, DeviceAdapter, Found, Kind, register

LIGHT_CAPS = [Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR, Cap.COLOR_TEMP]
TV_CAPS = [Cap.POWER, Cap.VOLUME, Cap.VOLUME_LEVEL, Cap.MUTE, Cap.CHANNEL, Cap.REMOTE, Cap.APPS, Cap.INPUTS]

DEMO = [
    ("lr-ceiling", "Ceiling light", Kind.LIGHT, "Living room", [Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR_TEMP],
     {"on": True, "brightness": 80, "color_temp": 3000, "color_mode": "temp"}),
    ("lr-lamp", "Floor lamp", Kind.LIGHT, "Living room", LIGHT_CAPS,
     {"on": True, "brightness": 45, "color_temp": 2400, "color_mode": "temp"}),
    ("lr-strip", "TV backlight", Kind.LIGHT, "Living room", LIGHT_CAPS,
     {"on": False, "brightness": 60, "color": {"r": 120, "g": 80, "b": 255}, "color_mode": "color"}),
    ("lr-tv", "Samsung TV", Kind.TV, "Living room", TV_CAPS,
     {"on": True, "volume": 18, "muted": False, "app": "netflix", "input": None}),
    ("lr-plug", "Speaker plug", Kind.PLUG, "Living room", [Cap.POWER], {"on": True}),
    ("bd-lamp", "Bedside lamp", Kind.LIGHT, "Bedroom", LIGHT_CAPS,
     {"on": False, "brightness": 30, "color_temp": 2200, "color_mode": "temp"}),
    ("bd-tv", "LG TV", Kind.TV, "Bedroom", TV_CAPS,
     {"on": False, "volume": 12, "muted": False, "app": "youtube", "input": None}),
    ("bd-fan", "Fan plug", Kind.PLUG, "Bedroom", [Cap.POWER], {"on": False}),
    ("kt-pendant", "Pendant lights", Kind.LIGHT, "Kitchen", [Cap.POWER, Cap.BRIGHTNESS],
     {"on": False, "brightness": 100}),
    ("kt-kettle", "Kettle plug", Kind.PLUG, "Kitchen", [Cap.POWER], {"on": False}),
    ("kt-fridge", "Fridge plug", Kind.PLUG, "Kitchen", [Cap.POWER], {"on": True}),
]

APPS = [{"id": "netflix", "name": "Netflix"}, {"id": "youtube", "name": "YouTube"},
        {"id": "prime", "name": "Prime Video"}, {"id": "disney", "name": "Disney+"},
        {"id": "spotify", "name": "Spotify"}, {"id": "hulu", "name": "Hulu"}]
INPUTS = [{"id": "tv", "name": "TV"}, {"id": "hdmi1", "name": "HDMI 1"},
          {"id": "hdmi2", "name": "HDMI 2"}, {"id": "hdmi3", "name": "HDMI 3"}]


@register
class DemoAdapter(DeviceAdapter):
    id = "demo"
    name = "Demo devices"
    description = "Pretend devices for trying the panel without hardware."
    kinds = (Kind.LIGHT, Kind.PLUG, Kind.TV)
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
        await self.refresh(device)

    async def refresh(self, device: Device) -> dict:
        await asyncio.sleep(0.02)
        if device.kind == Kind.TV and not device.meta:
            device.meta = {"apps": APPS, "inputs": INPUTS, "model": "Demo TV"}
        return dict(self._state.setdefault(device.config["_uid"], {"on": False}))

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
        elif action in (Action.KEY, Action.CHANNEL_UP, Action.CHANNEL_DOWN):
            pass
        return dict(s)
