"""
Tuya / Smart Life devices over the local network — this covers Globe Electric
(Globe Suite app), Feit, Gosund, Treatlife, Teckin and most "Smart Life" plugs,
switches and bulbs.

Local control needs each device's *local key*. Enter your free Tuya IoT
developer project details in Settings → Tuya once and the panel fetches the keys
for you (see docs/tuya-setup.md). After that, control is 100% local.
"""
from __future__ import annotations

import asyncio
import colorsys

from ..core.adapter import (Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found,
                            Kind, register)

LIGHT_CATEGORIES = {"dj", "dd", "fwd", "xdd", "dc", "fwl", "tgq", "tgkg"}
PLUG_CATEGORIES = {"cz", "pc"}
SWITCH_CATEGORIES = {"kg", "tdq", "cjkg"}
FAN_CATEGORIES = {"fs", "fskg"}

KELVIN_MIN, KELVIN_MAX = 2700, 6500


def _kind(category: str) -> str:
    if category in LIGHT_CATEGORIES:
        return Kind.LIGHT
    if category in SWITCH_CATEGORIES:
        return Kind.SWITCH
    if category in FAN_CATEGORIES:
        return Kind.FAN
    return Kind.PLUG


def _caps(kind: str) -> list[str]:
    if kind == Kind.LIGHT:
        return [Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR, Cap.COLOR_TEMP]
    return [Cap.POWER]


