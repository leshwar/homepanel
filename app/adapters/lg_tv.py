"""
LG webOS Smart TVs over the local network, via the aiowebostv library.

First connection: the TV shows a prompt — press Accept with the TV remote. The
key is saved so it's asked only once.
To turn the TV on, enable Quick Start+ and "Turn on via Wi-Fi" (wording varies by year).
Recent webOS versions put Quick Start+ under General → System → Additional Settings.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import ipaddress
import logging
import time
from urllib.parse import urlsplit
import uuid
import xml.etree.ElementTree as ET

from ..core.adapter import (Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found, Key,
                            Kind, PairingRequired, register)
from ..core.net import (http, local_subnet_hosts, mac_from_arp, normalize_mac, port_open, scan_ports,
                        ssdp_search, wake_on_lan)

WEBOS_PORTS = (3001, 3000)   # webOS remote control: secure, then plain (older TVs)
WAKE_READY_TIMEOUT = 28.0
WAKE_POLL = .5
RECOVERY_INTERVAL = 60.0
log = logging.getLogger("homepanel")


def _saved_uuid(config):
    raw = config.get("uuid") or config.get("_uid", "")
    if not isinstance(raw, str) or not raw.lower().startswith("uuid:"):
        return None
    try:
        return "uuid:" + str(uuid.UUID(raw[5:]))
    except ValueError:
        return None


def _socket_open(socket) -> bool:
    return socket is not None and not socket.closed


def _reported_power(power):
    value = power.get("state") if isinstance(power, dict) else None
    if value in ("Power Off", "Suspend", "Active Standby"):
        return False
    if value in ("Active", "Screen Saver", "Screen Off"):
        return True
    return None


def _control_connected(client) -> bool:
    return _connected(client) and _socket_open(getattr(client, "connection", None)) \
        and _socket_open(getattr(client, "input_connection", None))


def _new_client(device, *, pairing=False, mac_verified=False):
    """Check pre-registration identity before sending a saved key to a new socket."""
    from aiowebostv import WebOsClient
    if not hasattr(WebOsClient, "_get_pre_reg_system_info") or not hasattr(WebOsClient, "_check_registration"):
        raise AdapterError("LG TV support needs aiowebostv 0.10 or newer. Update the panel's dependencies before reconnecting.")
    expected_model = device.meta.get("model")
    key = device.config.get("client_key")

    class PairedClient(WebOsClient):
        async def _check_registration(self, ws):
            if pairing:
                return await super()._check_registration(ws)
            model = (self.tv_info.system or {}).get("modelName")
            if expected_model and model != expected_model:
                raise AdapterError("This address did not confirm the saved TV model. Its pairing key was not sent.")
            if not expected_model and not mac_verified:
                raise AdapterError("The TV identity cannot be verified automatically. Check its address and pairing.")
            await ws.send_json(self.registration_msg())
            async with asyncio.timeout(4):
                response = await ws.receive_json()
            if response.get("type") != "registered" or (response.get("payload") or {}).get("client-key") != key:
                raise PairingRequired("The TV did not accept its saved pairing. Pair again while the TV is on.")

    return PairedClient(device.config["ip"], key)

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
    refresh_timeout = 20.0
    retry_commands = False  # a timed-out input write may already have reached the TV
    wake_timeout = 50.0
    startup_screens = [{"id": "previous", "name": "Previous input (TV default)"}, {"id": "home", "name": "TV Home"}]
    manual_fields = [
        Field("name", "Name", required=True, placeholder="Bedroom TV"),
        Field("ip", "IP address", required=True, help="TV → Settings → Network → Wi-Fi → Advanced Wi-Fi Settings."),
        Field("mac", "MAC address (to turn on)", placeholder="Found automatically if left blank"),
    ]

    def __init__(self, account, data_dir):
        super().__init__(account, data_dir)
        self._clients: dict[str, object] = {}
        self._client_locks: dict[str, asyncio.Lock] = {}
        self._waking: set[str] = set()
        self._device_locks: dict[str, asyncio.Lock] = {}
        self._operations: dict[str, set[asyncio.Task]] = {}
        self._recover_after: dict[str, float] = {}
        self._forgotten: set[str] = set()
        self._stopped = False

    @asynccontextmanager
    async def _operation(self, device):
        task = asyncio.current_task()
        tasks = self._operations.setdefault(device.id, set())
        tasks.add(task)
        try:
            async with self._device_locks.setdefault(device.id, asyncio.Lock()):
                if self._stopped or device.id in self._forgotten:
                    raise AdapterError("This TV connection is closing.")
                yield
        finally:
            tasks.discard(task)

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
        async with self._client_locks.setdefault(device.id, asyncio.Lock()):
            c = self._clients.get(device.id)
            if c is not None and _control_connected(c):
                return c
            await self._drop(device)
            key = device.config.get("client_key")
            if not key and not pairing:
                raise PairingRequired("This TV isn't paired yet. Choose Pair and accept the prompt on the TV.")
            mac = await asyncio.to_thread(mac_from_arp, device.config["ip"]) if not device.meta.get("model") else None
            c = _new_client(device, pairing=pairing, mac_verified=bool(mac) and normalize_mac(mac) == normalize_mac(device.config.get("mac")))
            connected = False
            try:
                await c.connect()
                if not _control_connected(c):
                    raise ConnectionError("The TV control connection isn't ready.")
                connected = True
            finally:
                if not connected:
                    await c.disconnect()
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
        async with self._operation(device):
            await self._setup(device)

    async def _setup(self, device):
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
        self._forgotten.add(device.id)
        tasks = [task for task in self._operations.get(device.id, ()) if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._drop(device)

    async def stop(self):
        self._stopped = True
        tasks = {task for tasks in self._operations.values() for task in tasks if task is not asyncio.current_task()}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for did in list(self._clients):
            await self._drop(Device(id=did, adapter=self.id, name="TV"))

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
        async with self._operation(device):
            try:
                c, power = await self._connection(device)
                await self._learn_mac(device, c)
            except PairingRequired:
                raise
            except AdapterError as error:
                last = device.state.get("last_known") if device.state.get("stale") else {
                    k: device.state[k] for k in ("on", "volume", "muted", "app", "input") if device.state.get(k) is not None}
                return {"online": False, "on": None, "stale": True, "last_known": last or None,
                        "remote_ready": False, "wake_available": bool(device.config.get("mac")),
                        "error": str(error)}
            return self._state(device, c, power)

    def _state(self, device, c, power):
        for cap in CAPS:                    # TVs added before a feature existed get it too (e.g. the pointer)
            if cap not in device.caps:
                device.caps.append(cap)
        if not device.meta.get("apps"):
            self._update_meta(device, c)
        app = _tv(c, "current_app_id")
        # an input (HDMI 1 …) shows up as the "current app" with the input's appId
        current_input = next((i["id"] for i in device.meta.get("inputs", []) if i.get("app_id") and i["app_id"] == app), None)
        return {"online": True, "on": _reported_power(power),
                 "screen_on": False if power.get("state") == "Screen Off" else _reported_power(power),
                 "stale": False, "last_known": None, "remote_ready": _control_connected(c),
                "wake_available": bool(device.config.get("mac")), "volume": _tv(c, "volume"),
                "muted": bool(_tv(c, "muted", False)), "app": None if current_input else app, "input": current_input}

    async def _connection(self, device):
        from aiohttp import ClientError
        from aiowebostv.exceptions import WebOsTvError
        pairing_error = None
        try:
            async with asyncio.timeout(4):
                c = await self._client(device)
                power = await c.get_power_state()
                if not isinstance(power, dict) or not power.get("state"):
                    raise ConnectionError("Power status not reported")
                return c, power
        except PairingRequired as error:
            pairing_error = error
        except (OSError, asyncio.TimeoutError, ClientError, WebOsTvError, AdapterError):
            pass
        await self._drop(device)
        recovered = await self._rediscover(device)
        if recovered:
            return recovered
        if pairing_error is not None:
            raise pairing_error
        raise AdapterError("TV connection unavailable; its power is unknown. Automatic address recovery could not verify it. "
                           "Check the TV's network connection.")

    async def _rediscover(self, device):
        from dataclasses import replace
        from aiohttp import ClientError
        from aiowebostv.exceptions import WebOsTvError
        identity = _saved_uuid(device.config)
        if not identity or not device.config.get("client_key") or time.monotonic() < self._recover_after.get(device.id, 0):
            return None
        self._recover_after[device.id] = time.monotonic() + RECOVERY_INTERVAL
        original = dict(device.config)
        client = None
        try:
            hits = await ssdp_search(identity, timeout=2)
            local = set(local_subnet_hosts())
            matches = {}
            for hit in hits:
                if hit.get("usn", "").split("::", 1)[0].lower() != identity:
                    continue
                address = hit.get("ip", "")
                try:
                    ip = ipaddress.ip_address(address)
                    location = urlsplit(hit.get("location", ""))
                    if (ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local
                            or address not in local or location.scheme != "http" or location.hostname != address
                            or location.username or location.password or location.fragment):
                        continue
                    if location.port is not None and not 1 <= location.port <= 65535:
                        continue
                except ValueError:
                    continue
                matches.setdefault(address, hit["location"])
            if len(matches) != 1:
                return None
            address, url = next(iter(matches.items()))
            document = await http("GET", url, timeout=2)
            if not isinstance(document, str) or len(document) > 65536 or "<!DOCTYPE" in document.upper():
                return None
            root = ET.fromstring(document)
            ns = {"u": "urn:schemas-upnp-org:device-1-0"}
            udn = root.findtext(".//u:device/u:UDN", namespaces=ns) or ""
            if udn.lower() != identity:
                return None
            mac = await asyncio.to_thread(mac_from_arp, address)
            saved_mac = normalize_mac(original.get("mac"))
            if mac and saved_mac and normalize_mac(mac) != saved_mac:
                return None
            mac_verified = bool(mac and saved_mac and normalize_mac(mac) == saved_mac)
            if not device.meta.get("model") and not mac_verified:
                return None
            candidate = replace(device, config={**original, "ip": address})
            client = _new_client(candidate, mac_verified=mac_verified)
            async with asyncio.timeout(7):
                await client.connect()
                if not _control_connected(client) or client.client_key != original["client_key"]:
                    return None
                reported_mac = mac_from_connection_info(getattr(client.tv_info, "connection", None), address)
                if saved_mac and normalize_mac(reported_mac) != saved_mac:
                    return None
                power = await client.get_power_state()
                if not isinstance(power, dict) or not power.get("state"):
                    return None
            if device.config != original or self._stopped or device.id in self._forgotten:
                return None
            device.config["ip"] = address
            self._clients[device.id] = client
            client = None
            log.info("%s: verified paired TV connection recovered", device.name)
            return self._clients[device.id], power
        except PairingRequired:
            raise
        except (OSError, asyncio.TimeoutError, ClientError, WebOsTvError, AdapterError, ET.ParseError):
            log.warning("%s: automatic address verification failed; saved identity unchanged", device.name)
            return None
        finally:
            if client is not None:
                await client.disconnect()

    async def command(self, device: Device, action: str, value=None):
        async with self._operation(device):
            result = await self._command(device, action, value)
            return {"online": True, "stale": False, "last_known": None, "error": None,
                    "remote_ready": not (action == Action.POWER and value is False), **result}

    async def _command(self, device: Device, action: str, value=None):
        if action == Action.POWER and value:
            return await self._wake(device)
        from aiohttp import ClientError
        from aiowebostv.exceptions import WebOsTvError
        c, _ = await self._connection(device)
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
        except (ConnectionError, OSError, asyncio.TimeoutError, ClientError, WebOsTvError):
            await self._drop(device)
            raise AdapterError("The TV connection was interrupted. Delivery is uncertain, so the action was not repeated. "
                               "Reconnect, then try the action again.") from None
        return {}

    async def _ready(self, device: Device):
        c = await self._client(device)
        power = await c.get_power_state()
        if _reported_power(power) is not True:
            return None
        socket = getattr(c, "input_connection", None)
        return c if socket is not None and not socket.closed else None

    async def _wake(self, device: Device):
        from aiohttp import ClientConnectionError
        from aiowebostv.exceptions import WebOsTvCommandError, WebOsTvCommandTimeoutError, WebOsTvPairError

        if device.state.get("on") is True and not device.state.get("stale"):
            return {"on": True}
        if not device.config.get("client_key"):
            raise PairingRequired("Pair the TV while it is on before waking it from HomePanel.")
        transient = (OSError, asyncio.TimeoutError, ClientConnectionError, WebOsTvCommandTimeoutError)
        self._waking.add(device.id)
        try:
            # A stale snapshot must not turn an already-on TV away from its input.
            # Keep deadlines in this task: Python 3.11 wait_for can lose a
            # cancellation racing with an already-completed readiness check.
            try:
                async with asyncio.timeout(2):
                    ready = await self._ready(device)
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                    if ready:
                        return {"on": True}
            except transient:
                await self._drop(device)
            # Recovery is read-only. If the same TV is already on at a new address,
            # neither a wake packet nor Home should be sent.
            recovered = await self._rediscover(device)
            if recovered and self._state(device, *recovered)["on"] is True:
                return {"on": True}
            ip = device.config["ip"]
            mac = device.config.get("mac") or mac_from_arp(ip)
            if not mac:
                raise AdapterError("The panel doesn't know this TV's MAC address. Turn it on with its remote once, "
                                   "or enter the address in Settings → Devices.")
            device.config["mac"] = mac
            await wake_on_lan(mac, ip)
            try:
                async with asyncio.timeout(WAKE_READY_TIMEOUT):
                    while True:
                        try:
                            async with asyncio.timeout(4):
                                c = await self._ready(device)
                            if asyncio.current_task().cancelling():
                                raise asyncio.CancelledError
                            if c is not None:
                                break
                        except transient:
                            await self._drop(device)
                        await asyncio.sleep(WAKE_POLL)
            except asyncio.TimeoutError:
                raise AdapterError("The TV did not become ready. Check Quick Start+ and Turn on via Wi-Fi on the TV, "
                                   "then try again. Home was not sent.") from None
            if device.power_on_screen == "home":
                # Never retry this write: a lost response must not send Home twice.
                try:
                    async with asyncio.timeout(3):
                        await c.button("HOME")
                except (*transient, WebOsTvCommandError):
                    raise AdapterError("The TV woke, but Home could not be opened. Use the Home button or try the TV remote.") from None
            return {"on": True}
        except WebOsTvPairError:
            raise PairingRequired("The TV no longer accepts this pairing. Pair again while the TV is on.") from None
        except WebOsTvCommandError:
            raise AdapterError("The TV did not confirm that its controls are ready. Check its connection and try again.") from None
        except BaseException:
            await self._drop(device)
            raise
        finally:
            self._waking.discard(device.id)


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
