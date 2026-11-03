"""Tests for sunrise/sunset, schedules, presence, energy history and the Home Assistant adapter."""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from app.core.adapter import Action, AdapterError, Cap, Device, Kind
from app.core.history import History
from app.core.presence import AWAY_AFTER, Presence
from app.core.service import HomeService
from app.core.sun import sun_event


class SunTimes(unittest.TestCase):
    def test_london_midsummer(self):
        utc = timezone.utc
        rise = sun_event(date(2024, 6, 20), 51.4779, -0.0015, "sunrise", utc)
        sett = sun_event(date(2024, 6, 20), 51.4779, -0.0015, "sunset", utc)
        # Published times for Greenwich: 03:43 and 20:21 UTC
        self.assertLess(abs((rise - datetime(2024, 6, 20, 3, 43, tzinfo=utc)).total_seconds()), 300)
        self.assertLess(abs((sett - datetime(2024, 6, 20, 20, 21, tzinfo=utc)).total_seconds()), 300)

    def test_west_coast_sunset_stays_on_the_same_local_day(self):
        pst = timezone(timedelta(hours=-8))
        t = sun_event(date(2026, 11, 3), 47.6, -122.3, "sunset", pst)
        self.assertEqual(t.date(), date(2026, 11, 3))
        self.assertTrue(16 <= t.hour <= 17)   # late afternoon in early November

    def test_polar_night(self):
        self.assertIsNone(sun_event(date(2026, 12, 21), 78.2, 15.6, "sunrise", timezone.utc))


class EnergyHistory(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.h = History(os.path.join(self.dir, "h.db"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_record_is_throttled(self):
        self.assertTrue(self.h.record("p", 10, ts=1000))
        self.assertFalse(self.h.record("p", 10, ts=1030))
        self.assertTrue(self.h.record("p", 10, ts=1061))

    def test_constant_100w_for_an_hour_is_point_one_kwh(self):
        start = datetime.now().astimezone().replace(hour=1, minute=0, second=0, microsecond=0).timestamp()
        self.h.bulk_insert([("p", start + i * 60, 100.0) for i in range(61)])
        days = self.h.energy_by_day("p", 1)
        self.assertAlmostEqual(days[-1]["kwh"], 0.1, places=3)

    def test_gaps_are_not_counted(self):
        start = datetime.now().astimezone().replace(hour=1, minute=0, second=0, microsecond=0).timestamp()
        self.h.bulk_insert([("p", start, 1000.0), ("p", start + 3600, 1000.0)])   # one hour apart = a gap
        self.assertEqual(self.h.energy_by_day("p", 1)[-1]["kwh"], 0)


class PresenceTracking(unittest.IsolatedAsyncioTestCase):
    async def test_events_after_learning(self):
        people = [{"name": "A", "ip": "10.0.0.2"}, {"name": "B", "ip": "10.0.0.3"}]
        events = []

        async def on_event(e):
            events.append(e)

        p = Presence(lambda: people, on_event)
        home = {"10.0.0.2": True, "10.0.0.3": False}

        async def prober(ip):
            return home[ip]

        t = 1_000_000.0
        await p.check_once(prober, now=t)                 # learns; no event on start-up
        home["10.0.0.2"] = False
        await p.check_once(prober, now=t + 60)            # phone asleep, but not away yet
        self.assertEqual(events, [])
        await p.check_once(prober, now=t + AWAY_AFTER + 61)
        self.assertEqual(events, ["all_away"])
        home["10.0.0.3"] = True
        await p.check_once(prober, now=t + AWAY_AFTER + 120)
        self.assertEqual(events, ["all_away", "someone_home"])


class Automations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_time_schedule_fires_once(self):
        a = self.svc.automations.save({"name": "Kettle", "when": {"type": "time", "at": "06:30", "days": list(range(7))},
                                       "do": {"type": "command", "device_id": "kt-kettle", "action": "power", "value": True}})
        today = datetime.now().astimezone()
        at = today.replace(hour=6, minute=30, second=20, microsecond=0)
        await self.svc.automations.tick(at)
        await self.svc.automations.tick(at + timedelta(seconds=30))     # same occurrence: no second run
        stored = next(x for x in self.svc.store.automations if x["id"] == a["id"])
        self.assertEqual(stored["last_result"], "ok")
        self.assertTrue(self.svc.get("kt-kettle").state["on"])
        self.assertIsNotNone(a["next_run"])

    async def test_not_due_outside_window_or_day(self):
        a = self.svc.automations.save({"when": {"type": "time", "at": "06:30", "days": [0]},
                                       "do": {"type": "all_off"}})
        monday = datetime(2026, 11, 2, 6, 31).astimezone()
        self.assertIsNotNone(self.svc.automations.due(a, monday))
        self.assertIsNone(self.svc.automations.due(a, monday + timedelta(minutes=5)))
        self.assertIsNone(self.svc.automations.due(a, monday + timedelta(days=1)))   # Tuesday

    async def test_validation(self):
        with self.assertRaises(AdapterError):
            self.svc.automations.save({"when": {"type": "sun", "event": "sunset"}, "do": {"type": "all_off"}})  # no location
        with self.assertRaises(AdapterError):
            self.svc.automations.save({"when": {"type": "time", "at": "25:00"}, "do": {"type": "all_off"}})
        with self.assertRaises(AdapterError):
            self.svc.automations.save({"when": {"type": "time", "at": "07:00"}, "do": {"type": "scene", "scene_id": "nope"}})
        self.svc.update_settings({"latitude": "47.6", "longitude": "-122.3"})
        a = self.svc.automations.save({"when": {"type": "sun", "event": "sunset", "offset_min": -15}, "do": {"type": "all_off"}})
        self.assertIn("sunset", a["name"])
        self.assertIsNotNone(a["next_run"])

    async def test_presence_automation_runs_all_off(self):
        await self.svc.command("lr-ceiling", Action.POWER, True)
        await self.svc.automations.on_presence("all_away")         # demo seeds "All off when everyone leaves"
        self.assertFalse(self.svc.get("lr-ceiling").state["on"])

    async def test_demo_energy_history(self):
        e = await self.svc.energy("kt-fridge")
        self.assertEqual(len(e["days"]), 7)
        self.assertGreater(e["week_kwh"], 1)


# --- Home Assistant adapter against a fake Home Assistant ------------------------------

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