@register
class TuyaAdapter(DeviceAdapter):
    id = "tuya"
    name = "Tuya / Smart Life"
    brands = "Globe Electric, Feit, Gosund, Treatlife, Teckin, any Smart Life app device"
    kinds = (Kind.PLUG, Kind.LIGHT, Kind.SWITCH)
    description = ("Local control of Tuya-based plugs, switches and bulbs. "
                   "Connect your Tuya developer project once to fetch device keys.")
    requires = ("tinytuya",)
    poll_interval = 10
    account_fields = [
        Field("region", "Data center", "select", required=True, default="us",
              options=[{"value": v, "label": label} for v, label in [
                  ("us", "Western America"), ("us-e", "Eastern America"), ("eu", "Central Europe"),
                  ("eu-w", "Western Europe"), ("in", "India"), ("cn", "China"), ("sg", "Singapore")]],
              help="The data center your Tuya developer project uses."),
        Field("api_key", "Access ID / Client ID", required=True,
              help="From iot.tuya.com → Cloud → your project → Overview."),
        Field("api_secret", "Access Secret / Client Secret", "password", required=True),
        Field("device_id", "Any one device ID (optional)",
              help="Only needed if fetching devices fails. In the Globe/Smart Life app: device → ✎ → Device information."),
    ]
    manual_fields = [
        Field("name", "Name", required=True, placeholder="Desk lamp"),
        Field("device_id", "Device ID", required=True),
        Field("local_key", "Local key", "password", required=True),
        Field("ip", "IP address", placeholder="Leave blank to find automatically"),
        Field("version", "Protocol version", "select", default="3.3",
              options=[{"value": v, "label": v} for v in ("3.1", "3.3", "3.4", "3.5")]),
        Field("kind", "Type", "select", default="plug",
              options=[{"value": "plug", "label": "Plug"}, {"value": "light", "label": "Light"},
                       {"value": "switch", "label": "Switch"}]),
    ]

    def __init__(self, account, data_dir):
        super().__init__(account, data_dir)
        self._handles: dict[str, object] = {}

    # --- discovery ----------------------------------------------------------
    async def discover(self, timeout=6.0):
        scan = await asyncio.to_thread(self._lan_scan)
        cloud = []
        if self.account.get("api_key") and self.account.get("api_secret"):
            cloud = await asyncio.to_thread(self._cloud_devices)
        found: list[Found] = []
        seen = set()
        for c in cloud:
            dev_id = c.get("id")
            if not dev_id or c.get("sub"):     # skip Zigbee sub-devices (need a gateway)
                continue
            seen.add(dev_id)
            local = scan.get(dev_id, {})
            kind = _kind(c.get("category", ""))
            found.append(Found(
                adapter=self.id, uid=dev_id, name=c.get("name") or "Tuya device", kind=kind,
                caps=_caps(kind),
                config={"device_id": dev_id, "local_key": c.get("key", ""),
                        "ip": local.get("ip", ""), "version": str(local.get("version") or "3.3"),
                        "category": c.get("category", "")},
                detail=" · ".join(x for x in (local.get("ip") or "not seen on Wi-Fi yet",
                                              c.get("product_name", "")) if x)))
        for dev_id, local in scan.items():
            if dev_id in seen:
                continue
            found.append(Found(
                adapter=self.id, uid=dev_id, name=f"Tuya device {local.get('ip')}", kind=Kind.PLUG,
                caps=[Cap.POWER],
                config={"device_id": dev_id, "local_key": "", "ip": local.get("ip"),
                        "version": str(local.get("version") or "3.3")},
                detail=f"{local.get('ip')} · needs local key (connect your Tuya account first)"))
        return found

    def _lan_scan(self) -> dict:
        import tinytuya
        try:
            res = tinytuya.deviceScan(verbose=False, scantime=8, color=False, poll=False)
        except TypeError:   # older tinytuya releases
            res = tinytuya.deviceScan(False, 8)
        out = {}
        for v in (res or {}).values():
            dev_id = v.get("gwId") or v.get("id")
            if dev_id:
                out[dev_id] = v
        return out

    def _cloud_devices(self) -> list[dict]:
        import tinytuya
        kwargs = dict(apiRegion=self.account.get("region", "us"), apiKey=self.account["api_key"],
                      apiSecret=self.account["api_secret"])
        if self.account.get("device_id"):
            kwargs["apiDeviceID"] = self.account["device_id"]
        cloud = tinytuya.Cloud(**kwargs)
        if getattr(cloud, "error", None):
            raise AdapterError(f"Tuya account: {cloud.error}")
        devs = cloud.getdevices(verbose=False)
        if isinstance(devs, dict) and ("Error" in devs or "Err" in devs):
            raise AdapterError(f"Tuya account: {devs.get('Error') or devs}")
        return devs or []

    def from_manual(self, values):
        if not values.get("device_id") or not values.get("local_key"):
            raise AdapterError("Device ID and local key are required.")
        kind = values.get("kind") or Kind.PLUG
        return Found(adapter=self.id, uid=values["device_id"], name=values.get("name") or "Tuya device",
                     kind=kind, caps=_caps(kind),
                     config={"device_id": values["device_id"], "local_key": values["local_key"],
                             "ip": values.get("ip", ""), "version": values.get("version") or "3.3",
                             "category": "dj" if kind == Kind.LIGHT else "cz"})

    # --- device handle ------------------------------------------------------
    def _handle(self, device: Device):
        h = self._handles.get(device.id)
        if h:
            return h
        import tinytuya
        cfg = device.config
        if not cfg.get("local_key"):
            raise AdapterError("This device needs its local key. Connect your Tuya account in Settings, then search again.")
        cls = tinytuya.BulbDevice if device.kind == Kind.LIGHT else tinytuya.OutletDevice
        h = cls(cfg["device_id"], cfg.get("ip") or "Auto", cfg["local_key"])
        h.set_version(float(cfg.get("version") or 3.3))
        h.set_socketPersistent(False)
        h.set_socketTimeout(3)
        if hasattr(h, "set_socketRetryLimit"):
            h.set_socketRetryLimit(1)
        self._handles[device.id] = h
        return h

    async def forget(self, device):
        self._handles.pop(device.id, None)

    def _status(self, device: Device) -> dict:
        res = self._handle(device).status()
        if not isinstance(res, dict) or "Error" in res:
            msg = (res or {}).get("Error", "No response") if isinstance(res, dict) else "No response"
            if "key" in str(msg).lower() or "decrypt" in str(msg).lower():
                raise AdapterError("Wrong local key. Re-pairing the device in its app changes the key — search again.")
            raise ConnectionError(msg)
        dps = res.get("dps") or {}
        device.meta["dps_keys"] = sorted(dps.keys())
        return dps

    # --- state ----------------------------------------------------------------
    async def refresh(self, device: Device) -> dict:
        dps = await asyncio.to_thread(self._status, device)
        if device.kind != Kind.LIGHT:
            sw = str(device.config.get("switch_dp", "1"))
            state = {"on": bool(dps.get(sw))}
            if "19" in dps:                      # power metering plugs report deci-watts
                state["power_w"] = round(dps["19"] / 10, 1)
            return state
        return self._light_state(device, dps)

    def _light_state(self, device: Device, dps: dict) -> dict:
        v2 = "20" in dps
        p = {"on": "20", "mode": "21", "bri": "22", "temp": "23", "col": "24"} if v2 else \
            {"on": "1", "mode": "2", "bri": "3", "temp": "4", "col": "5"}
        device.config["dp_layout"] = "v2" if v2 else "v1"
        bri_max, bri_min = (1000, 10) if v2 else (255, 25)
        state = {"on": bool(dps.get(p["on"]))}
        mode = dps.get(p["mode"], "white")
        if p["bri"] in dps:
            state["brightness"] = max(1, round((dps[p["bri"]] - bri_min) / (bri_max - bri_min) * 100))
        if p["temp"] in dps:
            tmax = 1000 if v2 else 255
            state["color_temp"] = round(KELVIN_MIN + dps[p["temp"]] / tmax * (KELVIN_MAX - KELVIN_MIN))
        col = dps.get(p["col"])
        if v2 and isinstance(col, str) and len(col) == 12:
            h, s, v = int(col[0:4], 16), int(col[4:8], 16), int(col[8:12], 16)
            r, g, b = colorsys.hsv_to_rgb(h / 360, s / 1000, 1)
            state["color"] = {"r": round(r * 255), "g": round(g * 255), "b": round(b * 255)}
            if mode == "colour":
                state["brightness"] = max(1, round(v / 10))
        state["color_mode"] = "color" if mode == "colour" else "temp"
        return state

    # --- commands -------------------------------------------------------------
    async def command(self, device: Device, action: str, value=None):
        return await asyncio.to_thread(self._command, device, action, value)

    def _command(self, device: Device, action, value):
        h = self._handle(device)

        def check(res):
            if isinstance(res, dict) and "Error" in res:
                raise ConnectionError(res["Error"])

        if device.kind != Kind.LIGHT:
            if action != Action.POWER:
                raise AdapterError("Plugs only turn on and off.")
            check(h.set_value(str(device.config.get("switch_dp", "1")), bool(value)))
            return {"on": bool(value)}

        v2 = device.config.get("dp_layout", "v2") == "v2"
        on_dp = "20" if v2 else "1"
        if action == Action.POWER:
            check(h.set_value(on_dp, bool(value)))
            return {"on": bool(value)}

        if not v2:   # older bulbs: let tinytuya's BulbDevice do the maths
            if action == Action.BRIGHTNESS:
                check(h.set_brightness_percentage(value))
                return {"on": True, "brightness": value}
            if action == Action.COLOR:
                check(h.set_colour(value["r"], value["g"], value["b"]))
                return {"on": True, "color": value, "color_mode": "color"}
            if action == Action.COLOR_TEMP:
                pct = (value - KELVIN_MIN) / (KELVIN_MAX - KELVIN_MIN) * 100
                check(h.set_colourtemp_percentage(max(0, min(100, pct))))
                return {"on": True, "color_temp": value, "color_mode": "temp"}
            raise AdapterError("Not supported by this bulb")

        st = device.state
        if action == Action.BRIGHTNESS:
            if st.get("color_mode") == "color" and st.get("color"):
                check(h.set_multiple_values({"20": True, "24": _hsv_hex(st["color"], value)}))
            else:
                check(h.set_multiple_values({"20": True, "21": "white", "22": round(10 + value / 100 * 990)}))
            return {"on": True, "brightness": value}
        if action == Action.COLOR:
            check(h.set_multiple_values({"20": True, "21": "colour",
                                         "24": _hsv_hex(value, st.get("brightness") or 100)}))
            return {"on": True, "color": value, "color_mode": "color"}
        if action == Action.COLOR_TEMP:
            t = round((value - KELVIN_MIN) / (KELVIN_MAX - KELVIN_MIN) * 1000)
            check(h.set_multiple_values({"20": True, "21": "white", "23": max(0, min(1000, t))}))
            return {"on": True, "color_temp": value, "color_mode": "temp"}
        raise AdapterError("Not supported by this bulb")


def _hsv_hex(rgb: dict, brightness_pct: int) -> str:
    h, s, _ = colorsys.rgb_to_hsv(rgb["r"] / 255, rgb["g"] / 255, rgb["b"] / 255)
    return f"{round(h * 360):04x}{round(s * 1000):04x}{round(brightness_pct * 10):04x}"
