"""
LG sound bars with Wi-Fi (2018 and newer) over the local network.

They answer on TCP port 9741 with LG's own protocol: JSON messages, AES-encrypted
with a fixed key every LG sound bar shares (the protocol the LG Sound Bar app and
Home Assistant's lg_soundbar integration use). No account or pairing.

The protocol is small, so it is implemented here with asyncio rather than through
the `temescal` library Home Assistant uses (blocking sockets with a listener
thread). Only `cryptography` is needed for AES.

Each message on the wire: 0x10, a 4-byte big-endian length, then the AES-256-CBC
ciphertext (PKCS#7 padding) of a JSON object such as
{"cmd": "get", "msg": "SPK_LIST_VIEW_INFO"}. The sound bar replies with
{"cmd": "notibyget", "msg": "SPK_LIST_VIEW_INFO", "data": {...}}.
"""
from __future__ import annotations

import asyncio
import json
import struct

from ..core.adapter import Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found, Kind, register
from ..core.net import local_subnet_hosts, mac_from_arp, normalize_mac, scan_ports

PORT = 9741
_KEY = b"T^&*J%^7tr~4^%^&I(o%^!jIJ__+a0 k"   # shared by every LG sound bar, not a secret
_IV = b"'%^Ur7gy$~t+f)%@"

SPEAKER = "SPK_LIST_VIEW_INFO"   # volume, mute, power, current input, name
INPUTS = "FUNC_VIEW_INFO"        # current input and the inputs this model has
SOUND = "EQ_VIEW_INFO"           # current sound mode and the modes this model has
PRODUCT = "PRODUCT_INFO"         # model name and MAC address

# Input ("function") numbers, in protocol order.
INPUT_NAMES = ["Wi-Fi", "Bluetooth", "Portable", "Aux", "Optical", "CP", "HDMI", "HDMI ARC", "Spotify",
               "Optical 2", "HDMI 2", "HDMI 3", "LG TV", "Mic", "Chromecast", "Optical / HDMI ARC",
               "LG Optical", "FM", "USB", "USB 2", "HDMI eARC"]
# Sound mode ("equaliser") numbers, in protocol order. Newer models report higher
# numbers too; their names are not documented by that protocol table.
# Reference: mjg59/python-temescal, revision 7460c04, temescal/__init__.py.
SOUND_MODE_NAMES = ["Standard", "Bass", "Flat", "Boost", "Treble and bass", "User EQ", "Music", "Cinema",
                    "Night", "News", "Voice", "ia Sound", "Adaptive sound control", "Movie", "Bass blast",
                    "Dolby Atmos", "DTS Virtual:X", "Bass boost plus", "DTS:X", "AI Sound Pro",
                    "Clear voice", "Sports", "Game"]
FORMAT_MODES = {15, 16, 18}  # codec/format-dependent names, not guaranteed ordinary EQ presets
# Inputs that are the same socket under another name. A sound bar may report, say,
# eARC (20) as the current input while offering "Optical / HDMI ARC" (15) in its list.
SAME_INPUT = ((15, 20, 7, 16, 4, 9), (6, 10, 11), (18, 19), (1, 2), (0, 14, 8))

CAPS = [Cap.POWER, Cap.VOLUME, Cap.VOLUME_LEVEL, Cap.MUTE, Cap.INPUTS, Cap.SOUND_MODE]


def _name(names: list[str], i: int, fallback: str) -> str:
    return names[i] if 0 <= i < len(names) else f"{fallback} {i}"


def input_name(i: int) -> str:
    return _name(INPUT_NAMES, i, "Device-reported input")


def sound_mode_name(i: int) -> str:
    return _name(SOUND_MODE_NAMES, i, "Device-reported mode")


def shown_input(current: int | None, offered: list[int]) -> int | None:
    """The input from the offered list to highlight for the current one."""
    if current is None or current in offered:
        return current
    group = next((g for g in SAME_INPUT if current in g), ())
    return next((i for i in group if i in offered), current)


def to_percent(raw: int, lo: int, hi: int) -> int:
    return max(0, min(100, round((raw - lo) * 100 / (hi - lo)))) if hi > lo else 0


def from_percent(pct: int, lo: int, hi: int) -> int:
    return lo + round(max(0, min(100, pct)) * (hi - lo) / 100)


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

def _cipher():
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    return Cipher(algorithms.AES(_KEY), modes.CBC(_IV))


def encode(message: dict) -> bytes:
    data = json.dumps(message).encode()
    pad = 16 - len(data) % 16
    enc = _cipher().encryptor()
    body = enc.update(data + bytes([pad]) * pad) + enc.finalize()
    return b"\x10" + struct.pack(">I", len(body)) + body


def decode(body: bytes) -> dict:
    dec = _cipher().decryptor()
    data = dec.update(body) + dec.finalize()
    pad = data[-1] if data else 0
    if not 1 <= pad <= 16:
        raise ValueError("bad padding")
    return json.loads(data[:-pad])


