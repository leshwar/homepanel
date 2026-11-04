"""Integration tests: real adapters talking over real sockets to simulated devices.

Each test starts a tiny local server that behaves like the device or service
(a Shelly plug, Home Assistant) and runs the actual adapter code against it.
"""
import asyncio
import json
import tempfile
import unittest

from app.core import net
from app.core.adapter import Action, AdapterError, Cap, Device, Kind


class HttpClientAgainstLocalServer(unittest.IsolatedAsyncioTestCase):
    """The dependency-free HTTP client talking to a tiny local server (mimics a Shelly)."""

    async def test_get_and_post_json(self):
        async def handle(reader, writer):
            req = await reader.readuntil(b"\r\n\r\n")
            line = req.split(b"\r\n")[0].decode()
            body = json.dumps({"seen": line, "ison": True}).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            res = await net.http("GET", f"http://127.0.0.1:{port}/relay/0?turn=on")
            self.assertEqual(res["seen"], "GET /relay/0?turn=on HTTP/1.1")
            self.assertTrue(res["ison"])

    async def test_shelly_adapter_end_to_end(self):
        """Run the real Shelly adapter against a fake Gen2 device."""
        state = {"output": False}

        async def handle(reader, writer):
            req = (await reader.readuntil(b"\r\n\r\n")).decode()
            path = req.split(" ")[1]
            if path.startswith("/rpc/Switch.Set"):
                state["output"] = "on=true" in path
                payload = {"was_on": not state["output"]}
            elif path.startswith("/rpc/Switch.GetStatus"):
                payload = {"output": state["output"], "apower": 12.34}
            else:
                payload = {"gen": 2, "app": "PlugUS"}
            body = json.dumps(payload).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
            writer.close()

        from app.adapters.shelly import ShellyAdapter
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            a = ShellyAdapter({}, tempfile.mkdtemp())
            dev = Device(id="s1", adapter="shelly", name="Plug", kind=Kind.PLUG, caps=[Cap.POWER],
                         config={"ip": f"127.0.0.1:{port}", "gen": 2, "channel": 0})
            await a.command(dev, Action.POWER, True)
            st = await a.refresh(dev)
            self.assertEqual(st, {"on": True, "power_w": 12.3})


class ScanFallbackOverRealSockets(unittest.IsolatedAsyncioTestCase):
    """scan_ports and the Samsung fallback against real local servers."""

    async def test_scan_ports_finds_listening_host(self):
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            found = await net.scan_ports(["127.0.0.1"], (port,), timeout=1)
        self.assertEqual(found, {"127.0.0.1": port})
        self.assertEqual(await net.scan_ports(["127.0.0.1"], (1,), timeout=0.5), {})   # nothing on port 1

    async def test_samsung_found_by_scan_when_ssdp_finds_nothing(self):
        from app.adapters import samsung_tv

        async def handle(reader, writer):
            try:
                await reader.readuntil(b"\r\n\r\n")
            except asyncio.IncompleteReadError:   # the port scan connects and hangs up straight away
                writer.close()
                return
            body = json.dumps({"device": {"name": "Living Room TV", "modelName": "QN65", "wifiMac": "aa:bb:cc:00:11:22"}}).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
            writer.close()

        try:
            server = await asyncio.start_server(handle, "127.0.0.1", 8001)   # the port every Tizen TV uses
        except OSError:
            self.skipTest("port 8001 is busy on this machine")
        saved = (samsung_tv.ssdp_search, samsung_tv.local_subnet_hosts)

        async def no_ssdp(*a, **k):
            return []
        samsung_tv.ssdp_search, samsung_tv.local_subnet_hosts = no_ssdp, (lambda: ["127.0.0.1"])
        try:
            async with server:
                found = await samsung_tv.SamsungTVAdapter({}, tempfile.mkdtemp()).discover()
        finally:
            samsung_tv.ssdp_search, samsung_tv.local_subnet_hosts = saved
        self.assertEqual([(f.name, f.config["ip"], f.uid) for f in found],
                         [("Living Room TV", "127.0.0.1", "AA:BB:CC:00:11:22")])


