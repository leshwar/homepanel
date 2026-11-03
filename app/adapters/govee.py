"""
Govee devices.

* Plugs and most devices: Govee's official cloud API (needs a free API key —
  in the Govee Home app: Profile → ⚙ Settings → Apply for API Key).
* Lights that support Govee's "LAN Control" (toggle it per light in the Govee
  app): controlled directly over Wi-Fi with no internet needed.

If a light shows up both ways, the local (LAN) version is preferred.
"""
from __future__ import annotations

import asyncio
import json
import uuid

from ..core.adapter import (Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found,
                            Kind, register)
from ..core.net import HttpError, http

CLOUD = "https://openapi.api.govee.com/router/api/v1"
LAN_MULTICAST = "239.255.255.250"
LAN_SCAN_PORT, LAN_LISTEN_PORT, LAN_CMD_PORT = 4001, 4002, 4003


class _LanListener(asyncio.DatagramProtocol):
    """Govee lights always answer on UDP 4002, so one shared socket collects replies."""

    def __init__(self):
        self.waiters: dict[str, list[asyncio.Future]] = {}   # key: "ip:cmd" or "scan"
        self.scan_results: list[dict] = []

    def datagram_received(self, data, addr):
        try:
            msg = json.loads(data.decode())["msg"]
        except Exception:
            return
        cmd = msg.get("cmd")
        if cmd == "scan":
            self.scan_results.append(msg.get("data", {}))
            return
        for fut in self.waiters.pop(f"{addr[0]}:{cmd}", []):
            if not fut.done():
                fut.set_result(msg.get("data", {}))


