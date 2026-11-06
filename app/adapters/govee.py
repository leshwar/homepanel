"""
Govee devices.

* Plugs and most devices: Govee's official cloud API (needs a free API key —
  in the Govee Home app: Profile → ⚙ Settings → Apply for API Key).
* Lights that support Govee's "LAN Control" (toggle it per light in the Govee
  app): controlled directly over Wi-Fi with no internet needed.

If a light shows up both ways, the local (LAN) version is preferred.

Effects (scenes, DIY scenes, snapshots, music mode, strip segments and toggles such as
gradient or TV sync) only exist in the cloud API, so they need the API key even for LAN
lights. Their lists are read once (when the light is added, or on its first refresh) and
cached in the device's meta; "Update list" (Action.UPDATE_EFFECTS) reads them again.
They're never polled. Fast on/off, brightness and color still go over LAN when possible.

Cloud limits (developer.govee.com, "Rate limits"): device/control 2 per second per
device (burst 6); device/state and device/scenes 30 a minute per device; user/devices
30 a minute per account; and about 10,000 requests a day per account. _Budget keeps
under those and says so in plain words rather than letting Govee answer 429.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from ..core.adapter import (Action, AdapterError, Cap, Device, DeviceAdapter, Effect, Field, Found,
                            Kind, register)
from ..core.net import HttpError, http

log = logging.getLogger("homepanel")

CLOUD = "https://openapi.api.govee.com/router/api/v1"
LAN_MULTICAST = "239.255.255.250"
LAN_SCAN_PORT, LAN_LISTEN_PORT, LAN_CMD_PORT = 4001, 4002, 4003

DAILY_LIMIT = 10_000          # Govee's daily allowance per API key (we stop a little before it)
# (requests per second, burst) per bucket; a little under Govee's published limits
CONTROL_RATE = (1.5, 5)       # per device; Govee allows 2/s, burst 6
READ_RATE = (0.4, 6)          # state + scene lists, per device; Govee allows 30/min each
ACCOUNT_RATE = (0.4, 5)       # user/devices, per account; Govee allows 30/min
MAX_WAIT = 4.0                # wait this long for room in a bucket, then say it's busy
EFFECTS_TIMEOUT = 5.0        # reading the lists during a refresh (the service gives a refresh 8 s)
RETRY_EFFECTS_AFTER = 600     # a failed scene-list read is retried after 10 minutes, not every poll

# Govee capability instance → brand-neutral toggle id (Effect.TOGGLES) and its name
TOGGLES = {"nightlightToggle": (Effect.NIGHT_LIGHT, "Night light"),
           "gradientToggle": (Effect.GRADIENT, "Gradient"),
           "dreamViewToggle": (Effect.SYNC, "Screen sync")}
TOGGLE_INSTANCE = {tid: inst for inst, (tid, _n) in TOGGLES.items()}
# Effect id prefix → (Govee instance, group)
EFFECT_KINDS = {"scene": ("lightScene", Effect.SCENES), "diy": ("diyScene", Effect.DIY),
                "snap": ("snapshot", Effect.SNAPSHOTS)}


class _Budget:
    """Token buckets for Govee's per-device and per-account limits, plus a daily count.
    `clock` and `sleep` are swappable so tests don't wait."""

    def __init__(self, clock=time.monotonic, sleep=asyncio.sleep, today=lambda: time.strftime("%Y-%m-%d")):
        self.clock, self.sleep, self.today = clock, sleep, today
        self.buckets: dict[str, tuple[float, float]] = {}   # key -> (tokens, at)
        self.day, self.used = "", 0

    async def take(self, key: str, rate: float, burst: int) -> None:
        day = self.today()
        if day != self.day:
            self.day, self.used = day, 0
        if self.used >= DAILY_LIMIT:
            raise AdapterError("The panel has used today's Govee allowance (10,000 requests). "
                               "It resets tomorrow; the Govee app still works.")
        now = self.clock()
        tokens, at = self.buckets.get(key, (float(burst), now))
        tokens = min(float(burst), tokens + (now - at) * rate)
        wait = 0.0 if tokens >= 1 else (1 - tokens) / rate
        if wait > MAX_WAIT:
            raise AdapterError("That's a lot of changes at once. Wait a few seconds and try again.")
        self.buckets[key] = (tokens - 1, now)       # reserve now, so waiters queue up fairly
        self.used += 1
        if wait:
            await self.sleep(wait)


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
        self.cloud_url = CLOUD                     # tests point this at a fake server
        self.budget = _Budget()
        self._extras: dict[str, dict] = {}         # device id -> effect state the panel set (cloud rarely reports it)
        self._effects_tried: dict[str, float] = {} # device id -> last failed scene-list read (monotonic)

    def account_changed(self, account):
        super().account_changed(account)
        self._effects_tried.clear()                # a new key: try reading scene lists again

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
        dev = ((body or {}).get("payload") or {}).get("device", "")
        if path == "/device/control":
            await self.budget.take(f"control:{dev}", *CONTROL_RATE)
        elif path == "/user/devices":
            await self.budget.take("account", *ACCOUNT_RATE)
        else:
            await self.budget.take(f"read:{dev}", *READ_RATE)
        try:
            res = await http(method, self.cloud_url + path, json_body=body, headers={"Govee-API-Key": key}, timeout=10)
        except HttpError as e:
            if e.status in (401, 403):
                raise AdapterError("Govee rejected the API key. Check it in Settings → Govee.")
            if e.status == 429:
                raise AdapterError("Govee says the panel is sending too much. Wait a minute and try again.")
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

    # --- effects (scenes, music, segments, toggles) ---------------------------------
    @staticmethod
    def _ids(device: Device) -> tuple[str, str] | None:
        """(sku, Govee device id) for cloud calls, or None for a light added by IP alone."""
        cfg = device.config
        dev = cfg.get("device") or cfg.get("_uid") or ""
        if not cfg.get("sku") or not dev or dev.startswith("lan-"):
            return None
        return cfg["sku"], dev

    def _wants_effects(self, device: Device) -> bool:
        """Read the effect lists on this refresh? Once per device; failures retry after a while."""
        if device.config.get("_effects_at") or not self.account.get("api_key") or not self._ids(device):
            return False
        tried = self._effects_tried.get(device.id)
        return tried is None or time.monotonic() - tried > RETRY_EFFECTS_AFTER

    def _effects_hint(self, device: Device) -> None:
        """LAN lights without an API key: say how to get scenes (shown under the light's controls)."""
        if not self.account.get("api_key") and device.config.get("mode") == "lan":
            device.meta["hint"] = "Add your Govee API key in Settings → Govee to use scenes and music mode."
        else:
            device.meta.pop("hint", None)

    async def load_effects(self, device: Device) -> None:
        """Read what the light can do and its scene lists from the cloud, and cache them in meta."""
        ids = self._ids(device)
        if not ids:
            raise AdapterError("Scenes need the light's Govee ID. Remove it and add it again with Search.")
        sku, dev = ids
        res = await self._cloud("GET", "/user/devices")
        mine = next((d for d in (res or {}).get("data") or [] if d.get("device", "").upper() == dev.upper()), None)
        if not mine:
            raise AdapterError("This light isn't in your Govee account. Check that the API key is from the same account.")
        extra = parse_extras(mine.get("capabilities") or [])
        body = {"requestId": uuid.uuid4().hex, "payload": {"sku": sku, "device": dev}}
        effects = []
        if "lightScene" in extra["scene_kinds"]:
            effects += parse_effect_options(await self._cloud("POST", "/device/scenes", body), "lightScene")
        if "diyScene" in extra["scene_kinds"]:
            effects += parse_effect_options(await self._cloud("POST", "/device/diy-scenes", body), "diyScene")
        effects += extra["snapshots"]
        caps = [c for c in device.caps if c not in (Cap.EFFECTS, Cap.MUSIC, Cap.SEGMENTS, Cap.TOGGLES)]
        for cap, have in ((Cap.EFFECTS, effects or extra["scene_kinds"]), (Cap.MUSIC, extra["music_modes"]),
                          (Cap.SEGMENTS, extra["segments"]), (Cap.TOGGLES, extra["toggles"])):
            if have:
                caps.append(cap)
        device.caps = caps
        for key in ("effects", "music_modes", "segments", "toggles"):
            device.meta.pop(key, None)
        device.meta.update({k: v for k, v in (("effects", effects), ("music_modes", extra["music_modes"]),
                                              ("segments", extra["segments"]), ("toggles", extra["toggles"])) if v})
        device.config["_music_fields"] = extra["music_fields"]
        device.config["_effects_at"] = int(time.time())
        self._effects_tried.pop(device.id, None)

    async def _maybe_load_effects(self, device: Device) -> None:
        self._effects_hint(device)
        if not self._wants_effects(device):
            return
        try:   # a slow cloud mustn't hold up the light's own refresh for long
            await asyncio.wait_for(self.load_effects(device), EFFECTS_TIMEOUT)
        except Exception as e:                      # never let this break the light's normal refresh
            self._effects_tried[device.id] = time.monotonic()
            log.warning("%s: couldn't read its scenes from Govee: %s", device.name, e)

    def _with_extras(self, device: Device, state: dict) -> dict:
        """Add what the panel last set (effect, music, segments, toggles) to a refreshed state."""
        x = self._extras.get(device.id) or {}
        for k in ("effect", "music", "segments", "toggles"):
            if k in x:
                state[k] = x[k]
        if x.get("mode") in Effect.MODES:
            state["color_mode"] = x["mode"]
        return state

    def _remember(self, device: Device, **changes) -> dict:
        x = self._extras.setdefault(device.id, {})
        x.update(changes)
        return {k: v for k, v in x.items() if k != "mode"} | ({"color_mode": x["mode"]} if "mode" in x else {})

    # --- state ------------------------------------------------------------------
    async def setup(self, device: Device) -> None:
        await self.refresh(device)

    async def refresh(self, device: Device) -> dict:
        await self._maybe_load_effects(device)
        return self._with_extras(device, await self._refresh_light(device))

    async def _refresh_light(self, device: Device) -> dict:
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
        toggles = {}
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
            elif inst in TOGGLES and val in (0, 1):
                toggles[TOGGLES[inst][0]] = bool(val)
        if "color_temp" in state:
            state["color_mode"] = "temp"
        elif "color" in state:
            state["color_mode"] = "color"
        if toggles:      # Govee reported them: trust that over what the panel remembers
            self._remember(device, toggles={**(self._extras.get(device.id, {}).get("toggles") or {}), **toggles})
        return state

    # --- commands -----------------------------------------------------------------
    async def command(self, device: Device, action: str, value=None):
        if action in (Action.SET_EFFECT, Action.SET_MUSIC, Action.SET_SEGMENTS, Action.SET_TOGGLE,
                      Action.UPDATE_EFFECTS):
            return await self._effect_command(device, action, value)
        out = await self._light_command(device, action, value)
        if action in (Action.COLOR, Action.COLOR_TEMP) and self._extras.get(device.id):
            out |= self._remember(device, effect=None, music=None, segments=None, mode=out.get("color_mode"))
        return out

    async def _effect_command(self, device: Device, action: str, value) -> dict:
        if action == Action.UPDATE_EFFECTS:
            await self.load_effects(device)
            return {}
        ids = self._ids(device)
        if not ids:
            raise AdapterError("Scenes need the light's Govee ID. Remove it and add it again with Search.")
        cfg = device.config
        if action == Action.SET_EFFECT:
            cap, out = effect_capability(value), dict(effect=value, music=None, segments=None, mode="effect")
        elif action == Action.SET_MUSIC:
            cap = music_capability(value, cfg.get("_music_fields") or [])
            out = dict(music=value, effect=None, segments=None, mode="music")
        elif action == Action.SET_SEGMENTS:
            n = int(device.meta.get("segments") or 0)
            prev = (self._extras.get(device.id) or {}).get("segments") or [None] * n
            colors = (list(prev) + [None] * n)[:n]
            caps = segment_capabilities(value)
            for c in caps[:-1]:
                await self._control(ids, c)
            cap = caps[-1]
            if "color" in value:
                for i in value["segments"]:
                    colors[i] = "#{r:02x}{g:02x}{b:02x}".format(**value["color"])
            out = dict(segments=colors, effect=None, music=None, mode="segments")
        else:  # SET_TOGGLE
            cap = ("devices.capabilities.toggle", TOGGLE_INSTANCE[value["id"]], 1 if value["on"] else 0)
            toggles = {**((self._extras.get(device.id) or {}).get("toggles") or {}), value["id"]: value["on"]}
            await self._control(ids, cap)
            return self._remember(device, toggles=toggles)
        await self._control(ids, cap)
        return {**self._remember(device, **out), "on": True}

    async def _control(self, ids: tuple[str, str], cap: tuple[str, str, object]) -> None:
        sku, dev = ids
        await self._cloud("POST", "/device/control", {
            "requestId": uuid.uuid4().hex,
            "payload": {"sku": sku, "device": dev, "capability": {"type": cap[0], "instance": cap[1], "value": cap[2]}}})

    async def _light_command(self, device: Device, action: str, value=None):
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
        await self._control((cfg["sku"], cfg["device"]), cap)
        self._last_cloud_poll[device.id] = asyncio.get_running_loop().time()  # trust it for a while
        return out