class FakeHA:
    TOKEN = "test-token"

    def __init__(self):
        self.calls = []
        self.states = {
            "light.desk": {"entity_id": "light.desk", "state": "on", "attributes": {
                "friendly_name": "Desk lamp", "supported_color_modes": ["color_temp", "hs"],
                "brightness": 128, "color_mode": "color_temp", "color_temp_kelvin": 3000}},
            "media_player.living_tv": {"entity_id": "media_player.living_tv", "state": "playing", "attributes": {
                "friendly_name": "Living TV", "supported_features": 128 | 256 | 4 | 8 | 1024 | 2048 | 16384 | 1,
                "volume_level": 0.25, "is_volume_muted": False, "source": "HDMI 1", "source_list": ["HDMI 1", "Netflix"]}},
            "sensor.temp": {"entity_id": "sensor.temp", "state": "21", "attributes": {}},
        }

    async def handle(self, reader, writer):
        head = (await reader.readuntil(b"\r\n\r\n")).decode()
        length = int(next((ln.split(":")[1] for ln in head.split("\r\n") if ln.lower().startswith("content-length")), 0))
        body = json.loads(await reader.readexactly(length)) if length else None
        method, path = head.split(" ")[:2]
        authed = f"Authorization: Bearer {self.TOKEN}" in head
        status, payload = 200, None
        if not authed:
            status, payload = 401, {"message": "Invalid authentication"}
        elif path == "/api/states":
            payload = list(self.states.values())
        elif path == "/api/template":
            payload = "light.desk|Office\nmedia_player.living_tv|Living room\n"
        elif path.startswith("/api/services/"):
            self.calls.append((path, body))
            payload = []
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        data = raw.encode()
        writer.write(f"HTTP/1.1 {status} X\r\nContent-Length: {len(data)}\r\n\r\n".encode() + data)
        await writer.drain()
        writer.close()


class HomeAssistantAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from app.adapters.home_assistant import HomeAssistantAdapter
        self.ha = FakeHA()
        self.server = await asyncio.start_server(self.ha.handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.adapter = HomeAssistantAdapter({"url": f"http://127.0.0.1:{port}", "token": FakeHA.TOKEN}, tempfile.mkdtemp())

    async def asyncTearDown(self):
        self.server.close()

    async def test_discover_with_rooms_and_caps(self):
        found = {f.uid: f for f in await self.adapter.discover()}
        self.assertEqual(set(found), {"light.desk", "media_player.living_tv"})   # sensors skipped
        self.assertEqual(found["light.desk"].room, "Office")
        self.assertEqual(found["light.desk"].caps, [Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR, Cap.COLOR_TEMP])
        tv = found["media_player.living_tv"]
        self.assertEqual(tv.kind, Kind.TV)
        for c in (Cap.POWER, Cap.VOLUME, Cap.VOLUME_LEVEL, Cap.MUTE, Cap.INPUTS, Cap.MEDIA):
            self.assertIn(c, tv.caps)
        self.assertNotIn(Cap.REMOTE, tv.caps)

    async def test_refresh_and_commands(self):
        light = Device(id="1", adapter="home_assistant", name="Desk", kind=Kind.LIGHT, config={"entity_id": "light.desk"})
        st = await self.adapter.refresh(light)
        self.assertEqual((st["on"], st["brightness"], st["color_temp"]), (True, 50, 3000))
        await self.adapter.command(light, Action.BRIGHTNESS, 40)
        await self.adapter.command(light, Action.COLOR, {"r": 255, "g": 0, "b": 0})
        tv = Device(id="2", adapter="home_assistant", name="TV", kind=Kind.TV, config={"entity_id": "media_player.living_tv"})
        st = await self.adapter.refresh(tv)
        self.assertEqual((st["on"], st["volume"], st["input"]), (True, 25, "HDMI 1"))
        await self.adapter.command(tv, Action.VOLUME, 30)
        await self.adapter.command(tv, Action.POWER, False)
        self.assertEqual(self.ha.calls, [
            ("/api/services/light/turn_on", {"entity_id": "light.desk", "brightness_pct": 40}),
            ("/api/services/light/turn_on", {"entity_id": "light.desk", "rgb_color": [255, 0, 0]}),
            ("/api/services/media_player/volume_set", {"entity_id": "media_player.living_tv", "volume_level": 0.3}),
            ("/api/services/media_player/turn_off", {"entity_id": "media_player.living_tv"}),
        ])

    async def test_bad_token_message(self):
        self.adapter.account_changed({**self.adapter.account, "token": "wrong"})
        with self.assertRaises(AdapterError) as cm:
            await self.adapter.discover()
        self.assertIn("token", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
