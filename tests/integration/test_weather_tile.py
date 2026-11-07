"""Animated weather tile with mocked weather and isolated demo data."""
import json
import io
import os
import shutil
import tempfile
import unittest
from PIL import Image

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

    def assert_scene_text_is_readable_without_backdrops(self):
        tile = self.page.locator(".w-weather")
        info = tile.evaluate("""root => {
          const selectors = ['.w-label', '.w-wx b', '.w-sub'];
          const regions = selectors.map(selector => {
            const el = root.querySelector(selector), range = document.createRange();
            range.selectNodeContents(el);
            const r = range.getBoundingClientRect(), box = el.getBoundingClientRect();
            return {selector, x:Math.max(r.x,box.x), y:r.y, right:Math.min(r.right,box.right), bottom:r.bottom,
              color:getComputedStyle(el).color.match(/[\\d.]+/g).map(Number)};
          });
          for (const el of [root, ...root.querySelectorAll(':scope > span')]) {
            if (getComputedStyle(el).backgroundColor !== 'rgba(0, 0, 0, 0)') throw new Error('Text has a backdrop');
          }
          root._moving = root.getAnimations({subtree:true}).filter(a => a.playState === 'running');
          root._moving.forEach(a => a.pause());
          root.querySelectorAll(':scope > span').forEach(el => {el.style.opacity = '0';});
          return regions;
        }""")
        box = tile.bounding_box()
        try:
            image = Image.open(io.BytesIO(tile.screenshot())).convert("RGB")
        finally:
            tile.evaluate("""root => {
              root.querySelectorAll(':scope > span').forEach(el => {el.style.opacity = '';});
              root._moving.forEach(a => a.play()); delete root._moving;
            }""")

        def luma(rgb):
            channels = [v / 255 for v in rgb[:3]]
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
            return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722), strict=True))

        for region in info:
            text = luma(region["color"])
            ratios = []
            left = max(0, int(region["x"] - box["x"]))
            top = max(0, int(region["y"] - box["y"]))
            right = min(image.width, int(region["right"] - box["x"]))
            bottom = min(image.height, int(region["bottom"] - box["y"]))
            for x in range(left, right, 2):
                for y in range(top, bottom, 2):
                    background = luma(image.getpixel((x, y)))
                    ratios.append((max(text, background) + .05) / (min(text, background) + .05))
            self.assertTrue(ratios, region["selector"])
            self.assertGreaterEqual(min(ratios), 4.5, (region["selector"], min(ratios)))

    def test_supported_conditions_fill_tile_with_live_motion_and_readable_captions(self):
        self.enable()
        for condition, scene in (("clear", "clear"), ("partly-cloudy", "partly"), ("cloudy", "cloudy"),
                                 ("drizzle", "rain"), ("rain", "rain"), ("snow", "snow"), ("fog", "fog"), ("storm", "storm")):
            with self.subTest(condition=condition):
                self.response = self.weather(condition)
                self.refresh()
                self.page.wait_for_function("label => document.querySelector('.w-weather .w-sub')?.textContent.startsWith(label)",
                                            arg=condition.title())
                self.page.wait_for_selector(f'.w-weather-fx[data-weather-scene="{scene}"][data-active="true"]')
                self.assertEqual(self.page.inner_text(".w-wx b"), "72°")
                self.assertTrue(self.page.locator(".w-weather-fx").evaluate(
                    "e => e.getAnimations({subtree:true}).some(a => a.playState === 'running')"))
                self.assertEqual(self.page.locator(".w-weather-fx").evaluate("e => getComputedStyle(e).pointerEvents"), "none")
                self.assertEqual(self.page.locator("html").get_attribute("data-bg"), "night")
                self.assert_scene_text_is_readable_without_backdrops()
        self.response = self.weather("clear", False)
        self.refresh()
        self.page.wait_for_selector('.w-weather-fx[data-weather-period="night"] .w-fx-moon')
        self.assertEqual(self.page.locator(".w-fx-sun").count(), 0)
        for style in ("light", "dark"):
            self.page.evaluate("""async style => {
              await (await import('/js/api.js')).api.saveSettings({tile_style:style});
              await (await import('/js/store.js')).reload();
            }""", style)
            self.assert_scene_text_is_readable_without_backdrops()

    def test_resizing_reduced_motion_and_hidden_tiles(self):
        self.response = self.weather("rain")
        self.enable()
        self.page.wait_for_selector('.w-weather-fx[data-active="true"]')
        rain = self.page.locator(".w-fx-rain")
        before = rain.evaluate("e => getComputedStyle(e).transform")
        self.page.wait_for_timeout(250)
        self.assertNotEqual(rain.evaluate("e => getComputedStyle(e).transform"), before)
        self.assertEqual(rain.evaluate("e => getComputedStyle(e).animationTimingFunction"), "linear")
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
            self.assert_scene_text_is_readable_without_backdrops()
        self.page.emulate_media(reduced_motion="reduce")
        self.assertEqual(self.page.locator(".w-weather-fx").evaluate("e => e.getAnimations({subtree:true}).length"), 0)
        self.assert_scene_text_is_readable_without_backdrops()
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
        self.page.wait_for_selector('[data-weather-status="ready"]')  # keep the known reading while updating
        self.page.evaluate("""async () => {
          await (await import('/js/api.js')).api.saveSettings({weather_enabled:false});
          await (await import('/js/store.js')).reload();
        }""")
        self.pending.pop(0).fulfill(body=json.dumps(self.weather("snow")), content_type="application/json")
        self.page.wait_for_selector('[data-weather-status="off"]')
        self.assertEqual(self.page.locator(".w-weather-fx").count(), 0)
