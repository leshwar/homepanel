"""
Shelly relays and plugs (Gen 1 and Gen 2+/Plus/Pro), fully local over HTTP.

This is the simplest adapter in the project — a good template to copy when
adding a new brand.
"""
from __future__ import annotations

import asyncio

from ..core.adapter import Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found, Kind, register
from ..core.net import http, local_subnet_hosts


@register
class ShellyAdapter(DeviceAdapter):
    id = "shelly"
    name = "Shelly"
    brands = "Shelly Plug, Plus, Pro, 1PM and relays"
    kinds = (Kind.PLUG, Kind.SWITCH)
    description = "Local control over Wi-Fi. No account needed."
    poll_interval = 8
    manual_fields = [
        Field("name", "Name", required=True),
        Field("ip", "IP address", required=True),
        Field("channel", "Channel", "number", default=0, help="0 for single plugs and relays."),
    ]

    async def discover(self, timeout=6.0):
        sem = asyncio.Semaphore(64)

        async def probe(ip):
            async with sem:
                try:
                    info = await http("GET", f"http://{ip}/shelly", timeout=1.2)
                except Exception:
                    return None
                if not isinstance(info, dict) or not (info.get("type") or info.get("gen") or info.get("app")):
                    return None
                gen = int(info.get("gen") or 1)
                model = info.get("app") or info.get("model") or info.get("type", "Shelly")
                uid = (info.get("mac") or ip).upper()
                kind = Kind.PLUG if "plug" in str(model).lower() else Kind.SWITCH
                return Found(adapter=self.id, uid=uid, name=info.get("name") or f"Shelly {model}",
                             kind=kind, caps=[Cap.POWER], config={"ip": ip, "gen": gen, "channel": 0},
                             detail=f"{ip} · {model}")

        results = await asyncio.gather(*(probe(ip) for ip in local_subnet_hosts()))
        return [r for r in results if r]

    def from_manual(self, values):
        if not values.get("ip"):
            raise AdapterError("IP address is required.")
        return Found(adapter=self.id, uid=values["ip"], name=values.get("name") or "Shelly",
                     kind=Kind.SWITCH, caps=[Cap.POWER],
                     config={"ip": values["ip"], "gen": 0, "channel": int(values.get("channel") or 0)})

    async def setup(self, device: Device):
        if not device.config.get("gen"):
            info = await http("GET", f"http://{device.config['ip']}/shelly", timeout=3)
            device.config["gen"] = int(info.get("gen") or 1)
        await self.refresh(device)

    async def refresh(self, device: Device) -> dict:
        ip, ch = device.config["ip"], int(device.config.get("channel", 0))
        if int(device.config.get("gen", 1)) >= 2:
            s = await http("GET", f"http://{ip}/rpc/Switch.GetStatus?id={ch}")
            state = {"on": bool(s.get("output"))}
            if s.get("apower") is not None:
                state["power_w"] = round(s["apower"], 1)
            return state
        s = await http("GET", f"http://{ip}/relay/{ch}")
        return {"on": bool(s.get("ison"))}

    async def command(self, device: Device, action: str, value=None):
        if action != Action.POWER:
            raise AdapterError("Shelly relays only turn on and off.")
        ip, ch = device.config["ip"], int(device.config.get("channel", 0))
        if int(device.config.get("gen", 1)) >= 2:
            await http("GET", f"http://{ip}/rpc/Switch.Set?id={ch}&on={'true' if value else 'false'}")
        else:
            await http("GET", f"http://{ip}/relay/{ch}?turn={'on' if value else 'off'}")
        return {"on": value}
