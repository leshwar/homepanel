"""Small dependency-free network helpers shared by adapters."""
from __future__ import annotations

import asyncio
import colorsys
import ipaddress
import json
import math
import os
import socket
import ssl
from typing import Any
from urllib.parse import urlsplit


class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


async def http(method: str, url: str, *, json_body: Any = None, headers: dict | None = None,
               timeout: float = 5.0, verify_tls: bool = True) -> Any:
    """Minimal async HTTP/1.1 client returning parsed JSON (or text)."""
    parts = urlsplit(url)
    secure = parts.scheme == "https"
    host = parts.hostname
    port = parts.port or (443 if secure else 80)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query

    body = b""
    hdrs = {"Host": host if port in (80, 443) else f"{host}:{port}",
            "Connection": "close", "Accept": "application/json",
            "User-Agent": "HomePanel/1.0"}
    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"
    if body or method in ("POST", "PUT", "PATCH"):
        hdrs["Content-Length"] = str(len(body))
    hdrs.update(headers or {})

    ctx = None
    if secure:
        ctx = ssl.create_default_context()
        if not verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

    async def _do():
        reader, writer = await asyncio.open_connection(host, port, ssl=ctx,
                                                       server_hostname=host if secure else None)
        try:
            head = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())
            writer.write(head.encode() + b"\r\n" + body)
            await writer.drain()
            raw = await reader.read()
        finally:
            writer.close()
        return raw

    raw = await asyncio.wait_for(_do(), timeout)
    head, _, payload = raw.partition(b"\r\n\r\n")
    lines = head.decode(errors="replace").split("\r\n")
    status = int(lines[0].split()[1])
    resp_headers = {ln.split(":", 1)[0].lower(): ln.split(":", 1)[1].strip() for ln in lines[1:] if ":" in ln}
    if resp_headers.get("transfer-encoding", "").lower() == "chunked":
        payload = _dechunk(payload)
    text = payload.decode(errors="replace")
    if status >= 400:
        raise HttpError(status, text)
    try:
        return json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        return text


def _dechunk(data: bytes) -> bytes:
    out = b""
    while data:
        size_line, _, rest = data.partition(b"\r\n")
        try:
            size = int(size_line.split(b";")[0], 16)
        except ValueError:
            break
        if size == 0:
            break
        out += rest[:size]
        data = rest[size + 2:]
    return out


# --- UDP -------------------------------------------------------------------

class _Collector(asyncio.DatagramProtocol):
    def __init__(self):
        self.items: list[tuple[bytes, tuple]] = []
        self.event = asyncio.Event()

    def datagram_received(self, data, addr):
        self.items.append((data, addr))
        self.event.set()


async def udp_query(host: str, port: int, payload: bytes, *, timeout: float = 2.0,
                    broadcast: bool = False, collect: bool = False, bind_port: int = 0):
    """Send one datagram. Return the first reply (or every reply if collect=True)."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if broadcast:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if is_multicast(host):
        # Macs often have extra interfaces (VPN, Docker, Thunderbolt bridge). Send discovery
        # out of the interface that reaches the home network, not whichever the OS picks.
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local_ip()))
        except OSError:
            pass
    sock.bind(("0.0.0.0", bind_port))
    transport, proto = await loop.create_datagram_endpoint(_Collector, sock=sock)
    try:
        transport.sendto(payload, (host, port))
        if collect:
            await asyncio.sleep(timeout)
            return proto.items
        try:
            await asyncio.wait_for(proto.event.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        return proto.items[0]
    finally:
        transport.close()


async def wake_on_lan(mac: str, broadcast: str = "255.255.255.255") -> None:
    """Send a Wake-on-LAN magic packet (used to turn TVs on)."""
    clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(clean) != 12:
        raise ValueError("MAC address should look like AA:BB:CC:DD:EE:FF")
    packet = b"\xff" * 6 + bytes.fromhex(clean) * 16
    loop = asyncio.get_running_loop()

    def _send():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for _ in range(3):
                s.sendto(packet, (broadcast, 9))
                s.sendto(packet, (broadcast, 7))
    await loop.run_in_executor(None, _send)


async def ssdp_search(target: str = "ssdp:all", timeout: float = 3.0) -> list[dict]:
    """UPnP SSDP M-SEARCH. Returns a list of response header dicts (+ 'ip')."""
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
           'MAN: "ssdp:discover"\r\nMX: 2\r\n' f"ST: {target}\r\n\r\n").encode()
    replies = await udp_query("239.255.255.250", 1900, msg, timeout=timeout, collect=True)
    results = []
    for data, addr in replies or []:
        headers = {"ip": addr[0]}
        for line in data.decode(errors="replace").split("\r\n")[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        results.append(headers)
    return results


def is_multicast(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_multicast
    except ValueError:
        return False


def in_container() -> bool:
    """True when running inside Docker (where Docker Desktop on Mac/Windows hides the home network)."""
    return os.path.exists("/.dockerenv")


async def scan_ports(hosts: list[str], ports: tuple[int, ...], timeout: float = 0.8,
                     concurrency: int = 128) -> dict[str, int]:
    """Which hosts accept a TCP connection on any of `ports`? Returns {ip: first open port}.
    A fallback for finding devices when multicast discovery is blocked by the network."""
    sem = asyncio.Semaphore(concurrency)
    found: dict[str, int] = {}

    async def probe(ip):
        async with sem:
            for p in ports:
                if await port_open(ip, p, timeout):
                    found[ip] = p
                    return

    await asyncio.gather(*(probe(h) for h in hosts))
    return found


async def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        w.close()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


def mac_from_arp(ip: str) -> str | None:
    """Look up a device's MAC in the Linux ARP cache (works after we've talked to it)."""
    try:
        with open("/proc/net/arp") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if parts and parts[0] == ip and parts[3] != "00:00:00:00:00:00":
                    return parts[3].upper()
    except OSError:
        pass
    return None


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def local_subnet_hosts() -> list[str]:
    """Every host in this machine's /24 (good enough for home networks)."""
    net = ipaddress.ip_network(f"{local_ip()}/24", strict=False)
    return [str(h) for h in net.hosts()]


