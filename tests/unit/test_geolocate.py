"""Location lookup for "Use my location": parsing, rounding, fallback order and errors.
The lookup services are faked (no internet)."""
import asyncio
import unittest
from unittest import mock

from app.core.adapter import AdapterError
from app.core.geolocate import (IP_SOURCES, REVERSE_URL, Geolocator, check_coords, parse_ipapi,
                                parse_ipwhois, parse_reverse, place_label)
from app.core.net import HttpError
from tests.helpers import IPAPI_SEATTLE, IPWHOIS_LYON, REVERSE_SEATTLE


class FakeServices:
    """Answers by URL prefix; an Exception answer is raised."""

    def __init__(self, answers):
        self.answers = answers
        self.urls = []

    async def __call__(self, url):
        self.urls.append(url)
        for prefix, answer in self.answers.items():
            if url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise OSError("no route")


def run(coro):
    return asyncio.run(coro)


class ParsingTests(unittest.TestCase):
    def test_ipapi(self):
        self.assertEqual(parse_ipapi(IPAPI_SEATTLE),
                         {"latitude": 47.61, "longitude": -122.33, "place_name": "Seattle, WA"})

    def test_ipwhois(self):
        self.assertEqual(parse_ipwhois(IPWHOIS_LYON),
                         {"latitude": 45.76, "longitude": 4.84, "place_name": "Lyon, France"})

    def test_reverse(self):
        self.assertEqual(parse_reverse(REVERSE_SEATTLE), "Seattle, WA")
        self.assertEqual(parse_reverse({"locality": "Tiny Town", "countryName": "Norway", "countryCode": "NO"}),
                         "Tiny Town, Norway")
        self.assertEqual(parse_reverse("not json"), "")

    def test_place_label_edge_cases(self):
        self.assertEqual(place_label("", "WA", "Washington", "United States", "US"), "Washington, WA")
        self.assertEqual(place_label("Monaco", None, None, "Monaco", "MC"), "Monaco")
        self.assertLessEqual(len(place_label("A" * 60, None, None, "B", "XX")), 40)

    def test_rounding_and_checks(self):
        self.assertEqual(check_coords("47.60621", -122.33207), (47.61, -122.33))
        for bad in (("x", 1), (91, 0), (0, 181), (float("nan"), 0)):
            with self.assertRaises(AdapterError):
                check_coords(*bad)


class LookupTests(unittest.TestCase):
    def test_device_coords_get_a_place_name_and_are_rounded_before_sending(self):
        fake = FakeServices({REVERSE_URL: REVERSE_SEATTLE})
        out = run(Geolocator(fake).lookup(47.606209, -122.332071))
        self.assertEqual(out, {"latitude": 47.61, "longitude": -122.33, "place_name": "Seattle, WA",
                               "source": "device"})
        self.assertEqual(len(fake.urls), 1)
        self.assertIn("latitude=47.61&longitude=-122.33", fake.urls[0])   # never the precise position
        self.assertFalse(any(u.startswith(IP_SOURCES[0]) for u in fake.urls))

    def test_device_coords_without_place_name_when_offline(self):
        out = run(Geolocator(FakeServices({REVERSE_URL: OSError("offline")})).lookup(47.6, -122.3))
        self.assertEqual((out["latitude"], out["place_name"], out["source"]), (47.6, "", "device"))

    def test_approximate_uses_first_service(self):
        fake = FakeServices({IP_SOURCES[0]: IPAPI_SEATTLE, IP_SOURCES[1]: IPWHOIS_LYON})
        out = run(Geolocator(fake).lookup())
        self.assertEqual((out["place_name"], out["source"]), ("Seattle, WA", "approximate"))
        self.assertEqual(fake.urls, [IP_SOURCES[0]])

    def test_falls_back_to_second_service(self):
        for first in (HttpError(429, "Too many"), {"error": True, "reason": "RateLimited"}, OSError("timeout"),
                      {"city": "no coords"}):
            with self.subTest(first=first):
                fake = FakeServices({IP_SOURCES[0]: first, IP_SOURCES[1]: IPWHOIS_LYON})
                out = run(Geolocator(fake).lookup())
                self.assertEqual((out["place_name"], out["latitude"]), ("Lyon, France", 45.76))
                self.assertEqual(fake.urls, list(IP_SOURCES))

    def test_plain_errors_when_both_fail(self):
        busy = FakeServices({IP_SOURCES[0]: HttpError(429, ""), IP_SOURCES[1]: {"success": False,
                                                                                "message": "Rate limit reached"}})
        with self.assertRaises(AdapterError) as cm:
            run(Geolocator(busy).lookup())
        self.assertIn("busy", str(cm.exception))
        with self.assertRaises(AdapterError) as cm:
            run(Geolocator(FakeServices({})).lookup())
        self.assertIn("internet connection", str(cm.exception))

    def test_source_urls_can_be_pointed_elsewhere(self):
        fake = FakeServices({"http://stub/a": OSError("down"), "http://stub/b": IPWHOIS_LYON})
        with mock.patch.dict("os.environ", {"HOMEPANEL_GEO_IP_URLS": "http://stub/a, http://stub/b"}):
            self.assertEqual(run(Geolocator(fake).lookup())["place_name"], "Lyon, France")


if __name__ == "__main__":
    unittest.main()
