"""Weather for the resting clock: parsing, caching, failures and settings. The source is faked (no internet)."""
import asyncio
import shutil
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from app.core.adapter import AdapterError
from app.core.service import HomeService
from app.core.weather import CACHE_SECONDS, RETRY_SECONDS, STALE_SECONDS, Weather, describe, parse

SAMPLE = {"current": {"temperature_2m": 53.6, "weather_code": 61, "is_day": 0},
          "daily": {"temperature_2m_max": [58.2], "temperature_2m_min": [44.9]}}


class FakeSource:
    def __init__(self, reply=SAMPLE):
        self.reply = reply
        self.urls = []

    async def __call__(self, url):
        self.urls.append(url)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"weather_enabled": True, "latitude": 47.61234, "longitude": -122.33456, "temperature_unit": "F"}
        self.now = 1_000_000.0
        self.source = FakeSource()
        self.w = Weather(lambda: self.settings, fetch=self.source, clock=lambda: self.now)

    def get(self):
        return asyncio.run(self.w.current())

    def test_parse_and_describe(self):
        out = parse(SAMPLE, "F")
        self.assertEqual((out["temperature"], out["high"], out["low"]), (54, 58, 45))
        self.assertEqual((out["condition"], out["label"], out["is_day"]), ("rain", "Rain", False))
        self.assertEqual(describe(0), ("clear", "Clear"))
        self.assertEqual(describe(95)[0], "storm")
        self.assertEqual(describe(1234)[0], "cloudy")   # unknown codes don't break the clock
        with self.assertRaises(ValueError):
            parse({"nope": 1}, "F")

    def test_off_without_opt_in_or_location(self):
        self.settings["weather_enabled"] = False
        self.assertEqual(self.get(), {"available": False, "reason": "off"})
        self.settings.update(weather_enabled=True, latitude=None)
        self.assertFalse(self.get()["available"])
        self.assertEqual(self.source.urls, [])          # nothing left the house

    def test_sends_rounded_location_and_unit(self):
        out = self.get()
        self.assertTrue(out["available"])
        q = parse_qs(urlsplit(self.source.urls[0]).query)
        self.assertEqual((q["latitude"], q["longitude"]), (["47.61"], ["-122.33"]))
        self.assertEqual(q["temperature_unit"], ["fahrenheit"])
        self.settings["temperature_unit"] = "C"
        self.assertEqual(self.get()["unit"], "C")
        self.assertEqual(parse_qs(urlsplit(self.source.urls[1]).query)["temperature_unit"], ["celsius"])

    def test_cached_between_fetches(self):
        self.get()
        self.now += CACHE_SECONDS - 1
        self.get()
        self.assertEqual(len(self.source.urls), 1)
        self.now += 2
        self.get()
        self.assertEqual(len(self.source.urls), 2)

    def test_failure_hides_weather_and_backs_off(self):
        self.source.reply = OSError("no internet")
        self.assertEqual(self.get(), {"available": False, "reason": "unavailable"})
        self.now += RETRY_SECONDS - 1
        self.get()
        self.assertEqual(len(self.source.urls), 1)      # doesn't hammer the source
        self.now += 2
        self.source.reply = SAMPLE
        self.assertTrue(self.get()["available"])

    def test_keeps_last_reading_for_a_while_when_source_fails(self):
        self.get()
        self.source.reply = OSError("down")
        self.now += CACHE_SECONDS + 1
        self.assertTrue(self.get()["available"])        # stale but recent: still shown
        self.now += STALE_SECONDS
        self.assertFalse(self.get()["available"])


class WeatherSettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_defaults_and_validation(self):
        s = self.svc.store.settings
        self.assertEqual((s["weather_enabled"], s["place_name"]), (False, ""))   # opt-in
        out = self.svc.update_settings({"place_name": "  New   York  City " * 5, "weather_enabled": "true",
                                        "temperature_unit": "c"})
        self.assertTrue(out["place_name"].startswith("New York City New"))
        self.assertLessEqual(len(out["place_name"]), 40)
        self.assertEqual((out["weather_enabled"], out["temperature_unit"]), (True, "C"))
        with self.assertRaises(AdapterError):
            self.svc.update_settings({"temperature_unit": "K"})


if __name__ == "__main__":
    unittest.main()