# --- cloud JSON → brand-neutral meta, and back ------------------------------------

def _clean(name) -> str:
    return " ".join(str(name or "").replace("\u00a0", " ").split())


def parse_extras(caps_raw: list[dict]) -> dict:
    """The effect-related parts of one device's capabilities from GET /user/devices."""
    out = {"scene_kinds": [], "snapshots": [], "music_modes": [], "music_fields": [], "segments": 0, "toggles": []}
    for c in caps_raw:
        inst, params = c.get("instance"), c.get("parameters") or {}
        if inst in ("lightScene", "diyScene"):
            out["scene_kinds"].append(inst)
        elif inst == "snapshot":
            out["scene_kinds"].append(inst)
            out["snapshots"] = parse_effect_options({"payload": {"capabilities": [c]}}, "snapshot")
        elif inst == "musicMode":
            fields = params.get("fields") or []
            out["music_fields"] = [f.get("fieldName") for f in fields if f.get("fieldName")]
            mode = next((f for f in fields if f.get("fieldName") == "musicMode"), {})
            out["music_modes"] = [{"id": str(o["value"]), "name": _clean(o.get("name"))}
                                  for o in mode.get("options") or [] if isinstance(o.get("value"), int)]
        elif inst == "segmentedColorRgb":
            seg = next((f for f in params.get("fields") or [] if f.get("fieldName") == "segment"), {})
            rng = seg.get("elementRange") or {}
            if isinstance(rng.get("max"), int):
                out["segments"] = rng["max"] - int(rng.get("min") or 0) + 1
            elif isinstance((seg.get("size") or {}).get("max"), int):
                out["segments"] = seg["size"]["max"]
        elif inst in TOGGLES:
            tid, name = TOGGLES[inst]
            out["toggles"].append({"id": tid, "name": name})
    return out