@register
class GoveeAdapter(DeviceAdapter):
    id = "govee"
    name = "Govee"
    brands = "Govee smart plugs, bulbs, light strips"
    kinds = (Kind.PLUG, Kind.LIGHT)
    description = "Plugs use Govee's cloud API (free key). Lights with LAN Control work locally."
    poll_interval = 20        # LAN lights; cloud devices are throttled separately
    cloud_poll_seconds = 90   # Govee limits API calls per day — keep cloud polling gentle
    account_fields = [
        Field("api_key", "Govee API key", "password",
              help="Govee Home app → Profile → ⚙ Settings → Apply for API Key. It arrives by email."),
    ]
    manual_fields = [
        Field("name", "Name", required=True),
        Field("ip", "IP address", required=True, help="Only for lights with LAN Control turned on."),
    ]

    def __init__(self, account, data_dir):
        super().__init__(account, data_dir)
        self._listener: _LanListener | None = None
        self._transport = None
        self._last_cloud_poll: dict[str, float] = {}

    async def start(self):
        loop = asyncio.get_running_loop()
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", LAN_LISTEN_PORT))
            self._transport, self._listener = await loop.create_datagram_endpoint(_LanListener, sock=sock)
        except OSError:
            self._listener = None   # port busy: LAN mode off, cloud still works

    async def stop(self):
        if self._transport:
            self._transport.close()

    # --- LAN ------------------------------------------------------------------
    def _lan_send(self, ip: str, cmd: str, data: dict, port: int = LAN_CMD_PORT):
        if not self._transport:
            raise AdapterError("Govee LAN control is unavailable (UDP port 4002 is in use).")
        payload = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()
        self._transport.sendto(payload, (ip, port))

    async def _lan_status(self, ip: str) -> dict:
        fut = asyncio.get_running_loop().create_future()
        self._listener.waiters.setdefault(f"{ip}:devStatus", []).append(fut)
        self._lan_send(ip, "devStatus", {})
        return await asyncio.wait_for(fut, 3)

    async def _lan_scan(self, timeout=3.0) -> list[dict]:
        if not self._listener:
            return []
        self._listener.scan_results = []
        self._lan_send(LAN_MULTICAST, "scan", {"account_topic": "reserve"}, port=LAN_SCAN_PORT)
        await asyncio.sleep(timeout)
        return list(self._listener.scan_results)

    # --- cloud ----------------------------------------------------------------
    async def _cloud(self, method: str, path: str, body=None):
        key = self.account.get("api_key")
        if not key:
            raise AdapterError("Add your Govee API key in Settings → Govee.")
        try:
            res = await http(method, CLOUD + path, json_body=body, headers={"Govee-API-Key": key}, timeout=10)
        except HttpError as e:
            if e.status in (401, 403):
                raise AdapterError("Govee rejected the API key. Check it in Settings → Govee.")
            if e.status == 429:
                raise AdapterError("Govee's daily API limit was reached. It resets within 24 hours.")
            raise
        if isinstance(res, dict) and res.get("code") not in (200, None):
            raise AdapterError(f"Govee: {res.get('message') or res.get('msg') or res}")
        return res

    # --- discovery -------------------------------------------------------------
    async def discover(self, timeout=6.0):
        lan_task = asyncio.create_task(self._lan_scan())
        cloud_devices = []
        if self.account.get("api_key"):
            res = await self._cloud("GET", "/user/devices")
            cloud_devices = (res or {}).get("data") or []
        lan = await lan_task
        lan_by_id = {d.get("device", "").upper(): d for d in lan}

        found = []
        for d in cloud_devices:
            dev_id = d.get("device", "")
            caps_raw = d.get("capabilities") or []
            kind = Kind.PLUG if "socket" in (d.get("type") or "") else Kind.LIGHT
            caps, temp_range = _cloud_caps(caps_raw)
            if not caps:
                continue
            lan_hit = lan_by_id.pop(dev_id.upper(), None)
            if lan_hit and kind == Kind.LIGHT:
                found.append(_lan_found(lan_hit, d.get("deviceName")))
                continue
            found.append(Found(
                adapter=self.id, uid=dev_id, name=d.get("deviceName") or d.get("sku"), kind=kind, caps=caps,
                config={"mode": "cloud", "device": dev_id, "sku": d.get("sku"), "temp_range": temp_range},
                detail=f"{d.get('sku')} · via Govee cloud"))
        for d in lan_by_id.values():
            found.append(_lan_found(d))
        if not found and not self.account.get("api_key"):
            raise AdapterError("No Govee lights answered on Wi-Fi. For plugs, add your Govee API key first.")
        return found

    def from_manual(self, values):
        if not values.get("ip"):
            raise AdapterError("IP address is required.")
        return Found(adapter=self.id, uid=f"lan-{values['ip']}", name=values.get("name") or "Govee light",
                     kind=Kind.LIGHT, caps=[Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR, Cap.COLOR_TEMP],
                     config={"mode": "lan", "ip": values["ip"]})

    # --- state ------------------------------------------------------------------
    async def refresh(self, device: Device) -> dict:
        cfg = device.config
        if cfg.get("mode") == "lan":
            if not self._listener:
                raise AdapterError("Govee LAN control is unavailable on this machine.")
            s = await self._lan_status(cfg["ip"])
            state = {"on": bool(s.get("onOff")), "brightness": s.get("brightness")}
            if s.get("colorTemInKelvin"):
                state.update(color_temp=s["colorTemInKelvin"], color_mode="temp")
            elif s.get("color"):
                state.update(color=s["color"], color_mode="color")
            return state

        loop = asyncio.get_running_loop()
        if loop.time() - self._last_cloud_poll.get(device.id, -1e9) < self.cloud_poll_seconds and device.state.get("online"):
            return {k: v for k, v in device.state.items() if k not in ("online", "error")}
        self._last_cloud_poll[device.id] = loop.time()
        res = await self._cloud("POST", "/device/state", {
            "requestId": uuid.uuid4().hex, "payload": {"sku": cfg["sku"], "device": cfg["device"]}})
        state = {}
        for c in ((res or {}).get("payload") or {}).get("capabilities", []):
            inst, val = c.get("instance"), (c.get("state") or {}).get("value")
            if inst == "online" and val is False:
                raise ConnectionError("Govee says this device is offline")
            if inst == "powerSwitch":
                state["on"] = bool(val)
            elif inst == "brightness" and isinstance(val, (int, float)):
                state["brightness"] = int(val)
            elif inst == "colorRgb" and isinstance(val, int) and val:
                state.update(color={"r": (val >> 16) & 255, "g": (val >> 8) & 255, "b": val & 255})
            elif inst == "colorTemperatureK" and isinstance(val, int) and val:
                state["color_temp"] = val
        if "color_temp" in state:
            state["color_mode"] = "temp"
        elif "color" in state:
            state["color_mode"] = "color"
        return state

    # --- commands -----------------------------------------------------------------
    async def command(self, device: Device, action: str, value=None):
        cfg = device.config
        if cfg.get("mode") == "lan":
            ip = cfg["ip"]
            if action == Action.POWER:
                self._lan_send(ip, "turn", {"value": 1 if value else 0})
                return {"on": value}
            if action == Action.BRIGHTNESS:
                self._lan_send(ip, "brightness", {"value": value})
                return {"on": True, "brightness": value}
            if action == Action.COLOR:
                self._lan_send(ip, "colorwc", {"color": value, "colorTemInKelvin": 0})
                return {"on": True, "color": value, "color_mode": "color"}
            if action == Action.COLOR_TEMP:
                self._lan_send(ip, "colorwc", {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": value})
                return {"on": True, "color_temp": value, "color_mode": "temp"}
            raise AdapterError("Not supported")

        if action == Action.POWER:
            cap, out = ("devices.capabilities.on_off", "powerSwitch", 1 if value else 0), {"on": value}
        elif action == Action.BRIGHTNESS:
            cap, out = ("devices.capabilities.range", "brightness", value), {"on": True, "brightness": value}
        elif action == Action.COLOR:
            rgb = (value["r"] << 16) + (value["g"] << 8) + value["b"]
            cap, out = ("devices.capabilities.color_setting", "colorRgb", rgb), {"color": value, "color_mode": "color"}
        elif action == Action.COLOR_TEMP:
            lo, hi = cfg.get("temp_range") or (2000, 9000)
            v = max(lo, min(hi, value))
            cap, out = ("devices.capabilities.color_setting", "colorTemperatureK", v), {"color_temp": v, "color_mode": "temp"}
        else:
            raise AdapterError("Not supported")
        await self._cloud("POST", "/device/control", {
            "requestId": uuid.uuid4().hex,
            "payload": {"sku": cfg["sku"], "device": cfg["device"],
                        "capability": {"type": cap[0], "instance": cap[1], "value": cap[2]}}})
        self._last_cloud_poll[device.id] = asyncio.get_running_loop().time()  # trust it for a while
        return out


def _cloud_caps(caps_raw: list[dict]) -> tuple[list[str], list[int] | None]:
    caps, temp_range = [], None
    for c in caps_raw:
        inst = c.get("instance")
        if inst == "powerSwitch":
            caps.append(Cap.POWER)
        elif inst == "brightness":
            caps.append(Cap.BRIGHTNESS)
        elif inst == "colorRgb":
            caps.append(Cap.COLOR)
        elif inst == "colorTemperatureK":
            caps.append(Cap.COLOR_TEMP)
            rng = (c.get("parameters") or {}).get("range") or {}
            if rng.get("min") and rng.get("max"):
                temp_range = [rng["min"], rng["max"]]
    return caps, temp_range


def _lan_found(d: dict, name: str | None = None) -> Found:
    return Found(adapter="govee", uid=d.get("device") or f"lan-{d.get('ip')}",
                 name=name or f"Govee {d.get('sku', 'light')}", kind=Kind.LIGHT,
                 caps=[Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR, Cap.COLOR_TEMP],
                 config={"mode": "lan", "ip": d.get("ip"), "sku": d.get("sku")},
                 detail=f"{d.get('ip')} · {d.get('sku', '')} · local")
