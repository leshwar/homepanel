"""
Home Assistant bridge: control anything an existing Home Assistant instance knows
about (lights, switches, fans, media players / TVs) through its REST API, while
keeping the HomePanel UI.

Setup: in Home Assistant open your profile → Security → Long-lived access tokens
→ Create token. Paste it with your Home Assistant address in Settings here.

Uses only the documented REST API (https://developers.home-assistant.io/docs/api/rest/):
  GET  /api/states                       all entity states (one call, cached briefly)
  POST /api/services/<domain>/<service>  e.g. light/turn_on {"entity_id": ...}
  POST /api/template                     to read each entity's area (room)
"""
from __future__ import annotations

import asyncio
import time

from ..core.adapter import Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found, Key, Kind, register
from ..core.net import HttpError, http

DOMAINS = {"light": Kind.LIGHT, "switch": Kind.SWITCH, "fan": Kind.FAN,
           "media_player": Kind.TV, "input_boolean": Kind.SWITCH}

# MediaPlayerEntityFeature bit flags (homeassistant/components/media_player/const.py)
MP_PAUSE, MP_VOLUME_SET, MP_VOLUME_MUTE = 1, 4, 8
MP_PREVIOUS, MP_NEXT = 16, 32
MP_TURN_ON, MP_TURN_OFF, MP_VOLUME_STEP = 128, 256, 1024
MP_SELECT_SOURCE, MP_STOP, MP_PLAY = 2048, 4096, 16384

MEDIA_KEYS = {Key.PLAY: "media_play", Key.PAUSE: "media_pause", Key.STOP: "media_stop",
              Key.FORWARD: "media_next_track", Key.REWIND: "media_previous_track"}

# One line per entity: "light.kitchen|Kitchen". area_name() is a standard HA template function.
AREA_TEMPLATE = "{% for s in states %}{{ s.entity_id }}|{{ area_name(s.entity_id) or '' }}\n{% endfor %}"


def parse_areas(text) -> dict:
    out = {}
    for line in str(text or "").splitlines():
        eid, _, area = line.partition("|")
        if eid.strip() and area.strip():
            out[eid.strip()] = area.strip()
    return out


def caps_for(entity_id: str, attrs: dict) -> list[str]:
    domain = entity_id.split(".", 1)[0]
    if domain == "light":
        modes = set(attrs.get("supported_color_modes") or [])
        caps = [Cap.POWER]
        if modes - {"onoff"}:
            caps.append(Cap.BRIGHTNESS)
        if modes & {"hs", "rgb", "rgbw", "rgbww", "xy"}:
            caps.append(Cap.COLOR)
        if "color_temp" in modes:
            caps.append(Cap.COLOR_TEMP)
        return caps
    if domain == "media_player":
        f = int(attrs.get("supported_features") or 0)
        caps = []
        if f & (MP_TURN_ON | MP_TURN_OFF):
            caps.append(Cap.POWER)
        if f & (MP_VOLUME_STEP | MP_VOLUME_SET):
            caps.append(Cap.VOLUME)
        if f & MP_VOLUME_SET:
            caps.append(Cap.VOLUME_LEVEL)
        if f & MP_VOLUME_MUTE:
            caps.append(Cap.MUTE)
        if f & MP_SELECT_SOURCE and attrs.get("source_list"):
            caps.append(Cap.INPUTS)
        if f & (MP_PLAY | MP_PAUSE):
            caps.append(Cap.MEDIA)
        return caps
    return [Cap.POWER]


