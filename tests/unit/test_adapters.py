"""Unit tests: every adapter's contract and the protocol maths that need no network."""
import tempfile
import unittest

import app.adapters  # noqa: F401  registers every adapter
from app.core.adapter import (ADAPTERS, Action, AdapterError, Cap, Device, DeviceAdapter, Field, Kind,
                              missing_requirements)
from app.core import net


class AdapterContract(unittest.TestCase):
    def test_expected_adapters_registered(self):
        for aid in ("tuya", "govee", "kasa", "shelly", "wiz", "hue", "samsung_tv", "lg_tv", "lg_soundbar", "demo"):
            self.assertIn(aid, ADAPTERS)

    def test_metadata_is_complete(self):
        for aid, cls in ADAPTERS.items():
            with self.subTest(adapter=aid):
                self.assertTrue(issubclass(cls, DeviceAdapter))
                self.assertTrue(cls.name)
                self.assertTrue(cls.kinds)
                for k in cls.kinds:
                    self.assertIn(k, Kind.ALL)
                for f in [*cls.account_fields, *cls.manual_fields]:
                    self.assertIsInstance(f, Field)
                    self.assertIn(f.type, ("text", "password", "number", "select"))
                    if f.type == "select":
                        self.assertTrue(f.options)
                self.assertGreater(cls.poll_interval, 0)

    def test_manual_add_validates(self):
        for aid, cls in ADAPTERS.items():
            if not cls.manual_fields or missing_requirements(cls):
                continue
            with self.subTest(adapter=aid):
                inst = cls({}, tempfile.mkdtemp())
                with self.assertRaises(AdapterError):
                    inst.from_manual({})

    def test_tv_adapters_map_every_key(self):
        from app.adapters import samsung_tv, lg_tv
        from app.core.adapter import Key
        for mapping in (samsung_tv.KEYS, lg_tv.BUTTONS):
            self.assertEqual(set(mapping), set(Key.ALL))


class TuyaMath(unittest.TestCase):
    def test_colour_encoding_round_trip(self):
        from app.adapters.tuya import _hsv_hex, TuyaAdapter
        hexval = _hsv_hex({"r": 255, "g": 0, "b": 0}, 50)
        self.assertEqual(hexval, "0000" + "03e8" + "01f4")   # hue 0, sat 1000, value 500
        dev = Device(id="x", adapter="tuya", name="Bulb", kind=Kind.LIGHT)
        st = TuyaAdapter({}, tempfile.mkdtemp())._light_state(dev, {"20": True, "21": "colour", "22": 1000, "24": hexval})
        self.assertEqual(st["color"], {"r": 255, "g": 0, "b": 0})
        self.assertEqual(st["brightness"], 50)
        self.assertEqual(st["color_mode"], "color")

    def test_white_mode(self):
        from app.adapters.tuya import TuyaAdapter
        dev = Device(id="x", adapter="tuya", name="Bulb", kind=Kind.LIGHT)
        st = TuyaAdapter({}, tempfile.mkdtemp())._light_state(dev, {"20": True, "21": "white", "22": 505, "23": 0})
        self.assertEqual(st["brightness"], 50)
        self.assertEqual(st["color_temp"], 2700)


class GoveeParsing(unittest.TestCase):
    def test_cloud_caps(self):
        from app.adapters.govee import _cloud_caps
        caps, rng = _cloud_caps([
            {"type": "devices.capabilities.on_off", "instance": "powerSwitch"},
            {"type": "devices.capabilities.color_setting", "instance": "colorTemperatureK",
             "parameters": {"range": {"min": 2000, "max": 9000}}}])
        self.assertEqual(caps, [Cap.POWER, Cap.COLOR_TEMP])
        self.assertEqual(rng, [2000, 9000])

    def test_plug_has_power_only(self):
        from app.adapters.govee import _cloud_caps
        caps, _ = _cloud_caps([{"type": "devices.capabilities.on_off", "instance": "powerSwitch"}])
        self.assertEqual(caps, [Cap.POWER])


# What a real LG S95TR sent back (read-only "get" requests), trimmed.
SOUNDBAR_REPLIES = {
    "SPK_LIST_VIEW_INFO": {"i_vol": 6, "i_vol_min": 0, "i_vol_max": 100, "i_curr_func": 20, "b_mute": False,
                           "b_powerstatus": True, "s_user_name": "Living Room Soundbar"},
    "FUNC_VIEW_INFO": {"i_curr_func": 20, "ai_func_list": [15, 1, 0, 6, 19]},
    "EQ_VIEW_INFO": {"i_curr_eq": 19, "ai_eq_list": [19, 0, 7, 26]},
    "PRODUCT_INFO": {"s_model_name": "S95TR", "s_dev_mac": "28:87:61:91:35:3C"},
}


class FakeSoundbarLink:
    """Stands in for the network connection, so the adapter's logic runs without sockets."""

    def __init__(self, replies):
        self.replies, self.sets, self.closed = replies, [], False

    async def ask(self, *names, timeout=3.0):
        return {n: dict(self.replies[n]) for n in names if n in self.replies}

    async def set(self, msg, data):
        self.sets.append((msg, data))

    async def close(self):
        self.closed = True


