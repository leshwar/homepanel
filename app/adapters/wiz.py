"""WiZ and Philips WiZ Wi-Fi bulbs — local UDP on port 38899, no account needed."""
from __future__ import annotations

import json

from ..core.adapter import Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found, Kind, register
from ..core.net import udp_query

PORT = 38899


async def _rpc(ip: str, method: str, params: dict | None = None, timeout=2.0) -> dict:
    msg = json.dumps({"method": method, "params": params or {}}).encode()
    reply = await udp_query(ip, PORT, msg, timeout=timeout)
    if not reply:
        raise ConnectionError("No reply from bulb")
    data = json.loads(reply[0].decode())
    if "error" in data:
        raise AdapterError(f"Bulb error: {data['error'].get('message')}")
    return data.get("result") or {}


@register
class WizAdapter(DeviceAdapter):
    id = "wiz"
    name = "WiZ"
    brands = "WiZ, Philips WiZ Connected, Philips Smart LED (Wi-Fi)"
    kinds = (Kind.LIGHT,)
    description = "Local control over Wi-Fi. No account or hub needed."
    poll_interval = 10
    manual_fields = [Field("name", "Name", required=True), Field("ip", "IP address", required=True)]

    async def discover(self, timeout=6.0):
        msg = json.dumps({"method": "registration", "params": {
            "phoneMac": "AAAAAAAAAAAA", "register": False, "phoneIp": "1.2.3.4", "id": "1"}}).encode()
        replies = await udp_query("255.255.255.255", PORT, msg, timeout=3.0, broadcast=True, collect=True)
        found, seen = [], set()
        for data, addr in replies or []:
            try:
                result = json.loads(data.decode()).get("result") or {}
            except Exception:
                continue
            mac = (result.get("mac") or addr[0]).upper()
            if mac in seen:
                continue
            seen.add(mac)
            found.append(Found(adapter=self.id, uid=mac, name=f"WiZ bulb {addr[0].split('.')[-1]}",
                               kind=Kind.LIGHT, caps=[Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR, Cap.COLOR_TEMP],
                               config={"ip": addr[0]}, detail=addr[0]))
        return found

    def from_manual(self, values):
        if not values.get("ip"):
            raise AdapterError("IP address is required.")
        return Found(adapter=self.id, uid=values["ip"], name=values.get("name") or "WiZ bulb", kind=Kind.LIGHT,
                     caps=[Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR, Cap.COLOR_TEMP], config={"ip": values["ip"]})

    async def setup(self, device):
        try:
            cfg = await _rpc(device.config["ip"], "getSystemConfig")
            device.meta["model"] = cfg.get("moduleName", "")
            if "TW" in device.meta["model"] or "DW" in device.meta["model"]:   # tunable/dimmable white only
                device.caps = [c for c in device.caps if c != Cap.COLOR]
        except Exception:
            pass
        await self.refresh(device)

    async def refresh(self, device: Device) -> dict:
        r = await _rpc(device.config["ip"], "getPilot")
        state = {"on": bool(r.get("state")), "brightness": r.get("dimming")}
        if r.get("temp"):
            state.update(color_temp=r["temp"], color_mode="temp")
        elif "r" in r:
            state.update(color={"r": r["r"], "g": r["g"], "b": r["b"]}, color_mode="color")
        return state

    async def command(self, device: Device, action: str, value=None):
        ip = device.config["ip"]
        if action == Action.POWER:
            await _rpc(ip, "setPilot", {"state": bool(value)})
            return {"on": value}
        if action == Action.BRIGHTNESS:
            await _rpc(ip, "setPilot", {"state": True, "dimming": max(10, value)})
            return {"on": True, "brightness": value}
        if action == Action.COLOR:
            await _rpc(ip, "setPilot", {"state": True, **value})
            return {"on": True, "color": value, "color_mode": "color"}
        if action == Action.COLOR_TEMP:
            await _rpc(ip, "setPilot", {"state": True, "temp": max(2200, min(6500, value))})
            return {"on": True, "color_temp": value, "color_mode": "temp"}
        raise AdapterError("Not supported")
