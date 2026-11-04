"""
Samsung Smart TVs (Tizen, 2016 and newer) over the local network.

First connection: the TV shows "Allow HomePanel to connect?" — press Allow with
the TV remote. The token is saved, so it's asked only once.
To turn the TV on from standby, enable on the TV: Settings → General →
Network → Expert Settings → Power On with Mobile.
"""
from __future__ import annotations

import asyncio
import os

from ..core.adapter import (Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found, Key,
                            Kind, PairingRequired, register)
from ..core.net import (http, local_subnet_hosts, mac_from_arp, normalize_mac, port_open, scan_ports, ssdp_search,
                        wake_on_lan)

KEYS = {Key.UP: "KEY_UP", Key.DOWN: "KEY_DOWN", Key.LEFT: "KEY_LEFT", Key.RIGHT: "KEY_RIGHT",
        Key.OK: "KEY_ENTER", Key.BACK: "KEY_RETURN", Key.HOME: "KEY_HOME", Key.MENU: "KEY_MENU",
        Key.SOURCE: "KEY_SOURCE", Key.PLAY: "KEY_PLAY", Key.PAUSE: "KEY_PAUSE", Key.STOP: "KEY_STOP",
        Key.REWIND: "KEY_REWIND", Key.FORWARD: "KEY_FF", Key.EXIT: "KEY_EXIT", Key.CHANNEL_LIST: "KEY_CH_LIST",
        Key.INFO: "KEY_INFO", **{d: f"KEY_{d}" for d in Key.DIGITS}}

# Well-known Tizen app IDs, used when the TV doesn't share its installed-app list.
KNOWN_APPS = [
    {"id": "3201907018807", "name": "Netflix"}, {"id": "111299001912", "name": "YouTube"},
    {"id": "3201910019365", "name": "Prime Video"}, {"id": "3201901017640", "name": "Disney+"},
    {"id": "3201601007625", "name": "Hulu"}, {"id": "3201807016597", "name": "Apple TV"},
    {"id": "3201606009684", "name": "Spotify"}, {"id": "3201512006963", "name": "Plex"},
]
INPUTS = [{"id": "KEY_TV", "name": "TV"}, {"id": "KEY_HDMI1", "name": "HDMI 1"},
          {"id": "KEY_HDMI2", "name": "HDMI 2"}, {"id": "KEY_HDMI3", "name": "HDMI 3"},
          {"id": "KEY_HDMI4", "name": "HDMI 4"}]
CAPS = [Cap.POWER, Cap.VOLUME, Cap.MUTE, Cap.CHANNEL, Cap.REMOTE, Cap.MEDIA, Cap.APPS, Cap.INPUTS]