class LGSoundbar(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from app.adapters import lg_soundbar
        self.mod = lg_soundbar
        self.link = FakeSoundbarLink({k: dict(v) for k, v in SOUNDBAR_REPLIES.items()})
        self.saved_open = lg_soundbar.Link.open

        async def fake_open(ip, port=lg_soundbar.PORT, timeout=4.0):
            return self.link
        lg_soundbar.Link.open = staticmethod(fake_open)
        self.adapter = lg_soundbar.LGSoundbarAdapter({}, tempfile.mkdtemp())
        self.dev = Device(id="sb", adapter="lg_soundbar", name="Sound bar", kind=Kind.SPEAKER,
                          caps=list(lg_soundbar.CAPS), config={"ip": "192.0.2.10"})

    def tearDown(self):
        self.mod.Link.open = self.saved_open

    def test_wire_format_round_trip(self):
        msg = {"cmd": "get", "msg": "SPK_LIST_VIEW_INFO"}
        packet = self.mod.encode(msg)
        self.assertEqual(packet[0], 0x10)
        size = int.from_bytes(packet[1:5], "big")
        self.assertEqual((size % 16, size + 5), (0, len(packet)))
        self.assertEqual(self.mod.decode(packet[5:]), msg)
        big = {"cmd": "set", "msg": "x", "data": {"s": "a" * 400}}   # longer than 255 bytes
        self.assertEqual(self.mod.decode(self.mod.encode(big)[5:]), big)

    def test_helpers(self):
        self.assertEqual(self.mod.shown_input(20, [15, 1, 0]), 15)    # eARC shows as the ARC input
        self.assertEqual(self.mod.shown_input(6, [15, 1]), 6)          # not offered, no twin: keep it
        self.assertEqual(self.mod.to_percent(20, 0, 40), 50)
        self.assertEqual(self.mod.from_percent(50, 0, 40), 20)
        self.assertEqual(self.mod.sound_mode_name(26), "Sound mode 26")
        self.assertEqual(self.mod.input_name(20), "HDMI eARC")

    async def test_setup_and_refresh(self):
        await self.adapter.setup(self.dev)
        self.assertEqual(self.dev.config["mac"], "28:87:61:91:35:3C")
        self.assertEqual(self.dev.meta["model"], "S95TR")
        st = await self.adapter.refresh(self.dev)
        self.assertEqual(st, {"on": True, "muted": False, "volume": 6, "input": "15", "sound_mode": "19"})
        self.assertEqual([i["name"] for i in self.dev.meta["inputs"]],
                         ["Optical / HDMI ARC", "Bluetooth", "Wi-Fi", "HDMI", "USB 2"])
        self.assertEqual(self.dev.meta["sound_modes"][0], {"id": "19", "name": "AI Sound Pro"})
        self.assertTrue(self.link.closed)

    async def test_standby_reads_as_off_and_blocks_commands(self):
        self.link.replies["SPK_LIST_VIEW_INFO"]["b_powerstatus"] = False
        self.dev.state = await self.adapter.refresh(self.dev)
        self.assertFalse(self.dev.state["on"])
        with self.assertRaises(AdapterError):
            await self.adapter.command(self.dev, Action.VOLUME_UP)
        self.assertEqual(await self.adapter.command(self.dev, Action.POWER, True), {"on": True})
        self.assertEqual(self.link.sets, [("SPK_LIST_VIEW_INFO", {"b_powerkey": True})])

    async def test_commands(self):
        self.link.replies["SPK_LIST_VIEW_INFO"].update(i_vol=10, i_vol_max=40)
        self.dev.state = await self.adapter.refresh(self.dev)
        self.assertEqual(self.dev.state["volume"], 25)
        self.assertEqual(await self.adapter.command(self.dev, Action.VOLUME_UP), {"volume": 28})
        self.assertEqual(await self.adapter.command(self.dev, Action.VOLUME, 50), {"volume": 50})
        await self.adapter.command(self.dev, Action.MUTE, True)
        await self.adapter.command(self.dev, Action.SET_INPUT, "1")
        await self.adapter.command(self.dev, Action.SET_SOUND_MODE, "7")
        self.assertEqual(self.link.sets, [
            ("SPK_LIST_VIEW_INFO", {"i_vol": 11}),      # one step up from what the sound bar reported
            ("SPK_LIST_VIEW_INFO", {"i_vol": 20}),      # 50 % of 0-40
            ("SPK_LIST_VIEW_INFO", {"b_mute": True}),
            ("FUNC_VIEW_INFO", {"i_curr_func": 1}),
            ("EQ_VIEW_INFO", {"i_curr_eq": 7}),
        ])
        with self.assertRaises(AdapterError):
            await self.adapter.command(self.dev, Action.SET_INPUT, "3")   # Aux: this model has none

    async def test_unreachable_is_a_connection_error(self):
        async def refuse(ip, port=self.mod.PORT, timeout=4.0):
            raise OSError("refused")
        self.mod.Link.open = staticmethod(refuse)
        with self.assertRaises(ConnectionError) as cm:
            await self.adapter.refresh(self.dev)
        self.assertIn("same Wi-Fi", str(cm.exception))


class NetHelpers(unittest.TestCase):
    def test_parse_color(self):
        self.assertEqual(net.parse_color("#0080ff"), {"r": 0, "g": 128, "b": 255})
        self.assertEqual(net.parse_color({"r": 300, "g": -1, "b": 5}), {"r": 255, "g": 0, "b": 5})
        with self.assertRaises(ValueError):
            net.parse_color("blue")

    def test_xy_round_trip(self):
        for c in ({"r": 255, "g": 0, "b": 0}, {"r": 0, "g": 0, "b": 255}):
            back = net.xy_to_rgb(*net.rgb_to_xy(c))
            self.assertEqual(max(back, key=back.get), max(c, key=c.get))

    def test_dechunk(self):
        self.assertEqual(net._dechunk(b"4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n"), b"Wikipedia")


if __name__ == "__main__":
    unittest.main()
