"""
LG webOS Smart TVs over the local network, via the aiowebostv library.

First connection: the TV shows a prompt — press Accept with the TV remote. The
key is saved so it's asked only once.
To turn the TV on, enable on the TV: Settings → General → Devices → TV
Management → Quick Start+ and "Turn on via Wi-Fi" (wording varies by year).
"""
from __future__ import annotations

import asyncio

from ..core.adapter import (Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found, Key,
                            Kind, PairingRequired, register)
from ..core.net import (http, local_subnet_hosts, mac_from_arp, normalize_mac, port_open, scan_ports,
                        ssdp_search, wake_on_lan)

WEBOS_PORTS = (3001, 3000)   # webOS remote control: secure, then plain (older TVs)

BUTTONS = {Key.UP: "UP", Key.DOWN: "DOWN", Key.LEFT: "LEFT", Key.RIGHT: "RIGHT", Key.OK: "ENTER",
           Key.BACK: "BACK", Key.HOME: "HOME", Key.MENU: "MENU", Key.SOURCE: "INPUT_HUB",
           Key.PLAY: "PLAY", Key.PAUSE: "PAUSE", Key.STOP: "STOP", Key.REWIND: "REWIND",
           Key.FORWARD: "FASTFORWARD", Key.EXIT: "EXIT", Key.CHANNEL_LIST: "LIST", Key.INFO: "INFO",
           **{d: d for d in Key.DIGITS}}
CAPS = [Cap.POWER, Cap.VOLUME, Cap.VOLUME_LEVEL, Cap.MUTE, Cap.CHANNEL, Cap.REMOTE, Cap.MEDIA, Cap.APPS, Cap.INPUTS,
        Cap.POINTER]


def _tv(client, name, default=None):
    """aiowebostv moved state into client.tv_state in newer versions; support both."""
    st = getattr(client, "tv_state", None)
    if st is not None and hasattr(st, name):
        return getattr(st, name)
    return getattr(client, name, default)


