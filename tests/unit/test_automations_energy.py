"""Unit tests: sunrise/sunset, energy history, presence and schedules (no network)."""
import asyncio
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from app.core.adapter import Action, AdapterError
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

    async def _settle(self):
        while self.svc._power_tasks:
            await asyncio.gather(*list(self.svc._power_tasks))

    async def test_device_trigger_runs_when_the_watched_device_turns_on(self):
        autos = self.svc.automations
        a = autos.save({"when": {"type": "device", "device_id": "bd-tv", "event": "on", "junk": 1},
                        "do": {"type": "command", "device_id": "bd-lamp", "action": "power", "value": True}})
        self.assertEqual(a["name"], "Bedside lamp on when LG TV turns on")
        self.assertEqual(a["when"], {"type": "device", "device_id": "bd-tv", "event": "on"})
        self.assertIsNone(a["next_run"])                       # it waits for the device, not for a time
        await self.svc.refresh("bd-lamp")
        await self.svc.refresh("bd-tv")                        # first reading: off. A baseline, not a change.
        await self._settle()
        self.assertFalse(self.svc.get("bd-lamp").state["on"])
        await self.svc.command("bd-tv", Action.POWER, True)
        await self._settle()
        self.assertTrue(self.svc.get("bd-lamp").state["on"])
        stored = next(x for x in self.svc.store.automations if x["id"] == a["id"])
        self.assertEqual(stored["last_result"], "ok")

        # Off and straight back on (a flicker, or two automations switching each other): no second run yet.
        first = stored["last_run"]
        await self.svc.command("bd-lamp", Action.POWER, False)
        await self.svc.command("bd-tv", Action.POWER, False)
        await self.svc.command("bd-tv", Action.POWER, True)
        await self._settle()
        self.assertEqual(stored["last_run"], first)
        self.assertFalse(self.svc.get("bd-lamp").state["on"])
        stored["last_run"] = first - 60                        # later on it runs again
        await self.svc.command("bd-tv", Action.POWER, False)
        await self.svc.command("bd-tv", Action.POWER, True)
        await self._settle()
        self.assertTrue(self.svc.get("bd-lamp").state["on"])

    async def test_device_trigger_ignores_offline_and_the_other_direction(self):
        autos = self.svc.automations
        autos.save({"when": {"type": "device", "device_id": "kt-kettle", "event": "off"}, "do": {"type": "all_off"}})
        await self.svc.command("lr-ceiling", Action.POWER, True)
        await self.svc.refresh("kt-kettle")
        await self.svc.command("kt-kettle", Action.POWER, True)       # "on" is not what this one waits for
        await self._settle()
        self.assertTrue(self.svc.get("lr-ceiling").state["on"])
        kettle = self.svc.get("kt-kettle")
        kettle.state = {"online": False, "error": "unplugged"}        # dropping off the network is not "off"
        self.svc._publish_device(kettle)
        await self._settle()
        self.assertTrue(self.svc.get("lr-ceiling").state["on"])
        await self.svc.refresh("kt-kettle")                           # back online, still on: nothing happened
        await self._settle()
        self.assertTrue(self.svc.get("lr-ceiling").state["on"])
        await self.svc.command("kt-kettle", Action.POWER, False)
        await self._settle()
        self.assertFalse(self.svc.get("lr-ceiling").state["on"])

    async def test_device_trigger_validation_and_cleanup(self):
        autos = self.svc.automations
        for when, do, message in (
            ({"type": "device", "device_id": "nope", "event": "on"}, {"type": "all_off"}, "device to watch"),
            ({"type": "device", "device_id": "bd-tv", "event": "maybe"}, {"type": "all_off"}, "turns on"),
            ({"type": "device", "device_id": "bd-tv", "event": "on"},
             {"type": "command", "device_id": "bd-tv", "action": "power", "value": False}, "different device"),
        ):
            with self.subTest(message=message), self.assertRaises(AdapterError) as cm:
                autos.save({"when": when, "do": do})
            self.assertIn(message, str(cm.exception))
        a = autos.save({"when": {"type": "device", "device_id": "bd-tv", "event": "off"}, "do": {"type": "all_off"}})
        self.assertEqual(a["name"], "All off when LG TV turns off")
        await self.svc.remove_device("bd-tv")                         # nothing left to watch
        self.assertNotIn(a["id"], [x["id"] for x in self.svc.store.automations])

    async def test_presence_automation_runs_all_off(self):
        await self.svc.command("lr-ceiling", Action.POWER, True)
        await self.svc.automations.on_presence("all_away")         # demo seeds "All off when everyone leaves"
        self.assertFalse(self.svc.get("lr-ceiling").state["on"])

    async def test_demo_energy_history(self):
        e = await self.svc.energy("kt-fridge")
        self.assertEqual(len(e["days"]), 7)
        self.assertGreater(e["week_kwh"], 1)


# --- Home Assistant adapter against a fake Home Assistant ------------------------------


if __name__ == "__main__":
    unittest.main()