def parse_effect_options(res: dict, instance: str) -> list[dict]:
    """Options of a scene list (POST /device/scenes, /device/diy-scenes, or a snapshot capability)
    as [{"id","name","group"}]. The id carries what Govee needs to play it back."""
    prefix = next(p for p, (inst, _g) in EFFECT_KINDS.items() if inst == instance)
    group = EFFECT_KINDS[prefix][1]
    out, seen = [], set()
    for c in ((res or {}).get("payload") or {}).get("capabilities") or []:
        if c.get("instance") != instance:
            continue
        for o in (c.get("parameters") or {}).get("options") or []:
            v = o.get("value")
            if isinstance(v, dict) and isinstance(v.get("id"), int) and isinstance(v.get("paramId"), int):
                eid = f"{prefix}:{v['id']}:{v['paramId']}"
            elif isinstance(v, int) and not isinstance(v, bool):
                eid = f"{prefix}:{v}"
            else:
                continue
            if eid not in seen and _clean(o.get("name")):
                seen.add(eid)
                out.append({"id": eid, "name": _clean(o.get("name")), "group": group})
    return out


def effect_capability(effect_id: str) -> tuple[str, str, object]:
    """'scene:29884:41599' → the device/control capability that plays it."""
    parts = str(effect_id).split(":")
    try:
        instance = EFFECT_KINDS[parts[0]][0]
        nums = [int(p) for p in parts[1:]]
    except (KeyError, ValueError):
        raise AdapterError("That scene isn't available any more. Tap Update list.") from None
    if parts[0] == "scene" and len(nums) == 2:
        value: object = {"id": nums[0], "paramId": nums[1]}
    elif parts[0] != "scene" and len(nums) == 1:
        value = nums[0]
    else:
        raise AdapterError("That scene isn't available any more. Tap Update list.")
    return ("devices.capabilities.dynamic_scene", instance, value)


def music_capability(value: dict, fields: list[str]) -> tuple[str, str, object]:
    v: dict = {"musicMode": int(value["mode"]), "sensitivity": int(value["sensitivity"])}
    if "autoColor" in fields:
        v["autoColor"] = 1          # colors follow the music
    return ("devices.capabilities.music_setting", "musicMode", v)


def segment_capabilities(value: dict) -> list[tuple[str, str, object]]:
    caps = []
    if "brightness" in value:
        caps.append(("devices.capabilities.segment_color_setting", "segmentedBrightness",
                     {"segment": value["segments"], "brightness": value["brightness"]}))
    if "color" in value:
        c = value["color"]
        caps.append(("devices.capabilities.segment_color_setting", "segmentedColorRgb",
                     {"segment": value["segments"], "rgb": (c["r"] << 16) + (c["g"] << 8) + c["b"]}))
    return caps


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