class Link:
    """One short connection to a sound bar."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer

    @classmethod
    async def open(cls, ip: str, port: int = PORT, timeout: float = 4.0) -> Link:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
        return cls(reader, writer)

    async def send(self, message: dict) -> None:
        self.writer.write(encode(message))
        await self.writer.drain()

    async def read(self) -> dict:
        head = await self.reader.readexactly(5)
        size = struct.unpack(">I", head[1:])[0]
        if head[0] != 0x10 or size % 16 or size > 1 << 20:
            raise ConnectionError("unexpected reply")
        return decode(await self.reader.readexactly(size))

    async def ask(self, *names: str, timeout: float = 3.0) -> dict[str, dict]:
        """Request each message and collect the replies that arrive within `timeout`."""
        for n in names:
            await self.send({"cmd": "get", "msg": n})
        got: dict[str, dict] = {}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while set(names) - set(got):
            left = deadline - loop.time()
            if left <= 0:
                break
            try:
                m = await asyncio.wait_for(self.read(), left)
            except asyncio.TimeoutError:
                break
            if m.get("msg") in names and isinstance(m.get("data"), dict):
                got[m["msg"]] = m["data"]
        return got

    async def set(self, msg: str, data: dict) -> None:
        await self.send({"cmd": "set", "msg": msg, "data": data})
        try:   # the sound bar answers with its new state; give it a moment before hanging up
            await asyncio.wait_for(self.read(), 1.0)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------

@register
class LGSoundbarAdapter(DeviceAdapter):
    id = "lg_soundbar"
    name = "LG sound bar"
    brands = "LG sound bars with Wi-Fi (2018 and newer)"
    kinds = (Kind.SPEAKER,)
    description = "Volume, inputs and sound modes over Wi-Fi. No account or pairing needed."
    requires = ("cryptography",)
    poll_interval = 10
    manual_fields = [
        Field("name", "Name", required=True, placeholder="Living room sound bar"),
        Field("ip", "IP address", required=True,
              help="LG Soundbar app → your sound bar → Settings → Information, or your router's device list."),
    ]

    def __init__(self, account, data_dir):
        super().__init__(account, data_dir)
        self._locks: dict[str, asyncio.Lock] = {}
        self._volume_range: dict[str, tuple[int, int]] = {}
        self._offered_inputs: dict[str, list[int]] = {}

    # --- discovery ------------------------------------------------------------
    async def discover(self, timeout=6.0):
        open_hosts = await scan_ports(local_subnet_hosts(), (PORT,))
        found = []
        for ip in sorted(open_hosts):
            try:
                info = await self._identify(ip, open_hosts[ip])
            except Exception:
                continue
            if info:
                found.append(info)
        return found

    async def _identify(self, ip: str, port: int = PORT) -> Found | None:
        link = await Link.open(ip, port, 3)
        try:
            got = await link.ask(PRODUCT, SPEAKER, timeout=3)
        finally:
            await link.close()
        if SPEAKER not in got:
            return None
        product, speaker = got.get(PRODUCT, {}), got[SPEAKER]
        mac = normalize_mac(product.get("s_dev_mac")) or mac_from_arp(ip) or ""
        model = product.get("s_model_name") or "LG sound bar"
        config = {"ip": ip, "mac": mac}
        if port != PORT:
            config["port"] = port
        return Found(adapter=self.id, uid=mac or ip, name=speaker.get("s_user_name") or "LG sound bar",
                     kind=Kind.SPEAKER, caps=CAPS, config=config, detail=f"{ip} · {model}")

    def from_manual(self, values):
        ip = (values.get("ip") or "").strip()
        if not ip:
            raise AdapterError("IP address is required.")
        return Found(adapter=self.id, uid=ip, name=values.get("name") or "LG sound bar", kind=Kind.SPEAKER,
                     caps=CAPS, config={"ip": ip})

    # --- connection -----------------------------------------------------------
    def _lock(self, device: Device) -> asyncio.Lock:
        return self._locks.setdefault(device.id, asyncio.Lock())

    async def _open(self, device: Device) -> Link:
        try:
            return await Link.open(device.config["ip"], int(device.config.get("port") or PORT))
        except (OSError, asyncio.TimeoutError):
            raise ConnectionError(f"Can't reach the sound bar at {device.config['ip']}. "
                                  "Check that it's plugged in and on the same Wi-Fi as the panel.")

    async def setup(self, device: Device):
        try:
            async with self._lock(device):
                link = await self._open(device)
                try:
                    product = (await link.ask(PRODUCT, timeout=3)).get(PRODUCT, {})
                finally:
                    await link.close()
        except ConnectionError as e:
            raise AdapterError(str(e))
        if product.get("s_model_name"):
            device.meta["model"] = product["s_model_name"]
        mac = normalize_mac(product.get("s_dev_mac")) or mac_from_arp(device.config["ip"])
        if mac:
            device.config["mac"] = mac
        await self.refresh(device)

    # --- state ----------------------------------------------------------------
    async def refresh(self, device: Device) -> dict:
        async with self._lock(device):
            link = await self._open(device)
            try:
                got = await link.ask(SPEAKER, INPUTS, SOUND)
            except (OSError, ValueError, asyncio.IncompleteReadError) as e:
                raise ConnectionError(f"The sound bar sent something unexpected: {e}")
            finally:
                await link.close()
        if SPEAKER not in got:
            raise ConnectionError("The sound bar didn't answer. Try again in a moment.")
        return self._state(device, got)

    def _state(self, device: Device, got: dict[str, dict]) -> dict:
        spk, func, eq = got[SPEAKER], got.get(INPUTS, {}), got.get(SOUND, {})
        lo, hi = int(spk.get("i_vol_min", 0)), int(spk.get("i_vol_max", 40) or 40)
        self._volume_range[device.id] = (lo, hi)
        state: dict = {"on": bool(spk.get("b_powerstatus", True)), "muted": bool(spk.get("b_mute"))}
        if "i_vol" in spk:
            state["volume"] = to_percent(int(spk["i_vol"]), lo, hi)

        offered = [int(i) for i in func.get("ai_func_list") or []]
        if offered:
            self._offered_inputs[device.id] = offered
            device.meta["inputs"] = [{"id": str(i), "name": input_name(i)} for i in offered]
        current = func.get("i_curr_func", spk.get("i_curr_func"))
        if current is not None:
            shown = shown_input(int(current), self._offered_inputs.get(device.id, []))
            state["input"] = str(shown)

        modes = [int(i) for i in eq.get("ai_eq_list") or []]
        if modes:
            device.meta["sound_modes"] = [
                {"id": str(i), "name": sound_mode_name(i),
                 **({"advanced": True} if i in FORMAT_MODES or not 0 <= i < len(SOUND_MODE_NAMES) else {})}
                for i in modes]
        if str(device.meta.get("model", "")).upper().startswith("S95TR"):
            device.meta["playback_help"] = (
                "For Spotify, start music in the Spotify app on your phone, open Devices and choose this speaker. "
                "Use the same Wi-Fi for the first connection. Music sound mode changes EQ; it does not start playback.")
        if eq.get("i_curr_eq") is not None:
            state["sound_mode"] = str(eq["i_curr_eq"])
        return state

    # --- commands -------------------------------------------------------------
    async def command(self, device: Device, action: str, value=None):
        if action != Action.POWER and device.state.get("on") is False:
            raise AdapterError(f"{device.name} is off. Turn it on first.")
        async with self._lock(device):
            link = await self._open(device)
            try:
                return await self._command(device, link, action, value)
            except (OSError, ValueError, asyncio.IncompleteReadError):
                raise ConnectionError("The sound bar closed the connection. Try again in a moment.")
            finally:
                await link.close()

    async def _command(self, device: Device, link: Link, action: str, value):
        if action == Action.POWER:
            await link.set(SPEAKER, {"b_powerkey": bool(value)})
            return {"on": bool(value)}
        if action == Action.MUTE:
            await link.set(SPEAKER, {"b_mute": bool(value)})
            return {"muted": bool(value)}
        if action in (Action.VOLUME, Action.VOLUME_UP, Action.VOLUME_DOWN):
            spk = (await link.ask(SPEAKER, timeout=2)).get(SPEAKER, {})   # start from the real level
            lo, hi = int(spk.get("i_vol_min", 0)), int(spk.get("i_vol_max", 0) or 0)
            if hi <= lo:
                lo, hi = self._volume_range.get(device.id, (0, 40))
            self._volume_range[device.id] = (lo, hi)
            if action == Action.VOLUME:
                raw = from_percent(int(value), lo, hi)
            else:
                now = int(spk["i_vol"]) if "i_vol" in spk else from_percent(device.state.get("volume") or 0, lo, hi)
                raw = max(lo, min(hi, now + (1 if action == Action.VOLUME_UP else -1)))
            await link.set(SPEAKER, {"i_vol": raw})
            return {"volume": to_percent(raw, lo, hi)}
        if action == Action.SET_INPUT:
            try:
                i = int(value)
            except (TypeError, ValueError):
                i = -1
            offered = self._offered_inputs.get(device.id) or [int(x["id"]) for x in device.meta.get("inputs", [])]
            if i not in offered:
                raise AdapterError(f"{device.name} doesn't have that input. Pick one from the list.")
            await link.set(INPUTS, {"i_curr_func": i})
            return {"input": str(i)}
        if action == Action.SET_SOUND_MODE:
            await link.set(SOUND, {"i_curr_eq": int(value)})
            return {"sound_mode": str(value)}
        raise AdapterError("Not supported")
