"""The Home page layout: the default, checking what the UI saves, and settings."""
import shutil
import tempfile
import unittest
from types import SimpleNamespace as Dev

from app.core.adapter import AdapterError
from app.core.layout import SIZES, WIDGET_TYPES, LayoutError, clean_layout, default_layout
from app.core.service import BACKGROUNDS, HomeService


class DefaultLayoutTests(unittest.TestCase):
    def test_default_has_clock_india_and_us_clocks_weather_and_device_shortcuts(self):
        devices = [Dev(id="p1", kind="plug"), Dev(id="l1", kind="light"), Dev(id="t1", kind="tv"),
                   Dev(id="l2", kind="light"), Dev(id="l3", kind="light"), Dev(id="l4", kind="light")]
        lay = default_layout(devices)
        types = [w["type"] for w in lay["widgets"]]
        self.assertEqual(types[:6], ["clock", "weather", "zone", "zone", "scenes", "rooms"])
        zones = [w["options"] for w in lay["widgets"] if w["type"] == "zone"]
        self.assertEqual(zones, [{"tz": "Asia/Kolkata", "label": "India"}, {"tz": None, "label": "US"}])
        shortcuts = [(w["options"]["device_id"], w["size"]) for w in lay["widgets"] if w["type"] == "device"]
        self.assertEqual(shortcuts, [("t1", "2x1"), ("l1", "1x1"), ("l2", "1x1"), ("l3", "1x1")])   # TVs first, max 4, no plugs
        self.assertEqual(clean_layout(lay), lay)          # the default passes its own checks

    def test_every_type_and_size_is_known(self):
        lay = default_layout()
        self.assertTrue(all(w["type"] in WIDGET_TYPES and w["size"] in SIZES for w in lay["widgets"]))


class CleanLayoutTests(unittest.TestCase):
    def ok(self, widgets):
        return clean_layout({"widgets": widgets})["widgets"]

    def test_keeps_order_size_hidden_and_options(self):
        out = self.ok([
            {"id": "z", "type": "zone", "size": "2x1", "options": {"tz": "America/Chicago", "label": "  US  "}},
            {"id": "c", "type": "clock", "size": "2x2", "hidden": 1, "options": {"junk": True}},
            {"id": "d", "type": "device", "options": {"device_id": "lr-tv"}},
        ])
        self.assertEqual(out, [
            {"id": "z", "type": "zone", "size": "2x1", "hidden": False, "options": {"tz": "America/Chicago", "label": "US"}},
            {"id": "c", "type": "clock", "size": "2x2", "hidden": True, "options": {}},
            {"id": "d", "type": "device", "size": "1x1", "hidden": False, "options": {"device_id": "lr-tv"}},
        ])

    def test_rejects_bad_layouts_with_plain_messages(self):
        bad = [
            ("nope", "list of widgets"),
            ({"widgets": [{"id": "a", "type": "radio"}]}, "Unknown widget type"),
            ({"widgets": [{"id": "a", "type": "clock", "size": "3x3"}]}, "Widget size"),
            ({"widgets": [{"id": "a", "type": "clock"}, {"id": "a", "type": "weather"}]}, "its own short id"),
            ({"widgets": [{"id": "a", "type": "zone", "options": {"tz": "../../etc/passwd"}}]}, "time zone"),
            ({"widgets": [{"id": "a", "type": "device", "options": {}}]}, "needs the device"),
            ({"widgets": [{"id": f"w{i}", "type": "clock"} for i in range(41)]}, "up to 40"),
        ]
        for value, msg in bad:
            with self.subTest(msg=msg), self.assertRaises(LayoutError) as cm:
                clean_layout(value)
            self.assertIn(msg, str(cm.exception))


class LayoutSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_default_until_saved_then_the_saved_layout_for_every_screen(self):
        snap = self.svc.snapshot()["settings"]
        self.assertEqual(snap["background"], "sky")
        self.assertIn("sky", BACKGROUNDS)
        ids = [w["id"] for w in snap["home_layout"]["widgets"]]
        self.assertIn("dev-lr-tv", ids)                    # built from the demo devices
        mine = {"widgets": [{"id": "weather", "type": "weather", "size": "2x2"},
                            {"id": "clock", "type": "clock", "size": "1x1", "hidden": True}]}
        saved = self.svc.update_settings({"home_layout": mine})["home_layout"]
        self.assertEqual([(w["id"], w["size"], w["hidden"]) for w in saved["widgets"]],
                         [("weather", "2x2", False), ("clock", "1x1", True)])
        again = HomeService(self.dir, demo=True)          # survives a restart
        self.assertEqual(again.snapshot()["settings"]["home_layout"], saved)
        self.svc.update_settings({"home_layout": None})   # back to the default
        self.assertEqual(self.svc.snapshot()["settings"]["home_layout"]["widgets"][0]["id"], "clock")

    async def test_bad_layout_is_refused_and_nothing_changes(self):
        before = self.svc.snapshot()["settings"]["home_layout"]
        with self.assertRaises(AdapterError):
            self.svc.update_settings({"home_layout": {"widgets": [{"id": "x", "type": "rocket"}]}})
        self.assertEqual(self.svc.snapshot()["settings"]["home_layout"], before)


if __name__ == "__main__":
    unittest.main()