@register
class LGTVAdapter(DeviceAdapter):
    id = "lg_tv"
    name = "LG TV"
    brands = "LG Smart TVs with webOS"
    kinds = (Kind.TV,)
    description = "Remote control over Wi-Fi. Accept the prompt on the TV the first time."
    requires = ("aiowebostv",)
    poll_interval = 6
    manual_fields = [
        Field("name", "Name", required=True, placeholder="Bedroom TV"),
        Field("ip", "IP address", required=True, help="TV → Settings → Network → Wi-Fi → Advanced Wi-Fi Settings."),
        Field("mac", "MAC address (to turn on)", placeholder="Found automatically if left blank"),
    ]

    def __init__(self, account, data_dir):
        super().__init__(account, data_dir)
        self._clients: dict[str, object] = {}

    async def discover(self, timeout=6.0):
        hits = await ssdp_search("urn:lge-com:service:webos-second-screen:1", timeout=3)
        found, seen = [], set()
        for h in hits:
            ip = h["ip"]
            if ip in seen:
                continue
            seen.add(ip)
            uuid = h.get("usn", "").split("::")[0]
            found.append(self._found(ip, await self._mac_for(ip), uuid, detail=f"{ip} · webOS"))
        if not found:
            found = await self._scan_for_tvs(seen)
        return found

    def _found(self, ip: str, mac: str | None, uuid: str = "", *, detail: str) -> Found:
        """The same TV gets the same uid however it was found: its MAC when the panel can learn it.
        The SSDP uuid (the uid used before) is kept as an alias so TVs saved earlier still match."""
        uid = mac or uuid or ip
        config = {"ip": ip, "mac": mac or ""}
        if uuid:
            config["uuid"] = uuid
        return Found(adapter=self.id, uid=uid, name="LG TV", kind=Kind.TV, caps=CAPS, config=config,
                     detail=detail, needs_pairing=True, aliases=[uuid] if uuid and uuid != uid else [])

    async def _mac_for(self, ip: str) -> str | None:
        """The TV's MAC from the ARP cache. An SSDP reply doesn't always put the TV there,
        so knock on its remote-control port once and look again."""
        mac = mac_from_arp(ip)
        if not mac and (await port_open(ip, 3000, 1.0) or await port_open(ip, 3001, 1.0)):
            mac = mac_from_arp(ip)
        return normalize_mac(mac)

    async def _scan_for_tvs(self, skip: set) -> list[Found]:
        """Fallback when the network blocks discovery broadcasts (common with mesh Wi-Fi and
        some Macs): look for the webOS remote-control port on every address nearby."""
        hosts = [h for h in local_subnet_hosts() if h not in skip]
        open_hosts = await scan_ports(hosts, WEBOS_PORTS)
        found = []
        for ip in sorted(open_hosts):
            if not await self._looks_like_webos(ip):
                continue
            found.append(self._found(ip, await self._mac_for(ip), detail=f"{ip} · found by network scan"))
        return found

    def known_ids(self, device: Device) -> set[str]:
        """Also match TVs saved under their SSDP uuid by the MAC learned after pairing, and the reverse."""
        extra = {normalize_mac(device.config.get("mac")), device.config.get("uuid")}
        return super().known_ids(device) | {i for i in extra if i}

    async def _looks_like_webos(self, ip: str) -> bool:
        """webOS answers plain HTTP on port 3000 with a short 'Hello world' page."""
        try:
            body = await http("GET", f"http://{ip}:3000/", timeout=1.5)
        except Exception:
            return await port_open(ip, 3001, 1.0) and await port_open(ip, 3000, 1.0)
        return isinstance(body, str) and "hello" in body.lower()

    def from_manual(self, values):
        if not values.get("ip"):
            raise AdapterError("IP address is required.")
        mac = normalize_mac(values.get("mac"))
        return Found(adapter=self.id, uid=mac or values["ip"], name=values.get("name") or "LG TV", kind=Kind.TV,
                     caps=CAPS, config={"ip": values["ip"], "mac": mac or values.get("mac", "")}, needs_pairing=True,
                     aliases=[values["ip"]] if mac else [])

    async def _client(self, device: Device, *, pairing=False):
        c = self._clients.get(device.id)
        if c is not None and _connected(c):
            return c
        from aiowebostv import WebOsClient
        key = device.config.get("client_key")
        if not key and not pairing:
            raise PairingRequired("This TV isn't paired yet. Choose Pair and accept the prompt on the TV.")
        c = WebOsClient(device.config["ip"], key)
        await c.connect()
        self._clients[device.id] = c
        if c.client_key and c.client_key != key:
            device.config["client_key"] = c.client_key
        return c

    async def _drop(self, device: Device):
        c = self._clients.pop(device.id, None)
        if c:
            try:
                await c.disconnect()
            except Exception:
                pass

    async def setup(self, device: Device):
        ip = device.config["ip"]
        if not (await port_open(ip, 3000, 2) or await port_open(ip, 3001, 2)):
            raise AdapterError("Can't reach the TV. Turn it on and make sure it's on the same Wi-Fi.")
        try:
            c = await asyncio.wait_for(self._client(device, pairing=True), 40)
        except AdapterError:
            raise
        except Exception as e:
            await self._drop(device)
            raise PairingRequired(f"Accept the prompt on the TV, then choose Pair again. ({e})")
        await self._learn_mac(device, c)
        info = getattr(getattr(c, "tv_info", None), "system", None) or _tv(c, "system_info") or {}
        if isinstance(info, dict) and info.get("modelName"):
            device.meta["model"] = info["modelName"]
        self._update_meta(device, c)

    def _update_meta(self, device: Device, c):
        apps = _tv(c, "apps") or {}
        inputs = _tv(c, "inputs") or {}
        if apps:
            device.meta["apps"] = sorted(({"id": k, "name": v.get("title", k)} for k, v in apps.items()
                                          if not v.get("systemApp")), key=lambda a: a["name"].lower())
        if inputs:
            device.meta["inputs"] = [{"id": v.get("id", k), "name": v.get("label", k), "app_id": v.get("appId")}
                                     for k, v in inputs.items()]

    async def forget(self, device):
        await self._drop(device)

    async def _learn_mac(self, device: Device, c) -> None:
        """Ask the TV for its own network address (needed later to switch it on)."""
        if device.config.get("mac"):
            return
        info = getattr(getattr(c, "tv_info", None), "connection", None)
        if not isinstance(info, dict) and hasattr(c, "get_connection_info"):
            try:
                info = await asyncio.wait_for(c.get_connection_info(), 5)
            except Exception:
                info = None
        mac = mac_from_connection_info(info, device.config.get("ip")) or mac_from_arp(device.config["ip"])
        if mac:
            device.config["mac"] = mac

    async def refresh(self, device: Device) -> dict:
        ip = device.config["ip"]
        if not (await port_open(ip, 3000, 1.5) or await port_open(ip, 3001, 1.5)):
            await self._drop(device)
            return {"on": False}
        c = await self._client(device)
        await self._learn_mac(device, c)
        for cap in CAPS:                    # TVs added before a feature existed get it too (e.g. the pointer)
            if cap not in device.caps:
                device.caps.append(cap)
        if not device.meta.get("apps"):
            self._update_meta(device, c)
        app = _tv(c, "current_app_id")
        # an input (HDMI 1 …) shows up as the "current app" with the input's appId
        current_input = next((i["id"] for i in device.meta.get("inputs", []) if i.get("app_id") and i["app_id"] == app), None)
        return {"on": bool(_tv(c, "is_on", True)), "volume": _tv(c, "volume"),
                "muted": bool(_tv(c, "muted", False)), "app": None if current_input else app, "input": current_input}

    async def command(self, device: Device, action: str, value=None):
        if action == Action.POWER and value:
            if device.state.get("on"):
                return {"on": True}
            ip = device.config["ip"]
            mac = device.config.get("mac") or mac_from_arp(ip)
            if not mac:
                raise AdapterError(f"{device.name} can't be turned on yet because the panel doesn't know its MAC address. "
                                   "Turn the TV on with its remote once and the panel learns it, or enter it in "
                                   "Settings → Devices.")
            device.config["mac"] = mac
            await wake_on_lan(mac, ip)
            for _ in range(10):                      # wait for the TV's network to wake up
                if await port_open(ip, 3001, 1) or await port_open(ip, 3000, 1):
                    break
                await asyncio.sleep(1)
            return {"on": True}
        try:
            c = await self._client(device)
        except (OSError, asyncio.TimeoutError):
            raise AdapterError("The TV is off or not reachable.")
        try:
            if action == Action.POWER:
                await c.power_off()
                await self._drop(device)
                return {"on": False}
            if action == Action.VOLUME_UP:
                await c.volume_up()
            elif action == Action.VOLUME_DOWN:
                await c.volume_down()
            elif action == Action.VOLUME:
                await c.set_volume(value)
                return {"volume": value}
            elif action == Action.MUTE:
                await c.set_mute(value)
                return {"muted": value}
            elif action == Action.CHANNEL_UP:
                await c.channel_up()
            elif action == Action.CHANNEL_DOWN:
                await c.channel_down()
            elif action == Action.KEY:
                media = {Key.PLAY: "play", Key.PAUSE: "pause", Key.STOP: "stop",
                         Key.FORWARD: "fast_forward", Key.REWIND: "rewind"}   # same calls Home Assistant uses
                if value in media and hasattr(c, media[value]):
                    await getattr(c, media[value])()
                else:
                    await c.button(BUTTONS[value])
            elif action == Action.LAUNCH_APP:
                await c.launch_app(value)
                return {"app": value}
            elif action == Action.SET_INPUT:
                await c.set_input(value)
                return {"input": value, "app": None}
            elif action == Action.POINTER:
                await pointer(c, value)
            else:
                raise AdapterError("Not supported")
        except (ConnectionError, OSError):
            await self._drop(device)
            raise
        return {}


async def pointer(c, value: dict) -> None:
    """The Magic Remote pointer, over webOS's pointer input socket (already normalized by the service)."""
    if value.get("click"):
        await c.click()
    elif "scroll" in value:
        await c.scroll(0, value["scroll"])
    else:
        await c.move(value.get("dx", 0), value.get("dy", 0))


def mac_from_connection_info(info, ip: str | None = None) -> str | None:
    """Pull the MAC out of webOS connection info ({'wifiInfo': {'macAddress': …, 'ipAddress': …}, 'wiredInfo': …}).
    Prefers the interface the panel is talking to."""
    if not isinstance(info, dict):
        return None
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("macAddress"):
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(info)
    found.sort(key=lambda n: (n.get("ipAddress") != ip, not n.get("connected", True)))
    for node in found:
        mac = normalize_mac(node["macAddress"])
        if mac:
            return mac
    return None


def _connected(c) -> bool:
    f = getattr(c, "is_connected", None)
    try:
        return bool(f() if callable(f) else f)
    except Exception:
        return False
