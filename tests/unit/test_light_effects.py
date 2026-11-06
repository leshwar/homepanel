"""Light effects: scenes, DIY scenes, snapshots, music mode, strip segments and toggles.

The Govee parts read recorded cloud answers (tests/fixtures/govee) and swap the HTTP call for a
fake, so nothing touches the network. The service parts use the demo light strip, so they only
see the brand-neutral vocabulary (Cap.EFFECTS, Action.SET_EFFECT …)."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from app.adapters import govee
from app.adapters.govee import (GoveeAdapter, _Budget, effect_capability, music_capability, parse_effect_options,
                                parse_extras, segment_capabilities)
from app.core.adapter import Action, AdapterError, Cap, Device, Effect, Kind
from app.core.service import HomeService
from app.core.voice import RulesParser

FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures", "govee")
DEV_ID = "AA:BB:CC:DD:EE:FF:00:11"


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


class FakeCloud:
    """Stands in for app.core.net.http inside the Govee adapter: answers from the recorded JSON."""

    def __init__(self):
        self.calls = []

    async def __call__(self, method, url, json_body=None, headers=None, timeout=5.0, **kw):
        path = url.split("/router/api/v1", 1)[1]
        self.calls.append((method, path, json_body, headers))
        return {"/user/devices": lambda: fixture("user_devices.json"),
                "/device/scenes": lambda: fixture("scenes.json"),
                "/device/diy-scenes": lambda: fixture("diy_scenes.json"),
                "/device/state": lambda: fixture("state.json"),
                "/device/control": lambda: {"code": 200, "msg": "success"}}[path]()

    def paths(self):
        return [p for _m, p, _b, _h in self.calls]

    def controls(self):
        return [b["payload"]["capability"] for _m, p, b, _h in self.calls if p == "/device/control"]


def backlight(**config):
    return Device(id="gv1", adapter="govee", name="TV backlight", kind=Kind.LIGHT,
                  caps=[Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR, Cap.COLOR_TEMP],
                  config={"mode": "cloud", "device": DEV_ID, "sku": "H605C", "_uid": DEV_ID, **config})


class ParsingRecordedCloudAnswers(unittest.TestCase):
    def test_capabilities_of_an_rgbic_backlight(self):
        caps = fixture("user_devices.json")["data"][0]["capabilities"]
        x = parse_extras(caps)
        self.assertEqual(x["scene_kinds"], ["lightScene", "diyScene", "snapshot"])
        self.assertEqual([m["name"] for m in x["music_modes"]], ["Energic", "Rhythm", "Spectrum", "Rolling"])
        self.assertEqual(x["music_modes"][0]["id"], "1")
        self.assertIn("autoColor", x["music_fields"])
        self.assertEqual(x["segments"], 15)                       # elementRange 0..14
        self.assertEqual(x["toggles"], [{"id": Effect.GRADIENT, "name": "Gradient"},
                                        {"id": Effect.SYNC, "name": "Screen sync"}])
        self.assertEqual(x["snapshots"], [])                      # none saved in the app yet

    def test_scene_lists(self):
        scenes = parse_effect_options(fixture("scenes.json"), "lightScene")
        self.assertEqual(len(scenes), 12)
        names = [s["name"] for s in scenes]
        self.assertIn("Green Reign", names)                       # non-breaking spaces cleaned up
        self.assertTrue(all(s["group"] == Effect.SCENES for s in scenes))
        sunny = [s["id"] for s in scenes if s["name"].startswith("Sunny")]
        self.assertEqual(len(set(sunny)), 2)                      # same scene id, different paramId: both kept
        diy = parse_effect_options(fixture("diy_scenes.json"), "diyScene")
        self.assertEqual(diy, [{"id": "diy:8216931", "name": "Movie night", "group": Effect.DIY},
                               {"id": "diy:8216930", "name": "Game day", "group": Effect.DIY}])
        self.assertEqual(parse_effect_options({}, "lightScene"), [])

    def test_snapshot_options_come_from_the_device_list(self):
        cap = {"type": "devices.capabilities.dynamic_scene", "instance": "snapshot",
               "parameters": {"dataType": "ENUM", "options": [{"name": "Reading", "value": 4417},
                                                              {"name": "Bad", "value": "x"}]}}
        self.assertEqual(parse_extras([cap])["snapshots"], [{"id": "snap:4417", "name": "Reading", "group": "Snapshots"}])


class ControlPayloads(unittest.TestCase):
    def test_effects(self):
        self.assertEqual(effect_capability("scene:3853:4280"),
                         ("devices.capabilities.dynamic_scene", "lightScene", {"id": 3853, "paramId": 4280}))
        self.assertEqual(effect_capability("diy:8216931"), ("devices.capabilities.dynamic_scene", "diyScene", 8216931))
        self.assertEqual(effect_capability("snap:4417"), ("devices.capabilities.dynamic_scene", "snapshot", 4417))
        for bad in ("scene:1", "diy:x", "nope:1", "diy:1:2"):
            with self.assertRaisesRegex(AdapterError, "Update list"):
                effect_capability(bad)

    def test_music_and_segments(self):
        self.assertEqual(music_capability({"mode": "2", "sensitivity": 70}, ["musicMode", "sensitivity", "autoColor"]),
                         ("devices.capabilities.music_setting", "musicMode",
                          {"musicMode": 2, "sensitivity": 70, "autoColor": 1}))
        self.assertEqual(music_capability({"mode": "1", "sensitivity": 0}, ["musicMode", "sensitivity"])[2],
                         {"musicMode": 1, "sensitivity": 0})
        caps = segment_capabilities({"segments": [0, 3], "color": {"r": 0, "g": 0, "b": 255}, "brightness": 40})
        self.assertEqual(caps, [
            ("devices.capabilities.segment_color_setting", "segmentedBrightness", {"segment": [0, 3], "brightness": 40}),
            ("devices.capabilities.segment_color_setting", "segmentedColorRgb", {"segment": [0, 3], "rgb": 255})])


class GoveeAdapterEffects(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cloud = FakeCloud()
        patcher = mock.patch.object(govee, "http", self.cloud)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.a = GoveeAdapter({"api_key": "k-123"}, tempfile.mkdtemp())

    async def test_lists_are_read_once_then_cached(self):
        d = backlight()
        state = await self.a.refresh(d)
        self.assertEqual(self.cloud.paths(), ["/user/devices", "/device/scenes", "/device/diy-scenes", "/device/state"])
        self.assertTrue({Cap.EFFECTS, Cap.MUSIC, Cap.SEGMENTS, Cap.TOGGLES} <= set(d.caps))
        self.assertEqual(len(d.meta["effects"]), 14)                 # 12 scenes + 2 DIY
        self.assertEqual(d.meta["segments"], 15)
        self.assertTrue(d.config["_effects_at"])
        self.assertEqual(state["on"], False)
        self.assertEqual(self.cloud.calls[0][3], {"Govee-API-Key": "k-123"})
        # The next refreshes never read the scene lists again (and the state poll is throttled)
        d.state = {"online": True, **state}
        self.a._last_cloud_poll.clear()
        await self.a.refresh(d)
        self.assertEqual(self.cloud.paths()[4:], ["/device/state"])
        # … until the person asks for it
        await self.a.command(d, Action.UPDATE_EFFECTS)
        self.assertEqual(self.cloud.paths()[5:], ["/user/devices", "/device/scenes", "/device/diy-scenes"])

    async def test_a_failed_read_waits_before_trying_again(self):
        d = backlight()
        with mock.patch.object(self.a, "load_effects", side_effect=OSError("no internet")) as load:
            await self.a.refresh(d)
            await self.a.refresh(d)
            self.assertEqual(load.call_count, 1)
            self.a._effects_tried[d.id] -= govee.RETRY_EFFECTS_AFTER + 1
            await self.a.refresh(d)
            self.assertEqual(load.call_count, 2)
        self.assertNotIn(Cap.EFFECTS, d.caps)

    async def test_without_a_key_a_lan_light_says_how_to_get_scenes(self):
        a = GoveeAdapter({}, tempfile.mkdtemp())
        d = Device(id="l1", adapter="govee", name="Strip", kind=Kind.LIGHT, caps=[Cap.POWER],
                   config={"mode": "lan", "ip": "10.0.0.5", "sku": "H6199", "_uid": DEV_ID})
        a._listener = mock.Mock()
        with mock.patch.object(a, "_lan_status", return_value={"onOff": 1, "brightness": 30}):
            await a.refresh(d)
        self.assertIn("API key", d.meta["hint"])
        self.assertEqual(self.cloud.calls, [])
        with self.assertRaisesRegex(AdapterError, "Add your Govee API key"):
            await a.command(d, Action.UPDATE_EFFECTS)
        # Added by IP alone: there's no Govee ID to ask the cloud about
        d.config["_uid"] = "lan-10.0.0.5"
        a.account_changed({"api_key": "k"})
        with self.assertRaisesRegex(AdapterError, "Govee ID"):
            await a.command(d, Action.SET_EFFECT, "scene:1:2")

    async def test_commands_send_the_documented_payloads_and_remember_the_effect(self):
        d = backlight()
        await self.a.refresh(d)
        sunset = next(e["id"] for e in d.meta["effects"] if e["name"] == "Sunset")
        out = await self.a.command(d, Action.SET_EFFECT, sunset)
        self.assertEqual(self.cloud.controls()[-1], {"type": "devices.capabilities.dynamic_scene",
                                                     "instance": "lightScene", "value": {"id": 129, "paramId": 111}})
        self.assertEqual((out["effect"], out["color_mode"], out["on"]), (sunset, "effect", True))
        body = self.cloud.calls[-1][2]
        self.assertEqual((body["payload"]["sku"], body["payload"]["device"]), ("H605C", DEV_ID))
        self.assertTrue(body["requestId"])

        # Govee doesn't report the running scene; a refresh keeps what the panel set
        self.a._last_cloud_poll.clear()
        d.state = {"online": True}
        st = await self.a.refresh(d)
        self.assertEqual((st["effect"], st["color_mode"]), (sunset, "effect"))

        out = await self.a.command(d, Action.SET_MUSIC, {"mode": "3", "sensitivity": 80})
        self.assertEqual(self.cloud.controls()[-1]["value"], {"musicMode": 3, "sensitivity": 80, "autoColor": 1})
        self.assertEqual((out["color_mode"], out["effect"]), ("music", None))

        out = await self.a.command(d, Action.SET_SEGMENTS, {"segments": [0, 14], "color": {"r": 255, "g": 0, "b": 0}})
        self.assertEqual(self.cloud.controls()[-1], {"type": "devices.capabilities.segment_color_setting",
                                                     "instance": "segmentedColorRgb",
                                                     "value": {"segment": [0, 14], "rgb": 0xFF0000}})
        self.assertEqual(out["segments"][0], "#ff0000")
        self.assertEqual(out["segments"][14], "#ff0000")
        self.assertIsNone(out["segments"][1])

        out = await self.a.command(d, Action.SET_TOGGLE, {"id": Effect.SYNC, "on": True})
        self.assertEqual(self.cloud.controls()[-1], {"type": "devices.capabilities.toggle",
                                                     "instance": "dreamViewToggle", "value": 1})
        self.assertEqual(out["toggles"], {Effect.SYNC: True})

        # A plain color ends the effect
        out = await self.a.command(d, Action.COLOR, {"r": 0, "g": 255, "b": 0})
        self.assertEqual((out["color_mode"], out["effect"], out["segments"], out["music"]), ("color", None, None, None))
        self.a._last_cloud_poll.clear()
        st = await self.a.refresh(d)
        self.assertEqual(st["color_mode"], "color")


class CloudBudget(unittest.IsolatedAsyncioTestCase):
    def make(self):
        clock = {"t": 100.0, "day": "2026-11-04"}
        slept = []

        async def sleep(s):
            slept.append(s)

        return _Budget(clock=lambda: clock["t"], sleep=sleep, today=lambda: clock["day"]), clock, slept

    async def test_bursts_then_waits_then_refuses(self):
        b, clock, slept = self.make()
        rate, burst = govee.CONTROL_RATE
        for _ in range(burst):
            await b.take("control:x", rate, burst)
        self.assertEqual(slept, [])
        await b.take("control:x", rate, burst)                    # next one waits for a token
        self.assertAlmostEqual(slept[-1], 1 / rate, places=3)
        with self.assertRaisesRegex(AdapterError, "Wait a few seconds"):
            for _ in range(20):
                await b.take("control:x", rate, burst)
        await b.take("control:other", rate, burst)                # other lights have their own bucket
        clock["t"] += 60
        await b.take("control:x", rate, burst)                    # refilled after a minute

    async def test_daily_allowance(self):
        b, clock, _ = self.make()
        b.day, b.used = "2026-11-04", govee.DAILY_LIMIT
        with self.assertRaisesRegex(AdapterError, "today's Govee allowance"):
            await b.take("read:x", 100, 100)
        clock["day"] = "2026-11-05"
        await b.take("read:x", 100, 100)
        self.assertEqual(b.used, 1)

    async def test_govee_429_is_explained(self):
        from app.core.net import HttpError

        async def too_many(*a, **k):
            raise HttpError(429, "Too Many Requests")

        a = GoveeAdapter({"api_key": "k"}, tempfile.mkdtemp())
        with mock.patch.object(govee, "http", too_many), self.assertRaisesRegex(AdapterError, "Wait a minute"):
            await a.command(backlight(), Action.SET_EFFECT, "diy:1")


class ServiceValidation(unittest.IsolatedAsyncioTestCase):
    """The demo strip through the real service pipeline (validate → normalize → adapter)."""

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.s = HomeService(self.dir, demo=True)
        await self.s.start()

    async def asyncTearDown(self):
        await self.s.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_effect_music_segments_toggles(self):
        d = await self.s.command("lr-strip", Action.SET_EFFECT, "scene-sunset")
        self.assertEqual((d["state"]["effect"], d["state"]["color_mode"]), ("scene-sunset", "effect"))
        with self.assertRaisesRegex(AdapterError, "doesn't have the option"):
            await self.s.command("lr-strip", Action.SET_EFFECT, "scene-nope")
        with self.assertRaisesRegex(AdapterError, "Floor lamp can't play scenes"):
            await self.s.command("lr-lamp", Action.SET_EFFECT, "scene-sunset")

        d = await self.s.command("lr-strip", Action.SET_MUSIC, {"mode": "rhythm", "sensitivity": 140})
        self.assertEqual(d["state"]["music"], {"mode": "rhythm", "sensitivity": 100})
        d = await self.s.command("lr-strip", Action.SET_MUSIC, "spectrum")          # a bare mode id is fine too
        self.assertEqual(d["state"]["music"], {"mode": "spectrum", "sensitivity": 50})
        with self.assertRaisesRegex(AdapterError, "music mode 'disco'"):
            await self.s.command("lr-strip", Action.SET_MUSIC, {"mode": "disco"})

        d = await self.s.command("lr-strip", Action.SET_SEGMENTS, {"segments": [2, 0, 2], "color": "#0000ff"})
        self.assertEqual(d["state"]["segments"][:3], ["#0000ff", None, "#0000ff"])
        for bad, msg in (({"segments": [10], "color": "#fff"}, "numbered 0 to 9"), ({"segments": []}, "at least one"),
                         ({"segments": [1]}, "Choose a color"), ({"segments": ["x"], "color": "#fff"}, "numbered from 0")):
            with self.assertRaisesRegex(AdapterError, msg):
                await self.s.command("lr-strip", Action.SET_SEGMENTS, bad)

        d = await self.s.command("lr-strip", Action.SET_TOGGLE, {"id": "gradient", "on": 1})
        self.assertEqual(d["state"]["toggles"], {"gradient": True})
        with self.assertRaisesRegex(AdapterError, "feature 'night_light'"):
            await self.s.command("lr-strip", Action.SET_TOGGLE, {"id": "night_light", "on": True})

    async def test_scene_list_refresh_is_saved(self):
        strip = self.s.get("lr-strip")
        strip.meta = {**strip.meta, "effects": strip.meta["effects"][:1]}
        await self.s.command("lr-strip", Action.UPDATE_EFFECTS)
        self.assertEqual(len(self.s.get("lr-strip").meta["effects"]), 15)
        with open(os.path.join(self.dir, "demo.json"), encoding="utf-8") as f:
            saved = next(d for d in json.load(f)["devices"] if d["id"] == "lr-strip")
        self.assertEqual(len(saved["meta"]["effects"]), 15)        # the new list is saved, not only in memory

    async def test_voice_picks_an_effect_by_name(self):
        plan = RulesParser().parse_now("set the backlight to sunset", self.s.voice.home())
        self.assertEqual([(s.device_id, s.action, s.value) for s in plan.steps],
                         [("lr-strip", Action.SET_EFFECT, "scene-sunset")])
        res = await self.s.voice.handle("set the tv backlight to the aurora scene")
        self.assertEqual(res["say"], "Set the TV backlight to Aurora.")
        self.assertEqual(self.s.get("lr-strip").state["effect"], "scene-aurora")


if __name__ == "__main__":
    unittest.main()
