"""Animated weather tile with mocked weather and isolated demo data."""
import json
import os
import shutil
import tempfile
import unittest

from tests.helpers import DemoServer

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    if os.environ.get("REQUIRE_UI_TESTS"):
        raise
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class WeatherTileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir).start()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:
            cls.pw.stop()
            cls.server.stop()
            shutil.rmtree(cls.dir, ignore_errors=True)
            if os.environ.get("REQUIRE_UI_TESTS"):
                raise
            raise unittest.SkipTest(f"chromium not available: {e}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.errors = []
        self.pending = []
        self.response = self.weather("clear")
        self.page = self.browser.new_page(viewport={"width": 720, "height": 1280}, reduced_motion="no-preference")
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.route("**/api/v1/weather", self.respond)
        self.page.goto(self.server.url)
        self.page.wait_for_selector(".widget")
        self.page.evaluate("""async () => {
            const {api} = await import('/js/api.js');
            await api.saveSettings({weather_enabled:false, background:'night', place_name:'Demo weather'});
            await api.saveLayout({widgets:[{id:'weather',type:'weather',size:'2x2'}]});
            await (await import('/js/store.js')).reload();
        }""")

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    @staticmethod
    def weather(condition, is_day=True):
        return {"available": True, "temperature": 72, "high": 76, "low": 61, "unit": "F",
                "condition": condition, "label": condition.title(), "is_day": is_day}

    def respond(self, route):
        if self.response is None:
            self.pending.append(route)
        else:
            route.fulfill(json=self.response)

    def enable(self):
        self.page.evaluate("""async () => {
          await (await import('/js/api.js')).api.saveSettings({weather_enabled:true,latitude:0,longitude:0});
          await (await import('/js/store.js')).reload();
        }""")

    def refresh(self):
        self.page.evaluate("async () => (await import('/js/sky.js')).refreshWeather(true)")

    def test_supported_conditions_fill_tile_with_live_motion_and_readable_captions(self):
        from tests.integration.test_readability import ReadabilityTests
        self.enable()
        for condition, scene in (("clear", "clear"), ("partly-cloudy", "partly"), ("cloudy", "cloudy"),
                                 ("drizzle", "rain"), ("rain", "rain"), ("snow", "snow"), ("fog", "fog"), ("storm", "storm")):
            with self.subTest(condition=condition):
                self.response = self.weather(condition)
                self.refresh()
                self.page.wait_for_selector(f'.w-weather-fx[data-weather-scene="{scene}"][data-active="true"]')
                self.assertEqual(self.page.inner_text(".w-wx b"), "72°")
                self.assertTrue(self.page.locator(".w-weather-fx").evaluate(
                    "e => e.getAnimations({subtree:true}).some(a => a.playState === 'running')"))
                self.assertEqual(self.page.locator(".w-weather-fx").evaluate("e => getComputedStyle(e).pointerEvents"), "none")
                self.assertEqual(self.page.locator("html").get_attribute("data-bg"), "night")
                for selector in (".w-weather .w-label", ".w-weather .w-wx b", ".w-weather .w-sub"):
                    self.assertGreaterEqual(ReadabilityTests.surface(self, selector)["contrast"], 4.5)
        self.response = self.weather("clear", False)
        self.refresh()
        self.page.wait_for_selector('.w-weather-fx[data-weather-period="night"] .w-fx-moon')
        self.assertEqual(self.page.locator(".w-fx-sun").count(), 0)
        for style in ("light", "dark"):
            self.page.evaluate("""async style => {
              await (await import('/js/api.js')).api.saveSettings({tile_style:style});
              await (await import('/js/store.js')).reload();
            }""", style)
            for selector in (".w-weather .w-label", ".w-weather .w-wx b", ".w-weather .w-sub"):
                self.assertGreaterEqual(ReadabilityTests.surface(self, selector)["contrast"], 4.5)

    def test_resizing_reduced_motion_and_hidden_tiles(self):
        self.response = self.weather("rain")
        self.enable()
        self.page.wait_for_selector('.w-weather-fx[data-active="true"]')
        for size in ("1x1", "2x1", "2x2"):
            self.page.click("#edit-home")
            self.page.click('.widget[data-wid="weather"] [data-menu]')
            self.page.click(f'[data-size-pick="{size}"]')
            self.page.click(".wmenu button[data-menu-close]")
            self.page.click("[data-edit-done]")
            self.page.wait_for_selector(".home:not(.editing)")
            effect = self.page.locator(".w-weather-fx").bounding_box()
            tile = self.page.locator(".w-weather").bounding_box()
            for key in ("x", "y", "width", "height"):
                self.assertAlmostEqual(effect[key], tile[key], delta=1)
            self.assertEqual(self.page.locator(".w-weather").evaluate("e => getComputedStyle(e).overflow"), "hidden")
        self.page.emulate_media(reduced_motion="reduce")
        self.assertEqual(self.page.locator(".w-weather-fx").evaluate("e => e.getAnimations({subtree:true}).length"), 0)
        self.page.emulate_media(reduced_motion="no-preference")
        self.page.click('#dock [data-nav="rooms"]')
        self.page.wait_for_function("document.querySelector('.w-weather-fx').dataset.active === 'false'")
        self.assertTrue(self.page.locator(".w-weather-fx").evaluate(
            "e => e.getAnimations({subtree:true}).every(a => a.playState === 'paused')"))
        self.page.click('#dock [data-nav="home"]')
        self.page.click("#edit-home")
        self.page.click('.widget[data-wid="weather"] [data-hide]')
        self.assertEqual(self.page.locator(".w-weather-fx").count(), 0)
        self.page.click("[data-edit-cancel]")

    def test_missing_loading_error_retry_and_disabled_request_never_fake_weather(self):
        self.assertEqual(self.page.locator(".w-weather-fx").count(), 0)
        self.page.wait_for_selector('[data-weather-status="off"] [data-setup-weather]')
        self.response = None
        self.enable()
        self.page.wait_for_selector('[data-weather-status="loading"]')
        self.assertEqual(self.page.locator(".w-weather-fx").count(), 0)
        self.pending.pop(0).fulfill(json={"available": False, "reason": "unavailable"})
        self.page.wait_for_selector('[data-weather-status="unavailable"] [data-retry-weather]')
        self.assertEqual(self.page.locator(".w-weather-fx").count(), 0)
        self.response = self.weather("rain")
        self.page.click("[data-retry-weather]")
        self.page.wait_for_selector('[data-weather-scene="rain"]')
        self.response = None
        self.refresh()
        self.page.wait_for_selector('[data-weather-status="loading"]')
        self.page.evaluate("""async () => {
          await (await import('/js/api.js')).api.saveSettings({weather_enabled:false});
          await (await import('/js/store.js')).reload();
        }""")
        self.pending.pop(0).fulfill(body=json.dumps(self.weather("snow")), content_type="application/json")
        self.page.wait_for_selector('[data-weather-status="off"]')
        self.assertEqual(self.page.locator(".w-weather-fx").count(), 0)
