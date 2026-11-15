"""Animated weather tile with mocked weather and isolated demo data."""
import json
import io
import os
import shutil
import tempfile
import unittest
from PIL import Image, ImageChops, ImageStat

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
    def weather(condition, is_day=True, hours=0, wet=()):
        """A reading; hours=12 adds the coming hours from 9 PM, cooling a degree an hour, raining in the `wet` ones."""
        return {"available": True, "temperature": 72, "feels_like": 66, "high": 76, "low": 61, "unit": "F",
                "condition": condition, "label": condition.title(), "is_day": is_day,
                "hours": [{"at": 2_000_000_000 + i * 3600, "hour": (21 + i) % 24, "temperature": 71 - i,
                           "rain": 80 if i in wet else 5, "condition": "rain" if i in wet else "partly-cloudy",
                           "label": "Rain" if i in wet else "Partly cloudy", "is_day": False} for i in range(hours)]}

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
          const selectors = ['.w-label', '.w-wx b', '.w-sub', '.wx-range', '.wx-feels', '.wx-outlook', '.wx-hour b', '.wx-hour small'];
          const shown = selectors.flatMap(selector => [...root.querySelectorAll(selector)].map(el => [selector, el]))
            .filter(([, el]) => el.getClientRects().length);                       // what this size of tile shows
          for (const needed of ['.w-label', '.w-wx b', '.w-sub']) if (!shown.some(([s]) => s === needed)) throw new Error('Missing ' + needed);
          const regions = shown.map(([selector, el]) => {
            const range = document.createRange();
            range.selectNodeContents(el);
            const r = range.getBoundingClientRect(), box = el.getBoundingClientRect();
            return {selector, x:Math.max(r.x,box.x), y:r.y, right:Math.min(r.right,box.right), bottom:r.bottom,
              color:getComputedStyle(el).color.match(/[\\d.]+/g).map(Number)};
          });
          const parts = [...root.querySelectorAll(':scope > :not(.w-weather-fx)')];  // everything drawn over the sky
          for (const el of [root, ...parts, ...root.querySelectorAll('.wx-hour, .wx-hour *')]) {
            if (getComputedStyle(el).backgroundColor !== 'rgba(0, 0, 0, 0)') throw new Error('Text has a backdrop');
          }
          root._moving = root.getAnimations({subtree:true}).filter(a => a.playState === 'running');
          root._moving.forEach(a => a.pause());
          parts.forEach(el => {el.style.opacity = '0';});
          return regions;
        }""")
        box = tile.bounding_box()
        try:
            image = Image.open(io.BytesIO(tile.screenshot())).convert("RGB")
        finally:
            tile.evaluate("""root => {
              root.querySelectorAll(':scope > :not(.w-weather-fx)').forEach(el => {el.style.opacity = '';});
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

    def resize(self, size):
        self.page.evaluate("""async size => {
            await (await import('/js/api.js')).api.saveLayout({widgets:[{id:'weather',type:'weather',size}]});
            await (await import('/js/store.js')).reload();
        }""", size)
        self.page.wait_for_selector(f'.widget.s-{size} .w-weather[data-weather-status="ready"]')

    def clipped(self):
        """Text in the tile that doesn't fit its line or spills out of the tile (a long place name may be shortened)."""
        return self.page.locator(".w-weather").evaluate("""root => {
          const tile = root.getBoundingClientRect();
          return [...root.querySelectorAll('.w-wx b, .w-sub > span, .wx-range, .wx-outlook, .wx-hour b, .wx-hour small')]
            .filter(el => el.getClientRects().length).filter(el => {
              const r = el.getBoundingClientRect();
              return el.scrollWidth > el.clientWidth + 1 || r.right > tile.right + 1 || r.bottom > tile.bottom + 1 || r.left < tile.left - 1;
            }).map(el => el.className + ': ' + el.textContent);
        }""")

    def test_coming_hours_grow_with_the_tile_and_stay_readable(self):
        self.response = self.weather("partly-cloudy", hours=12, wet=(2, 3, 4))
        self.enable()
        self.page.wait_for_selector(".w-weather.has-hours")
        shown = lambda sel: self.page.locator(f".w-weather {sel}").first.is_visible()
        # Large: now, one sentence about rain, the line of the next 12 hours, and four hours spelled out.
        self.assertEqual(self.page.inner_text(".w-wx b"), "72°")
        self.assertEqual(self.page.locator(".w-sub").inner_text().replace("\n", ""), "Partly-Cloudy, feels like 66°")
        self.assertEqual(self.page.inner_text(".wx-range"), "H 76° L 61°")
        self.assertEqual(self.page.inner_text(".wx-outlook"), "Rain around 11 PM")
        self.assertEqual(self.page.locator(".wx-hour").count(), 4)
        self.assertEqual(self.page.locator(".wx-hour small").all_inner_texts(), ["10 PM", "1 AM", "4 AM", "7 AM"])
        self.assertEqual(self.page.locator(".wx-hour b").all_inner_texts(), ["70°", "67°", "64°", "61°"])
        self.assertIn("80% chance of rain", self.page.locator(".wx-hour").nth(1).get_attribute("aria-label") or "")
        self.assertEqual(self.page.locator(".wx-rain rect").count(), 3)            # only the hours with a real chance
        self.assertTrue(shown(".wx-chart") and shown(".wx-hours") and shown(".wx-outlook"))
        # Each spelled-out hour sits under its own point on the line.
        offsets = self.page.locator(".w-weather").evaluate("""root => [...root.querySelectorAll('.wx-chart i')].map((dot, i) => {
          const d = dot.getBoundingClientRect(), c = root.querySelectorAll('.wx-hour')[i].getBoundingClientRect();
          return Math.abs((d.left + d.width / 2) - (c.left + c.width / 2));
        })""")
        self.assertEqual(len(offsets), 4)
        self.assertLessEqual(max(offsets), 1.5, offsets)
        self.assertEqual(self.clipped(), [])
        self.assert_scene_text_is_readable_without_backdrops()
        # Wide: the hours sit beside now; no line, no sentence. Small: now only.
        self.resize("2x1")
        self.assertTrue(shown(".wx-hours"))
        self.assertFalse(shown(".wx-chart") or shown(".wx-outlook") or shown(".wx-feels"))
        self.assertEqual(self.clipped(), [])
        self.assert_scene_text_is_readable_without_backdrops()
        now, hours = self.page.locator(".w-wx b").bounding_box(), self.page.locator(".wx-hours").bounding_box()
        self.assertLessEqual(now["x"] + now["width"], hours["x"])                  # side by side, not on top of each other
        self.resize("1x1")
        self.assertFalse(shown(".wx-hours") or shown(".wx-chart") or shown(".wx-outlook"))
        self.assertTrue(shown(".wx-range"))
        self.assertEqual(self.clipped(), [])
        # Night, with the moon out: the hours stay clear of it and readable, in every size.
        self.response = self.weather("clear", False, hours=12)
        self.refresh()
        self.page.wait_for_selector(".w-fx-moon")
        for size in ("2x1", "2x2"):
            with self.subTest(size=size, night=True):
                self.resize(size)
                self.assertEqual(self.clipped(), [])
                self.assert_scene_text_is_readable_without_backdrops()
        self.assertEqual(self.page.inner_text(".wx-outlook"), "Dry for the next 12 hours")
        # 24-hour clocks get 24-hour hours; larger text still fits.
        self.page.evaluate("""async () => {
          await (await import('/js/api.js')).api.saveSettings({clock_24h:true, font_size:'large'});
          await (await import('/js/store.js')).reload();
        }""")
        self.page.wait_for_function("document.querySelector('.wx-hour small')?.textContent === '22:00'")
        for size in ("2x2", "2x1", "1x1"):
            with self.subTest(size=size, large_text=True):
                self.resize(size)
                self.assertEqual(self.clipped(), [])
        # A reading without hours is the small layout at every size.
        self.response = self.weather("rain")
        self.refresh()
        self.page.wait_for_function("!document.querySelector('.w-weather.has-hours')")
        self.resize("2x2")
        self.assertEqual(self.page.locator(".wx-hours, .wx-chart, .wx-outlook").count(), 0)
        self.assertEqual(self.clipped(), [])
        self.page.evaluate("""async () => {
          await (await import('/js/api.js')).api.saveSettings({clock_24h:false, font_size:'medium'});
          await (await import('/js/store.js')).reload();
        }""")

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

    def test_night_cloud_motion_changes_visible_pixels_and_preserves_legibility(self):
        self.response = self.weather("cloudy", False)
        self.enable()
        self.page.wait_for_selector('.w-weather-fx[data-active="true"]')
        self.page.wait_for_function("""document.getAnimations().filter(a =>
            Number.isFinite(a.effect.getComputedTiming().endTime)).every(a => a.playState !== 'running')""")
        cloud = self.page.locator(".w-fx-clouds")
        before_time = cloud.evaluate("e => e.getAnimations()[0].currentTime")
        cloud.evaluate("e => {window.originalCloud = e;}")
        first = Image.open(io.BytesIO(self.page.locator(".w-weather").screenshot())).convert("RGB")
        self.page.wait_for_timeout(3000)
        second = Image.open(io.BytesIO(self.page.locator(".w-weather").screenshot())).convert("RGB")
        self.assertTrue(cloud.evaluate("e => e === window.originalCloud"))
        self.assertGreater(cloud.evaluate("e => e.getAnimations()[0].currentTime"), before_time + 2500)
        delta = ImageChops.difference(first, second)
        red, green, blue = delta.split()
        largest_change = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        changed = sum(largest_change.histogram()[12:]) / (delta.width * delta.height)
        self.assertGreaterEqual(changed, .08, changed)
        self.assertGreaterEqual(sum(ImageStat.Stat(delta).mean) / 3, 1.8)
        self.assert_scene_text_is_readable_without_backdrops()
        for condition in ("partly-cloudy", "cloudy", "rain", "snow", "fog", "storm"):
            self.response = self.weather(condition, False)
            self.refresh()
            self.page.wait_for_function("label => document.querySelector('.w-weather .w-sub')?.textContent.startsWith(label)",
                                        arg=condition.title())
            for phase in (0, 7, 14, 21):
                with self.subTest(condition=condition, phase=phase):
                    self.page.locator(".w-weather-fx").evaluate(
                        "(el, time) => el.getAnimations({subtree:true}).forEach(a => {a.pause(); a.currentTime=time;})", phase * 1000)
                    self.assert_scene_text_is_readable_without_backdrops()
        for size in ("1x1", "2x1"):
            self.page.evaluate("""async size => {
                await (await import('/js/api.js')).api.saveLayout({widgets:[{id:'weather',type:'weather',size}]});
                await (await import('/js/store.js')).reload();
            }""", size)
            for condition in ("cloudy", "partly-cloudy"):
                self.response = self.weather(condition, False)
                self.refresh()
                self.page.wait_for_function("label => document.querySelector('.w-weather .w-sub')?.textContent.startsWith(label)",
                                            arg=condition.title())
                for phase in (0, 7, 14, 21):
                    with self.subTest(size=size, condition=condition, phase=phase):
                        self.page.locator(".w-weather-fx").evaluate(
                            "(el, time) => el.getAnimations({subtree:true}).forEach(a => {a.pause(); a.currentTime=time;})", phase * 1000)
                        self.assert_scene_text_is_readable_without_backdrops()
        self.page.emulate_media(reduced_motion="reduce")
        self.assertEqual(self.page.locator(".w-weather-fx").evaluate("e => e.getAnimations({subtree:true}).length"), 0)
        self.assert_scene_text_is_readable_without_backdrops()

    def test_snapshots_preserve_weather_nodes_and_obscured_effects_pause_then_resume(self):
        self.response = self.weather("cloudy", False)
        self.enable()
        self.page.wait_for_selector('.w-weather-fx[data-active="true"]')
        result = self.page.evaluate("""async () => {
          const cloud=document.querySelector('.w-fx-clouds'), animation=cloud.getAnimations()[0];
          for(let i=0;i<8;i++) await (await import('/js/store.js')).reload();
          return {node:cloud===document.querySelector('.w-fx-clouds'),
            animation:animation===document.querySelector('.w-fx-clouds').getAnimations()[0]};
        }""")
        self.assertEqual(result, {"node": True, "animation": True})
        self.page.evaluate("async () => (await import('/js/sheet.js')).openDevice('lr-soundbar')")
        self.assertEqual(self.page.locator(".w-fx-clouds").evaluate("e => getComputedStyle(e).animationPlayState"), "paused")
        self.page.click("#sheet .panel-head [data-close]")
        self.page.wait_for_selector("#sheet", state="hidden")
        self.assertEqual(self.page.locator(".w-fx-clouds").evaluate("e => getComputedStyle(e).animationPlayState"), "running")
        self.page.click("#open-settings")
        self.assertEqual(self.page.locator(".w-fx-clouds").evaluate("e => getComputedStyle(e).animationPlayState"), "paused")
        self.page.click("#settings [data-back]")
        self.assertEqual(self.page.locator(".w-fx-clouds").evaluate("e => getComputedStyle(e).animationPlayState"), "running")

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
