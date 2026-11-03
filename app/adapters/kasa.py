"""TP-Link Kasa and Tapo plugs, switches and bulbs via the python-kasa library (local)."""
from __future__ import annotations

from ..core.adapter import Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found, Kind, register
from ..core.net import rgb_to_hsv, hsv_to_rgb


@register
class KasaAdapter(DeviceAdapter):
    id = "kasa"
    name = "TP-Link Kasa / Tapo"
    brands = "TP-Link Kasa and Tapo plugs, switches, bulbs"
    kinds = (Kind.PLUG, Kind.LIGHT, Kind.SWITCH)
    description = "Local control. Newer models and all Tapo devices need your TP-Link login once."
    requires = ("kasa",)
    poll_interval = 10
    account_fields = [
        Field("username", "TP-Link email", help="Needed for Tapo and newer Kasa firmware. Stays on this device."),
        Field("password", "TP-Link password", "password"),
    ]
    manual_fields = [Field("name", "Name", required=True), Field("ip", "IP address", required=True)]

    def __init__(self, account, data_dir):
        super().__init__(account, data_dir)
        self._devs: dict[str, object] = {}

    def _creds(self) -> dict:
        u, p = self.account.get("username"), self.account.get("password")
        return {"username": u, "password": p} if u and p else {}

    async def discover(self, timeout=6.0):
        from kasa import Discover
        devices = await Discover.discover(discovery_timeout=5, **self._creds())
        found = []
        for ip, dev in devices.items():
            try:
                await dev.update()
            except Exception:
                found.append(Found(adapter=self.id, uid=ip, name=f"TP-Link {ip}", kind=Kind.PLUG,
                                   caps=[Cap.POWER], config={"ip": ip},
                                   detail=f"{ip} · needs your TP-Link login (Settings → TP-Link)"))
                continue
            kind, caps = _kind_caps(dev)
            found.append(Found(adapter=self.id, uid=(getattr(dev, "mac", "") or ip).upper(), name=dev.alias or dev.model,
                               kind=kind, caps=caps, config={"ip": ip}, detail=f"{ip} · {dev.model}"))
        return found

    def from_manual(self, values):
        if not values.get("ip"):
            raise AdapterError("IP address is required.")
        return Found(adapter=self.id, uid=values["ip"], name=values.get("name") or "TP-Link device",
                     kind=Kind.PLUG, caps=[Cap.POWER], config={"ip": values["ip"]})

    async def _dev(self, device: Device):
        dev = self._devs.get(device.id)
        if dev is None:
            from kasa import Discover
            dev = await Discover.discover_single(device.config["ip"], **self._creds())
            self._devs[device.id] = dev
        await dev.update()
        return dev

    async def setup(self, device: Device):
        dev = await self._dev(device)
        device.kind, device.caps = _kind_caps(dev)
        device.meta["model"] = dev.model

    async def forget(self, device):
        dev = self._devs.pop(device.id, None)
        if dev and hasattr(dev, "disconnect"):
            await dev.disconnect()

    async def refresh(self, device: Device) -> dict:
        try:
            dev = await self._dev(device)
        except Exception:
            self._devs.pop(device.id, None)   # reconnect next time (IP may have changed)
            raise
        state = {"on": bool(dev.is_on)}
        light = _light(dev)
        if light:
            if getattr(light, "is_dimmable", True) and getattr(light, "brightness", None) is not None:
                state["brightness"] = light.brightness
            if getattr(light, "is_color", False) and getattr(light, "hsv", None):
                h, s, v = light.hsv
                if s:
                    state.update(color=hsv_to_rgb(h / 360, s / 100, 1), color_mode="color")
            if getattr(light, "is_variable_color_temp", False) and getattr(light, "color_temp", 0):
                state.setdefault("color_mode", "temp")
                state["color_temp"] = light.color_temp
        return state

    async def command(self, device: Device, action: str, value=None):
        dev = await self._dev(device)
        if action == Action.POWER:
            await (dev.turn_on() if value else dev.turn_off())
            return {"on": value}
        light = _light(dev)
        if not light:
            raise AdapterError("Not supported by this device")
        if action == Action.BRIGHTNESS:
            await light.set_brightness(value)
            return {"on": True, "brightness": value}
        if action == Action.COLOR:
            h, s, _ = rgb_to_hsv(value)
            await light.set_hsv(round(h * 360), round(s * 100), device.state.get("brightness") or 100)
            return {"on": True, "color": value, "color_mode": "color"}
        if action == Action.COLOR_TEMP:
            await light.set_color_temp(value)
            return {"on": True, "color_temp": value, "color_mode": "temp"}
        raise AdapterError("Not supported")


def _light(dev):
    try:
        from kasa import Module
        return dev.modules.get(Module.Light)
    except Exception:
        return dev if getattr(dev, "is_bulb", False) else None


def _kind_caps(dev):
    light = _light(dev)
    if light and (getattr(light, "is_dimmable", False) or getattr(light, "is_color", False)):
        caps = [Cap.POWER, Cap.BRIGHTNESS]
        if getattr(light, "is_color", False):
            caps.append(Cap.COLOR)
        if getattr(light, "is_variable_color_temp", False):
            caps.append(Cap.COLOR_TEMP)
        is_bulb = "bulb" in str(getattr(dev, "device_type", "")).lower() or getattr(dev, "is_bulb", False) \
            or "strip" in str(getattr(dev, "device_type", "")).lower()
        return (Kind.LIGHT if is_bulb or getattr(light, "is_color", False) else Kind.SWITCH), caps
    dtype = str(getattr(dev, "device_type", "")).lower()
    return (Kind.SWITCH if "wallswitch" in dtype else Kind.PLUG), [Cap.POWER]