# --- colour helpers ----------------------------------------------------------

def parse_color(value) -> dict:
    if isinstance(value, dict):
        return {k: max(0, min(255, int(value.get(k, 0)))) for k in ("r", "g", "b")}
    if isinstance(value, str):
        v = value.lstrip("#")
        if len(v) == 6:
            return {"r": int(v[0:2], 16), "g": int(v[2:4], 16), "b": int(v[4:6], 16)}
    raise ValueError("Color should be #rrggbb or {r,g,b}")


def rgb_to_hsv(c: dict) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(c["r"] / 255, c["g"] / 255, c["b"] / 255)


def hsv_to_rgb(h: float, s: float, v: float) -> dict:
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return {"r": round(r * 255), "g": round(g * 255), "b": round(b * 255)}


def kelvin_to_rgb(k: float) -> dict:
    """Approximate colour of white light at a temperature (for the UI tile glow)."""
    t = k / 100
    r = 255 if t <= 66 else 329.7 * ((t - 60) ** -0.1332)
    g = 99.47 * math.log(t) - 161.12 if t <= 66 else 288.12 * ((t - 60) ** -0.0755)
    b = 255 if t >= 66 else (0 if t <= 19 else 138.52 * math.log(t - 10) - 305.04)
    clamp = lambda x: int(max(0, min(255, x)))
    return {"r": clamp(r), "g": clamp(g), "b": clamp(b)}


def rgb_to_xy(c: dict) -> list[float]:
    """sRGB -> CIE xy (Philips Hue)."""
    def lin(v):
        v /= 255
        return ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92
    r, g, b = lin(c["r"]), lin(c["g"]), lin(c["b"])
    X = r * 0.4124 + g * 0.3576 + b * 0.1805
    Y = r * 0.2126 + g * 0.7152 + b * 0.0722
    Z = r * 0.0193 + g * 0.1192 + b * 0.9505
    total = X + Y + Z
    if total == 0:
        return [0.3127, 0.3290]
    return [round(X / total, 4), round(Y / total, 4)]


def xy_to_rgb(x: float, y: float, bri: float = 1.0) -> dict:
    z = 1.0 - x - y
    Y = bri
    X = (Y / y) * x if y else 0
    Z = (Y / y) * z if y else 0
    r = X * 3.2406 - Y * 1.5372 - Z * 0.4986
    g = -X * 0.9689 + Y * 1.8758 + Z * 0.0415
    b = X * 0.0557 - Y * 0.2040 + Z * 1.0570
    m = max(r, g, b, 1e-6)
    r, g, b = (max(0, v / m) for v in (r, g, b))
    gamma = lambda v: 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return {"r": round(gamma(r) * 255), "g": round(gamma(g) * 255), "b": round(gamma(b) * 255)}