@register
class HomeAssistantAdapter(DeviceAdapter):
    id = "home_assistant"
    name = "Home Assistant"
    brands = "Anything your Home Assistant controls: lights, switches, fans, TVs and speakers"
    kinds = (Kind.LIGHT, Kind.SWITCH, Kind.FAN, Kind.TV)
    description = "Use devices from an existing Home Assistant. Rooms come from your Home Assistant areas."
    poll_interval = 5
    account_fields = [
        Field("url", "Home Assistant address", required=True, default="http://homeassistant.local:8123"),
        Field("token", "Long-lived access token", "password", required=True,
              help="In Home Assistant: your profile → Security → Long-lived access tokens → Create token."),
    ]

    def __init__(self, account, data_dir):
        super().__init__(account, data_dir)
        self._cache: tuple[float, dict] = (0.0, {})
        self._lock = asyncio.Lock()

    def account_changed(self, account):
        super().account_changed(account)
        self._cache = (0.0, {})

    async def _api(self, method: str, path: str, body=None, timeout=8):
        url, token = (self.account.get("url") or "").rstrip("/"), self.account.get("token")
        if not url or not token:
            raise AdapterError("Connect Home Assistant first: Settings → Add a device → Home Assistant.")
        try:
            return await http(method, url + path, json_body=body, timeout=timeout,
                              headers={"Authorization": f"Bearer {token}"})
        except HttpError as e:
            if e.status == 401:
                raise AdapterError("Home Assistant rejected the token. Create a new long-lived token.")
            if e.status == 404:
                raise AdapterError("Home Assistant doesn't know that device any more.")
            raise

    async def _states(self) -> dict:
        """All states, fetched once and shared by every device for 2 seconds."""
        async with self._lock:
            ts, states = self._cache
            if time.monotonic() - ts < 2:
                return states
            data = await self._api("GET", "/api/states")
            states = {s["entity_id"]: s for s in data or []}
            self._cache = (time.monotonic(), states)
            return states

    async def discover(self, timeout=6.0):
        states = await self._states()
        try:
            areas = parse_areas(await self._api("POST", "/api/template", {"template": AREA_TEMPLATE}))
        except Exception:
            areas = {}   # rooms are a nice-to-have
        found = []
        for eid, s in sorted(states.items()):
            domain = eid.split(".", 1)[0]
            if domain not in DOMAINS or s.get("state") == "unavailable":
                continue
            attrs = s.get("attributes", {})
            caps = caps_for(eid, attrs)
            if not caps:
                continue
            found.append(Found(adapter=self.id, uid=eid, name=attrs.get("friendly_name") or eid,
                               kind=DOMAINS[domain], caps=caps, config={"entity_id": eid},
                               detail=eid, room=areas.get(eid, "")))
        return found

    async def setup(self, device: Device):
        s = (await self._states()).get(device.config["entity_id"])
        if not s:
            raise AdapterError("Home Assistant doesn't have this device any more.")
        device.caps = caps_for(device.config["entity_id"], s.get("attributes", {})) or device.caps
        self._update_meta(device, s.get("attributes", {}))

    def _update_meta(self, device: Device, attrs: dict):
        if attrs.get("source_list"):
            device.meta["inputs"] = [{"id": x, "name": x} for x in attrs["source_list"]]

    async def refresh(self, device: Device) -> dict:
        eid = device.config["entity_id"]
        s = (await self._states()).get(eid)
        if not s:
            raise AdapterError("Home Assistant doesn't have this device any more.")
        if s.get("state") == "unavailable":
            raise ConnectionError("Home Assistant reports this device as unavailable")
        a = s.get("attributes", {})
        st = s.get("state")
        state = {"on": st not in ("off", "standby", "unknown", "idle") if eid.startswith("media_player.") else st == "on"}
        if eid.startswith("light."):
            if a.get("brightness") is not None:
                state["brightness"] = max(1, round(a["brightness"] / 255 * 100))
            if a.get("color_mode") == "color_temp" and a.get("color_temp_kelvin"):
                state.update(color_temp=a["color_temp_kelvin"], color_mode="temp")
            elif a.get("rgb_color"):
                r, g, b = a["rgb_color"]
                state.update(color={"r": r, "g": g, "b": b}, color_mode="color")
        elif eid.startswith("media_player."):
            if a.get("volume_level") is not None:
                state["volume"] = round(a["volume_level"] * 100)
            state["muted"] = bool(a.get("is_volume_muted"))
            state["input"] = a.get("source")
            self._update_meta(device, a)
        return state

    async def _call(self, domain: str, service: str, entity_id: str, **data):
        await self._api("POST", f"/api/services/{domain}/{service}", {"entity_id": entity_id, **data})
        self._cache = (0.0, {})   # next refresh reads fresh state

    async def command(self, device: Device, action: str, value=None):
        eid = device.config["entity_id"]
        domain = eid.split(".", 1)[0]
        if action == Action.POWER:
            svc_domain = "homeassistant" if domain in ("input_boolean",) else domain
            await self._call(svc_domain, "turn_on" if value else "turn_off", eid)
            return {"on": value}
        if domain == "light":
            if action == Action.BRIGHTNESS:
                await self._call("light", "turn_on", eid, brightness_pct=value)
                return {"on": True, "brightness": value}
            if action == Action.COLOR:
                await self._call("light", "turn_on", eid, rgb_color=[value["r"], value["g"], value["b"]])
                return {"on": True, "color": value, "color_mode": "color"}
            if action == Action.COLOR_TEMP:
                await self._call("light", "turn_on", eid, color_temp_kelvin=value)
                return {"on": True, "color_temp": value, "color_mode": "temp"}
        if domain == "media_player":
            if action == Action.VOLUME_UP:
                await self._call(domain, "volume_up", eid)
                return {}
            if action == Action.VOLUME_DOWN:
                await self._call(domain, "volume_down", eid)
                return {}
            if action == Action.VOLUME:
                await self._call(domain, "volume_set", eid, volume_level=round(value / 100, 2))
                return {"volume": value}
            if action == Action.MUTE:
                await self._call(domain, "volume_mute", eid, is_volume_muted=bool(value))
                return {"muted": bool(value)}
            if action == Action.SET_INPUT:
                await self._call(domain, "select_source", eid, source=value)
                return {"input": value}
            if action == Action.KEY and value in MEDIA_KEYS:
                await self._call(domain, MEDIA_KEYS[value], eid)
                return {}
        raise AdapterError("Not supported for this device")