@register
class SamsungTVAdapter(DeviceAdapter):
    id = "samsung_tv"
    name = "Samsung TV"
    brands = "Samsung Smart TVs with Tizen (2016 and newer)"
    kinds = (Kind.TV,)
    description = "Remote control over Wi-Fi. Accept the prompt on the TV the first time."
    requires = ("samsungtvws",)
    poll_interval = 6
    manual_fields = [
        Field("name", "Name", required=True, placeholder="Living room TV"),
        Field("ip", "IP address", required=True, help="TV → Settings → General → Network → Network Status → IP Settings."),
        Field("mac", "MAC address (to turn on)", placeholder="Found automatically if left blank"),
    ]

    def __init__(self, account, data_dir):
        super().__init__(account, data_dir)
        self._remotes: dict[str, object] = {}

    # --- discovery ----------------------------------------------------------
    async def discover(self, timeout=6.0):
        hits = await ssdp_search("urn:samsung.com:device:RemoteControlReceiver:1", timeout=3)
        candidates = [h["ip"] for h in hits]
        if not candidates:
            # Fallback when the network blocks discovery broadcasts: every Tizen TV
            # answers its REST API on port 8001.
            candidates = sorted(await scan_ports(local_subnet_hosts(), (8001,)))
        found, seen = [], set()
        for ip in candidates:
            if ip in seen:
                continue
            seen.add(ip)
            try:
                info = await http("GET", f"http://{ip}:8001/api/v2/", timeout=3)
            except Exception:
                continue
            if not isinstance(info, dict) or "device" not in info:
                continue
            dev = info.get("device", {})
            # Both paths read the TV's own API, so the uid doesn't depend on how it was found.
            mac, uuid = normalize_mac(dev.get("wifiMac")), dev.get("id") or ""
            uid = mac or (uuid or ip).upper()
            legacy = (dev.get("wifiMac") or uuid or ip).upper()     # the uid older versions saved
            config = {"ip": ip, "mac": mac or dev.get("wifiMac", ""), "model": dev.get("modelName", "")}
            if uuid:
                config["uuid"] = uuid
            found.append(Found(adapter=self.id, uid=uid,
                               name=dev.get("name") or info.get("name") or "Samsung TV", kind=Kind.TV, caps=CAPS,
                               config=config, detail=f"{ip} · {dev.get('modelName', '')}", needs_pairing=True,
                               aliases=sorted({legacy, uuid.upper()} - {uid, ""})))
        return found

    def from_manual(self, values):
        if not values.get("ip"):
            raise AdapterError("IP address is required.")
        mac = normalize_mac(values.get("mac"))
        return Found(adapter=self.id, uid=mac or values["ip"], name=values.get("name") or "Samsung TV", kind=Kind.TV,
                     caps=CAPS, config={"ip": values["ip"], "mac": mac or values.get("mac", "")}, needs_pairing=True,
                     aliases=[values["ip"]] if mac else [])

    def known_ids(self, device: Device) -> set[str]:
        extra = {normalize_mac(device.config.get("mac")), (device.config.get("uuid") or "").upper()}
        return super().known_ids(device) | {i for i in extra if i}

    # --- connection -----------------------------------------------------------
    def _token_file(self, device: Device) -> str:
        return os.path.join(self.data_dir, "tokens", f"samsung-{device.id}.token")

    def _remote(self, device: Device):
        r = self._remotes.get(device.id)
        if r is None:
            from samsungtvws import SamsungTVWS
            os.makedirs(os.path.dirname(self._token_file(device)), exist_ok=True)
            r = SamsungTVWS(host=device.config["ip"], port=8002, token_file=self._token_file(device),
                            timeout=8, name="HomePanel")
            self._remotes[device.id] = r
        return r

    def _drop(self, device: Device):
        r = self._remotes.pop(device.id, None)
        if r:
            try:
                r.close()
            except Exception:
                pass

    async def _send(self, device: Device, key: str):
        try:
            await asyncio.to_thread(self._remote(device).send_key, key)
        except Exception as e:
            self._drop(device)
            if type(e).__name__ == "UnauthorizedError" or "unauthorized" in str(e).lower():
                raise PairingRequired("The TV hasn't allowed this panel yet. Choose Pair and press Allow on the TV.")
            raise ConnectionError(f"TV didn't accept the command: {e}")

    async def setup(self, device: Device):
        ip = device.config["ip"]
        try:
            info = await http("GET", f"http://{ip}:8001/api/v2/", timeout=4)
            d = info.get("device", {})
            device.config["mac"] = device.config.get("mac") or d.get("wifiMac", "")
            device.meta["model"] = d.get("modelName", "")
        except Exception:
            raise AdapterError("Can't reach the TV. Turn it on and make sure it's on the same Wi-Fi.")
        if not device.config.get("mac"):
            device.config["mac"] = mac_from_arp(ip) or ""
        try:
            await asyncio.to_thread(self._remote(device).open)   # shows the Allow prompt on first use
        except Exception as e:
            self._drop(device)
            raise PairingRequired(f"Press Allow on the TV, then choose Pair again. ({e})")
        device.meta["inputs"] = INPUTS
        device.meta["apps"] = await self._apps(device)

    async def _apps(self, device: Device) -> list[dict]:
        try:
            apps = await asyncio.wait_for(asyncio.to_thread(self._remote(device).app_list), 6)
            if apps:
                return [{"id": a["appId"], "name": a["name"]} for a in apps if a.get("appId")]
        except Exception:
            pass
        return KNOWN_APPS

    async def forget(self, device):
        self._drop(device)
        try:
            os.remove(self._token_file(device))
        except OSError:
            pass

    # --- state ----------------------------------------------------------------
    async def refresh(self, device: Device) -> dict:
        ip = device.config["ip"]
        try:
            info = await http("GET", f"http://{ip}:8001/api/v2/", timeout=2.5)
        except Exception:
            self._drop(device)
            return {"on": False, "reachable": False}
        power = (info.get("device") or {}).get("PowerState")
        return {"on": power in (None, "on"), "reachable": True}

    # --- commands -------------------------------------------------------------
    async def command(self, device: Device, action: str, value=None):
        if action == Action.POWER:
            return await self._power(device, value)
        if not device.state.get("on"):
            raise AdapterError("Turn the TV on first.")
        if action == Action.VOLUME_UP:
            await self._send(device, "KEY_VOLUP")
        elif action == Action.VOLUME_DOWN:
            await self._send(device, "KEY_VOLDOWN")
        elif action == Action.MUTE:
            await self._send(device, "KEY_MUTE")
            return {"muted": value}
        elif action == Action.CHANNEL_UP:
            await self._send(device, "KEY_CHUP")
        elif action == Action.CHANNEL_DOWN:
            await self._send(device, "KEY_CHDOWN")
        elif action == Action.KEY:
            await self._send(device, KEYS[value])
        elif action == Action.SET_INPUT:
            await self._send(device, value)
            return {"input": value, "app": None}
        elif action == Action.LAUNCH_APP:
            try:
                await http("POST", f"http://{device.config['ip']}:8001/api/v2/applications/{value}", timeout=4)
            except Exception:
                await asyncio.to_thread(self._remote(device).run_app, value)
            return {"app": value}
        else:
            raise AdapterError("Not supported")
        return {}

    async def _power(self, device: Device, on: bool):
        state = await self.refresh(device)
        if on == state.get("on"):
            return {"on": on}
        if on:
            if state.get("reachable"):       # standby but network alive: the power key wakes it
                await self._send(device, "KEY_POWER")
            else:
                mac = device.config.get("mac") or mac_from_arp(device.config["ip"])
                if not mac:
                    raise AdapterError("Can't turn this TV on: its MAC address is unknown. Add it in Settings.")
                await wake_on_lan(mac, device.config["ip"])
                for _ in range(10):           # wait for it to come up
                    await asyncio.sleep(1.5)
                    if await port_open(device.config["ip"], 8001, 1):
                        break
            return {"on": True}
        await self._send(device, "KEY_POWER")
        return {"on": False}
