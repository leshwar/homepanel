"""Integration tests: real adapters talking over real sockets to simulated devices.

Each test starts a tiny local server that behaves like the device or service
(a Shelly plug, Home Assistant) and runs the actual adapter code against it.
"""
import asyncio
import json
import os
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


class FakeSoundbar:
    """A tiny LG sound bar: AES-encrypted JSON over TCP, written separately from the adapter
    so a mistake in the adapter's wire format can't hide behind the same code."""
    KEY = b"T^&*J%^7tr~4^%^&I(o%^!jIJ__+a0 k"
    IV = b"'%^Ur7gy$~t+f)%@"

    def __init__(self):
        self.spk = {"i_vol": 8, "i_vol_min": 0, "i_vol_max": 40, "b_mute": False, "b_powerstatus": True,
                    "i_curr_func": 20, "s_user_name": "Den Soundbar"}
        self.func = {"i_curr_func": 20, "ai_func_list": [15, 1, 0, 6]}
        self.eq = {"i_curr_eq": 19, "ai_eq_list": [19, 0, 7, 6]}
        self.product = {"s_model_name": "SC9S", "s_dev_mac": "aa:bb:cc:dd:ee:01"}
        self.sets = []

    def _cipher(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        return Cipher(algorithms.AES(self.KEY), modes.CBC(self.IV))

    def pack(self, obj):
        raw = json.dumps(obj).encode()
        n = 16 - len(raw) % 16
        e = self._cipher().encryptor()
        body = e.update(raw + bytes([n]) * n) + e.finalize()
        return b"\x10" + len(body).to_bytes(4, "big") + body

    def unpack(self, body):
        d = self._cipher().decryptor()
        raw = d.update(body) + d.finalize()
        return json.loads(raw[:-raw[-1]])

    async def handle(self, reader, writer):
        views = {"SPK_LIST_VIEW_INFO": self.spk, "FUNC_VIEW_INFO": self.func, "EQ_VIEW_INFO": self.eq,
                 "PRODUCT_INFO": self.product}
        try:
            while True:
                head = await reader.readexactly(5)
                req = self.unpack(await reader.readexactly(int.from_bytes(head[1:], "big")))
                view = views.get(req["msg"])
                if view is None:
                    continue
                if req["cmd"] == "set":
                    self.sets.append((req["msg"], req["data"]))
                    data = dict(req["data"])
                    if "b_powerkey" in data:
                        data = {"b_powerstatus": data["b_powerkey"]}
                    view.update(data)
                    if req["msg"] == "FUNC_VIEW_INFO":
                        self.spk["i_curr_func"] = self.func["i_curr_func"]
                    writer.write(self.pack({"cmd": "notiforset", "msg": req["msg"], "data": view, "result": "ok"}))
                else:
                    # like the real thing, sometimes say something unasked for first
                    writer.write(self.pack({"cmd": "notibyget", "msg": "PLAY_INFO", "data": {"i_stream_type": 0}}))
                    writer.write(self.pack({"cmd": "notibyget", "msg": req["msg"], "data": view, "result": "ok"}))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


class LGSoundbarAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from app.adapters import lg_soundbar
        self.mod = lg_soundbar
        self.fake = FakeSoundbar()
        self.server = await asyncio.start_server(self.fake.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.saved = (lg_soundbar.PORT, lg_soundbar.local_subnet_hosts)
        lg_soundbar.PORT, lg_soundbar.local_subnet_hosts = self.port, (lambda: ["127.0.0.1"])
        self.adapter = lg_soundbar.LGSoundbarAdapter({}, tempfile.mkdtemp())

    async def asyncTearDown(self):
        self.mod.PORT, self.mod.local_subnet_hosts = self.saved
        self.server.close()

    async def test_discover_setup_refresh_and_control(self):
        found = await self.adapter.discover()
        self.assertEqual([(f.name, f.uid, f.kind, f.detail) for f in found],
                         [("Den Soundbar", "AA:BB:CC:DD:EE:01", Kind.SPEAKER, "127.0.0.1 · SC9S")])
        f = found[0]
        dev = Device(id="sb", adapter="lg_soundbar", name=f.name, kind=f.kind, caps=f.caps, config=dict(f.config))
        await self.adapter.setup(dev)
        self.assertEqual(dev.meta["model"], "SC9S")
        dev.state = await self.adapter.refresh(dev)
        self.assertEqual(dev.state, {"on": True, "muted": False, "volume": 20, "input": "15", "sound_mode": "19"})
        self.assertIn({"id": "7", "name": "Cinema"}, dev.meta["sound_modes"])

        await self.adapter.command(dev, Action.VOLUME, 50)
        await self.adapter.command(dev, Action.VOLUME_DOWN)
        await self.adapter.command(dev, Action.MUTE, True)
        await self.adapter.command(dev, Action.SET_INPUT, "6")
        await self.adapter.command(dev, Action.SET_SOUND_MODE, "7")
        await self.adapter.command(dev, Action.POWER, False)
        self.assertEqual(self.fake.sets, [
            ("SPK_LIST_VIEW_INFO", {"i_vol": 20}), ("SPK_LIST_VIEW_INFO", {"i_vol": 19}),
            ("SPK_LIST_VIEW_INFO", {"b_mute": True}), ("FUNC_VIEW_INFO", {"i_curr_func": 6}),
            ("EQ_VIEW_INFO", {"i_curr_eq": 7}), ("SPK_LIST_VIEW_INFO", {"b_powerkey": False})])
        st = await self.adapter.refresh(dev)
        self.assertEqual((st["on"], st["volume"], st["muted"], st["input"], st["sound_mode"]),
                         (False, 48, True, "6", "7"))

    async def test_add_by_ip_and_unreachable_message(self):
        f = self.adapter.from_manual({"name": "Bar", "ip": "127.0.0.1"})
        dev = Device(id="m", adapter="lg_soundbar", name="Bar", kind=f.kind, caps=f.caps,
                     config={**f.config, "port": self.port})
        await self.adapter.setup(dev)
        self.assertEqual(dev.config["mac"], "AA:BB:CC:DD:EE:01")
        self.server.close()
        await self.server.wait_closed()
        with self.assertRaises(AdapterError) as cm:
            await self.adapter.setup(dev)
        self.assertIn("same Wi-Fi", str(cm.exception))


class SearchAllOffersNoDuplicateTV(unittest.IsolatedAsyncioTestCase):
    """The real LG adapter and HomeService against a fake webOS TV on 127.0.0.1. A TV saved
    from an SSDP search must stay "added" when a later search only finds it by the port scan
    (the multicast reply was missed), and adding it again must be refused."""
    UUID = "uuid:14704f92-0000-0000-0000-000000000001"

    async def asyncSetUp(self):
        from app.adapters import lg_tv
        from app.core.service import HomeService

        async def handle(reader, writer):
            try:
                await reader.readuntil(b"\r\n\r\n")
            except asyncio.IncompleteReadError:          # the port scan connects and hangs up
                writer.close()
                return
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 11\r\n\r\nHello world")
            await writer.drain()
            writer.close()

        try:
            self.server = await asyncio.start_server(handle, "127.0.0.1", 3000)   # webOS answers on :3000
        except OSError:
            self.skipTest("port 3000 is busy on this machine")
        self.lg_tv, self.ssdp_hits = lg_tv, []

        async def ssdp(*a, **k):
            return self.ssdp_hits
        self.saved = (lg_tv.ssdp_search, lg_tv.local_subnet_hosts)
        lg_tv.ssdp_search, lg_tv.local_subnet_hosts = ssdp, (lambda: ["127.0.0.1"])
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir)
        self.svc.adapters = {"lg_tv": lg_tv.LGTVAdapter({}, self.dir)}
        # saved by an earlier version from an SSDP search: uid is the uuid, MAC not learned yet
        self.svc.store.devices["tv"] = Device(id="tv", adapter="lg_tv", name="Living room TV", kind=Kind.TV,
                                              config={"ip": "127.0.0.1", "mac": "", "_uid": self.UUID})

    async def asyncTearDown(self):
        self.lg_tv.ssdp_search, self.lg_tv.local_subnet_hosts = self.saved
        self.server.close()
        await self.server.wait_closed()

    async def test_tv_is_never_offered_twice(self):
        self.ssdp_hits = [{"ip": "127.0.0.1", "usn": f"{self.UUID}::urn:lge-com:service:webos-second-screen:1"}]
        r = await self.svc.discover_all()
        self.assertEqual([(f["adapter"], f["added"]) for f in r["found"]], [("lg_tv", True)])

        self.ssdp_hits = []                                 # multicast reply missed: found by the port scan
        r = await self.svc.discover_all()
        [tv] = r["found"]
        self.assertIn("network scan", tv["detail"])
        self.assertTrue(tv["added"])
        self.assertTrue(all("config" not in f and "aliases" not in f for f in r["found"]))
        with self.assertRaisesRegex(AdapterError, "Already added as 'Living room TV'"):
            await self.svc.add_device("lg_tv", uid=tv["uid"])
        self.assertEqual(list(self.svc.store.devices), ["tv"])


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


class FakeGoveeCloud:
    """A tiny stand-in for Govee's cloud API (openapi.api.govee.com/router/api/v1), answering with
    the recorded JSON in tests/fixtures/govee and keeping what the panel asked it to do."""
    KEY = "test-govee-key"
    FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures", "govee")

    def __init__(self):
        self.requests = []       # (method, path, body)
        self.status = 200

    def fixture(self, name):
        with open(os.path.join(self.FIX, name), encoding="utf-8") as f:
            return json.load(f)

    async def handle(self, reader, writer):
        head = (await reader.readuntil(b"\r\n\r\n")).decode()
        length = int(next((ln.split(":")[1] for ln in head.split("\r\n") if ln.lower().startswith("content-length")), 0))
        body = json.loads(await reader.readexactly(length)) if length else None
        method, path = head.split(" ")[:2]
        path = path.removeprefix("/router/api/v1")
        self.requests.append((method, path, body))
        status, payload = self.status, None
        if f"Govee-API-Key: {self.KEY}" not in head:
            status, payload = 401, {"code": 401, "message": "Invalid API key"}
        elif status != 200:
            payload = {"code": status, "message": "Too many requests"}
        elif (method, path) == ("GET", "/user/devices"):
            payload = self.fixture("user_devices.json")
        elif (method, path) == ("POST", "/device/scenes"):
            payload = self.fixture("scenes.json")
        elif (method, path) == ("POST", "/device/diy-scenes"):
            payload = self.fixture("diy_scenes.json")
        elif (method, path) == ("POST", "/device/state"):
            payload = self.fixture("state.json")
        elif (method, path) == ("POST", "/device/control"):
            payload = {"requestId": body["requestId"], "msg": "success", "code": 200,
                       "capability": {**body["payload"]["capability"], "state": {"status": "success"}}}
        else:
            status, payload = 404, {"code": 404, "message": "Not found"}
        data = json.dumps(payload).encode()
        writer.write(f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n\r\n".encode()
                     + data)
        await writer.drain()
        writer.close()

    def controls(self):
        return [b["payload"]["capability"] for m, p, b in self.requests if p == "/device/control"]


class GoveeCloudEffectsTests(unittest.IsolatedAsyncioTestCase):
    """The real Govee adapter over HTTP against the fake cloud: find the light, read its scenes,
    play one, music mode, strip parts, a toggle, and plain errors."""

    async def asyncSetUp(self):
        from app.adapters.govee import GoveeAdapter
        self.cloud = FakeGoveeCloud()
        self.server = await asyncio.start_server(self.cloud.handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.adapter = GoveeAdapter({"api_key": FakeGoveeCloud.KEY}, tempfile.mkdtemp())
        self.adapter.cloud_url = f"http://127.0.0.1:{port}/router/api/v1"

    async def asyncTearDown(self):
        self.server.close()

    async def added_light(self) -> Device:
        found = await self.adapter.discover()
        self.assertEqual(len(found), 1)
        f = found[0]
        d = Device(id="gv", adapter="govee", name=f.name, kind=f.kind, caps=list(f.caps), config={**f.config, "_uid": f.uid})
        await self.adapter.setup(d)
        return d

    async def test_scenes_music_segments_and_toggles(self):
        d = await self.added_light()
        self.assertEqual(d.name, "TV backlight")
        for cap in (Cap.EFFECTS, Cap.MUSIC, Cap.SEGMENTS, Cap.TOGGLES):
            self.assertIn(cap, d.caps)
        groups = {e["group"] for e in d.meta["effects"]}
        self.assertEqual(groups, {"Scenes", "DIY"})
        self.assertEqual(d.meta["segments"], 15)
        reads = [(m, p) for m, p, _b in self.cloud.requests]
        self.assertEqual(reads, [("GET", "/user/devices"), ("GET", "/user/devices"), ("POST", "/device/scenes"),
                                 ("POST", "/device/diy-scenes"), ("POST", "/device/state")])

        sunset = next(e["id"] for e in d.meta["effects"] if e["name"] == "Sunset")
        movie = next(e["id"] for e in d.meta["effects"] if e["name"] == "Movie night")
        await self.adapter.command(d, Action.SET_EFFECT, sunset)
        await self.adapter.command(d, Action.SET_EFFECT, movie)
        await self.adapter.command(d, Action.SET_MUSIC, {"mode": "2", "sensitivity": 60})
        await self.adapter.command(d, Action.SET_SEGMENTS, {"segments": [0, 1], "color": {"r": 0, "g": 0, "b": 255},
                                                            "brightness": 30})
        out = await self.adapter.command(d, Action.SET_TOGGLE, {"id": "gradient", "on": False})
        self.assertEqual(out["toggles"], {"gradient": False})
        self.assertEqual(self.cloud.controls(), [
            {"type": "devices.capabilities.dynamic_scene", "instance": "lightScene", "value": {"id": 129, "paramId": 111}},
            {"type": "devices.capabilities.dynamic_scene", "instance": "diyScene", "value": 8216931},
            {"type": "devices.capabilities.music_setting", "instance": "musicMode",
             "value": {"musicMode": 2, "sensitivity": 60, "autoColor": 1}},
            {"type": "devices.capabilities.segment_color_setting", "instance": "segmentedBrightness",
             "value": {"segment": [0, 1], "brightness": 30}},
            {"type": "devices.capabilities.segment_color_setting", "instance": "segmentedColorRgb",
             "value": {"segment": [0, 1], "rgb": 255}},
            {"type": "devices.capabilities.toggle", "instance": "gradientToggle", "value": 0},
        ])
        for _m, p, body in self.cloud.requests:
            if p == "/device/control":
                self.assertEqual((body["payload"]["sku"], body["payload"]["device"]), ("H605C", "AA:BB:CC:DD:EE:FF:00:11"))

    async def test_wrong_key_and_too_many_requests_are_explained(self):
        d = await self.added_light()
        self.adapter.account_changed({"api_key": "wrong"})
        with self.assertRaisesRegex(AdapterError, "rejected the API key"):
            await self.adapter.command(d, Action.UPDATE_EFFECTS)
        self.adapter.account_changed({"api_key": FakeGoveeCloud.KEY})
        self.cloud.status = 429
        with self.assertRaisesRegex(AdapterError, "Wait a minute"):
            await self.adapter.command(d, Action.SET_EFFECT, d.meta["effects"][0]["id"])


if __name__ == "__main__":
    unittest.main()


class EcovacsRefusalThroughTheService(unittest.IsolatedAsyncioTestCase):
    """The whole command path (service pipeline → Ecovacs adapter → fake library): a command
    the vacuum refuses must come back as an error, and the panel must keep showing the real
    state instead of "Cleaning". A model that wants clean_V2 still starts."""

    async def asyncSetUp(self):
        import sys
        from tests.unit import test_ecovacs as fake
        from app.core.service import HomeService
        self.fake, self.saved = fake, fake.install_fake_library()
        fake.cloud.reset()
        self.sys = sys
        from app.adapters.ecovacs import EcovacsAdapter
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir)
        self.svc.store.accounts["ecovacs"] = {"email": "me@example.com", "password": "pw", "country": "US"}
        self.svc.adapters = {"ecovacs": EcovacsAdapter(self.svc.store.accounts["ecovacs"], self.dir)}
        self.svc.store.devices["v"] = Device(id="v", adapter="ecovacs", name="Hall bot", kind=Kind.VACUUM,
                                             caps=["clean", "dock"], config={"did": "bot1", "_uid": "bot1"})
        await self.svc.refresh("v")

    async def asyncTearDown(self):
        await self.svc.adapters["ecovacs"].stop()
        for name, mod in self.saved.items():
            if mod is None:
                self.sys.modules.pop(name, None)
            else:
                self.sys.modules[name] = mod

    async def test_refused_then_v2(self):
        cloud = self.fake.cloud
        self.assertEqual(self.svc.store.devices["v"].state["activity"], "docked")
        cloud.reply = lambda cmd: {"ret": "ok", "resp": {"body": {"code": 30007, "msg": "bin full"}}}
        with self.assertRaisesRegex(AdapterError, "bin full"):
            await self.svc.command("v", "clean", "start")
        self.assertEqual(self.svc.store.devices["v"].state["activity"], "docked")    # not "cleaning"

        # like deebot-client with the T90: the classic command is refused and comes back empty
        cloud.reply = lambda cmd: {} if cmd.name == "clean" else {"ret": "ok", "resp": {"body": {"code": 0}}}
        d = await self.svc.command("v", "clean", "start")
        self.assertEqual(d["state"]["activity"], "cleaning")
        self.assertTrue(self.svc.store.devices["v"].config["clean_v2"])              # saved with the device
