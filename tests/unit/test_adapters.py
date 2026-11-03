"""Unit tests: every adapter's contract and the protocol maths that need no network."""
import tempfile
import unittest

import app.adapters  # noqa: F401  registers every adapter
from app.core.adapter import ADAPTERS, AdapterError, Cap, Device, DeviceAdapter, Field, Kind, missing_requirements
from app.core import net


class AdapterContract(unittest.TestCase):
    def test_expected_adapters_registered(self):
        for aid in ("tuya", "govee", "kasa", "shelly", "wiz", "hue", "samsung_tv", "lg_tv", "demo"):
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
