"""Integration tests for the touch UI in a real browser (skipped unless Playwright is installed).

    pip install playwright && playwright install chromium
"""
import os
import shutil
import tempfile
import unittest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    if os.environ.get("REQUIRE_UI_TESTS"):   # CI sets this so UI tests can never be skipped silently
        raise
    sync_playwright = None

from tests.helpers import DemoServer, FakeWeatherSource


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir).start()
        cls.port = cls.server.port
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:  # browser binaries not downloaded
            cls.pw.stop()
            cls.server.stop()
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
        self.page = self.browser.new_page(viewport={"width": 720, "height": 1280}, has_touch=True)
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.goto(f"http://127.0.0.1:{self.port}/")
        self.page.wait_for_selector(".tile")

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def tile(self, did):
        return self.page.locator(f'.tile[data-id="{did}"]')

    def test_tap_toggles_plug(self):
        self.page.wait_for_function("document.querySelector('.tile[data-id=\"kt-kettle\"] .tile-status').textContent === 'Off'")
        self.tile("kt-kettle").locator(".tile-name").click()
        self.page.wait_for_function("document.querySelector('.tile[data-id=\"kt-kettle\"]').classList.contains('on')")

    def test_tv_tap_opens_remote_not_power(self):
        self.tile("lr-tv").locator(".tile-name").click()
        self.page.wait_for_selector(".dpad")
        self.assertTrue(self.tile("lr-tv").evaluate("el => el.classList.contains('on')"))

    def test_sound_bar_opens_media_controls_and_picks_sound_mode(self):
        self.page.wait_for_selector('.tile[data-id="lr-soundbar"].wide')
        self.tile("lr-soundbar").locator(".tile-name").click()
        self.page.wait_for_selector('[data-sound-mode="cinema"]')
        self.assertTrue(self.tile("lr-soundbar").evaluate("el => el.classList.contains('on')"))  # tap didn't turn it off
        self.assertEqual(self.page.locator(".dpad").count(), 0)       # no TV remote for a speaker
        self.assertTrue(self.page.locator('[data-input="bt"]').is_visible())
        self.page.locator('[data-sound-mode="cinema"]').click()
        self.page.wait_for_selector('[data-sound-mode="cinema"][aria-pressed="true"]')
        box = self.page.locator('[data-sound-mode="cinema"]').bounding_box()
        self.assertGreaterEqual(box["height"], 48)

    def test_brightness_slider(self):
        self.tile("lr-ceiling").locator("[data-more]").click()
        box = self.page.locator("#bri").bounding_box()
        self.page.mouse.click(box["x"] + box["width"] * 0.3, box["y"] + box["height"] / 2)
        self.page.wait_for_function("document.querySelector('#bri-val').textContent === '30%'")

    def test_add_room_and_open_add_flow(self):
        self.page.click("#open-settings")
        self.page.click("[data-go=rooms]")
        self.page.fill("input[name=room]", "Office")
        self.page.click("[data-room-add] button[type=submit]")
        self.page.wait_for_selector("text=Office")
        self.page.click("[data-back]")
        self.page.click("[data-go=add]")
        self.page.wait_for_selector("text=Shelly")

    def test_energy_chart_for_metering_plug(self):
        self.tile("kt-fridge").locator("[data-more]").click()
        self.page.wait_for_selector(".bars .bar")
        self.assertEqual(self.page.locator(".bars .bar").count(), 7)

    def test_create_schedule(self):
        self.page.click("#open-settings")
        self.page.click("[data-go=automations]")
        self.page.click("[data-go=automation-new]")
        self.page.select_option("select[name=when]", "time")
        self.page.fill("input[name=at]", "22:30")
        self.page.select_option("select[name=do]", "all_off")
        self.page.fill("input[name=name]", "Lights out")
        self.page.click("[data-auto-form] button[type=submit]")
        self.page.wait_for_selector("text=Lights out")

    def test_glass_background_and_transparency(self):
        root = "document.documentElement"
        self.page.wait_for_function(f"{root}.dataset.bg === 'ocean' && {root}.classList.contains('glass')")
        self.page.click("#open-settings")
        self.page.click("[data-go=display]")
        self.page.click(".bg-choice:has(input[value=aurora])")
        self.page.fill("input[name=glass_transparency]", "80")   # live preview while dragging
        alpha = float(self.page.evaluate(f"getComputedStyle({root}).getPropertyValue('--glass-alpha')"))
        self.assertAlmostEqual(alpha, 0.92 - 80 * 0.0085, places=2)
        self.page.click("[data-display] button[type=submit]")
        self.page.wait_for_selector("text=Saved")
        self.page.reload()
        self.page.wait_for_function(f"{root}.dataset.bg === 'aurora'")
        # put things back for the other tests
        self.page.evaluate("""fetch('/api/v1/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'},
                              body: JSON.stringify({background: 'ocean', glass_transparency: 45})})""")

    def test_photo_frame_shows_photos_and_touch_exits(self):
        before = self.tile("lr-lamp").evaluate("el => el.classList.contains('on')")
        self.page.click("#open-frame")
        self.page.wait_for_selector("#frame:not([hidden])")
        self.page.wait_for_function("[...document.querySelectorAll('.frame-photo.visible')]"
                                    ".some(el => el.style.backgroundImage.includes('/api/v1/photos/'))")
        self.page.mouse.click(360, 400)            # where the floor lamp tile is underneath
        self.page.wait_for_selector("#frame", state="hidden")
        self.assertEqual(before, self.tile("lr-lamp").evaluate("el => el.classList.contains('on')"))

    def test_add_photo_from_settings(self):
        import os
        import tempfile
        from PIL import Image
        path = os.path.join(tempfile.mkdtemp(), "beach.jpg")
        Image.new("RGB", (1200, 800), (240, 200, 120)).save(path, "JPEG")
        self.page.click("#open-settings")
        self.page.click("[data-go=photos]")
        self.page.wait_for_selector(".thumb")
        count = self.page.locator(".thumb").count()
        self.page.set_input_files("#photo-input", path)
        self.page.wait_for_function(f"document.querySelectorAll('.thumb').length === {count + 1}")
        self.page.wait_for_selector("text=Added 1 photo")

    def test_tv_settings_have_a_mac_field(self):
        self.page.click("#open-settings")
        self.page.click("[data-go=devices]")
        self.page.click("[data-arg=lr-tv]")
        self.page.fill("#d-mac", "64:e4:a5:3:4:5")
        self.page.click("[data-save-device]")
        self.page.wait_for_selector("text=Saved")
        mac = self.page.evaluate("fetch('/api/v1/state').then(r => r.json()).then(s => s.devices.find(d => d.id === 'lr-tv').mac)")
        self.assertEqual(mac, "64:E4:A5:03:04:05")

    def test_demo_mode_explains_how_to_add_real_devices(self):
        self.page.click("#open-settings")
        self.page.click("[data-go=add]")
        self.page.click("[data-arg=shelly]")          # a brand with no extra libraries, so always available
        self.page.wait_for_selector("text=You're in demo mode")

    def test_robot_vacuum_sheet(self):
        tile = self.page.locator('.tile[data-id="lr-vacuum"]')
        tile.click()                                         # opens controls, never starts cleaning by itself
        self.page.wait_for_selector("#sheet:not([hidden]) [data-clean]")
        self.assertEqual(self.page.locator("#sheet [data-power]").count(), 0)   # no on/off button
        self.assertIn("Battery", self.page.locator("#sheet").inner_text())
        self.page.click("#sheet [data-clean=start]")
        self.page.wait_for_selector("#sheet [data-clean=pause]")
        self.page.wait_for_function(
            "document.querySelector('.tile[data-id=\"lr-vacuum\"] .tile-status').textContent.startsWith('Cleaning')")
        self.page.click("#sheet [data-dock]")
        self.page.wait_for_function(
            "document.querySelector('#sheet .sheet-head p').textContent.startsWith('Going back to dock')")
        box = self.page.locator("#sheet [data-clean]").bounding_box()
        self.assertGreaterEqual(box["height"], 48)               # touch target
        self.assertEqual(self.errors, [])

    def test_robot_vacuum_map_rooms_and_settings(self):
        self.page.locator('.tile[data-id="lr-vacuum"]').click()
        self.page.wait_for_function("(() => { const i = document.querySelector('#sheet .vac-map img');"
                                    " return i && i.complete && i.naturalWidth > 0; })()")      # the map loaded
        self.page.click('#sheet [data-room-pick="2"]')
        self.page.click('#sheet [data-room-pick="3"]')
        self.page.wait_for_selector("text=Clean these 2 rooms")
        self.page.click("#sheet [data-clean-rooms]")
        self.page.wait_for_selector("#sheet [data-clean=pause]")
        self.page.click('#sheet [data-suction="quiet"]')
        self.page.wait_for_selector('#sheet [data-suction="quiet"][aria-pressed="true"]')
        self.page.click("#sheet [data-locate]")
        self.page.wait_for_selector("text=Your vacuum is making a sound")
        self.assertIn("Filter", self.page.locator("#sheet .vac-parts").text_content())   # folded away until tapped
        for sel in ('[data-room-pick="1"]', '[data-suction="quiet"]', "[data-locate]"):
            self.assertGreaterEqual(self.page.locator(f"#sheet {sel}").bounding_box()["height"], 48)
        self.page.click("#sheet [data-dock]")                      # leave it docked for the other tests
        self.page.wait_for_selector("#sheet [data-clean=start]")
        self.assertEqual(self.errors, [])

    def test_search_all_brands_from_add_screen(self):
        self.page.click("#open-settings")
        self.page.click("[data-go=add]")
        self.page.click("[data-discover-all]")
        self.page.wait_for_selector("[data-search-all-results] .row")
        rows = self.page.locator("[data-search-all-results] .row")
        self.assertGreaterEqual(rows.count(), 10)
        self.assertIn("Demo devices", rows.first.inner_text())
        self.page.wait_for_selector("text=Search again")
        btn = self.page.locator("[data-discover-all]").bounding_box()
        self.assertGreaterEqual(btn["height"], 48)                  # touch target
        self.assertEqual(self.errors, [])

    def test_ambient_clock_wakes_without_toggling(self):
        self.page.click("#clock")
        self.page.wait_for_selector("#ambient:not([hidden])")
        before = self.tile("lr-lamp").evaluate("el => el.classList.contains('on')")
        self.page.locator("#ambient").click()
        self.page.wait_for_selector("#ambient", state="hidden")
        self.assertEqual(before, self.tile("lr-lamp").evaluate("el => el.classList.contains('on')"))


    def test_each_clock_face_shows_and_wakes(self):
        faces = ["digital", "analog", "words", "date", "night"]
        try:
            for face in faces:
                with self.subTest(face=face):
                    self.page.click("#open-settings")
                    self.page.click("[data-go=display]")
                    self.page.click(f".face-choice:has(input[value={face}])")
                    self.page.click("[data-display] button[type=submit]")
                    self.page.wait_for_selector("[data-go=display]")      # saved, back on the settings home
                    self.page.click("#settings [data-back]")
                    self.page.wait_for_selector("#settings", state="hidden")
                    self.page.click("#clock")
                    self.page.wait_for_selector(f"#ambient[data-face={face}] .cf-{face}")
                    self.assertTrue(self.page.locator(f"#ambient .cf-{face}").is_visible())
                    before = self.tile("lr-lamp").evaluate("el => el.classList.contains('on')")
                    self.page.locator("#ambient").click()
                    self.page.wait_for_selector("#ambient", state="hidden")
                    self.assertEqual(before, self.tile("lr-lamp").evaluate("el => el.classList.contains('on')"))
        finally:
            self.page.evaluate("""fetch('/api/v1/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'},
                                  body: JSON.stringify({clock_face: 'digital'})})""")

    def put_settings(self, **s):
        import json
        self.page.evaluate(f"""fetch('/api/v1/settings', {{method: 'PUT', headers: {{'Content-Type': 'application/json'}},
                                body: JSON.stringify({json.dumps(s)})}})""")

    def show_clock(self):
        self.page.reload()
        self.page.wait_for_selector(".tile")
        self.page.click("#clock")
        self.page.wait_for_selector("#ambient:not([hidden])")

    def test_clock_shows_weather_and_place_and_hides_weather_when_unavailable(self):
        source = FakeWeatherSource(temperature=53.6, code=61)
        os.environ["HOMEPANEL_WEATHER_URL"] = source.url
        try:
            # opt in through Settings → Location and presence
            self.page.click("#open-settings")
            self.page.click("[data-go=location]")
            self.page.fill("input[name=latitude]", "47.61")
            self.page.fill("input[name=longitude]", "-122.33")
            self.page.fill("input[name=place_name]", "Seattle")
            self.page.check("input[name=weather_enabled]")
            self.page.click("[data-location] button[type=submit]")
            self.page.wait_for_selector("text=Location saved")
            for face in ("digital", "analog", "words", "date"):
                with self.subTest(face=face):
                    self.put_settings(clock_face=face)
                    self.show_clock()
                    self.page.wait_for_selector("#ambient .cf-wx[data-condition=rain] .cf-wx-icon")
                    text = self.page.inner_text("#ambient")
                    self.assertIn("54°", text)
                    self.assertIn("Seattle".upper() if face == "date" else "Seattle", text)
            self.put_settings(clock_face="night")              # night face: just a dim temperature
            self.show_clock()
            self.page.wait_for_selector("#ambient .cf-night .cf-temp")
            self.assertEqual(self.page.locator("#ambient .cf-wx-icon").count(), 0)
            before = self.tile("lr-lamp").evaluate("el => el.classList.contains('on')")
            self.page.locator("#ambient").click()
            self.page.wait_for_selector("#ambient", state="hidden")
            self.assertEqual(before, self.tile("lr-lamp").evaluate("el => el.classList.contains('on')"))

            # source unreachable → the clock just leaves the weather out
            source.stop()
            os.environ["HOMEPANEL_WEATHER_URL"] = source.url.replace("/v1", "/gone/v1")
            self.put_settings(clock_face="digital", temperature_unit="C")
            self.show_clock()
            self.page.wait_for_selector("#ambient .cf-wx .cf-place")  # place still shown
            self.page.wait_for_timeout(500)
            self.assertEqual(self.page.locator("#ambient .cf-wx-icon").count(), 0)
            self.assertNotIn("°", self.page.inner_text("#ambient"))
        finally:
            os.environ.pop("HOMEPANEL_WEATHER_URL", None)
            self.put_settings(clock_face="digital", latitude=None, longitude=None, place_name="",
                              weather_enabled=False, temperature_unit="F")

    def test_clock_face_logic(self):
        words, drift = self.page.evaluate("""async () => {
            const m = await import('/js/clockfaces.js');
            const words = [[10, 15], [10, 45], [23, 58], [0, 2], [12, 1], [9, 33], [21, 0]].map(([h, mi]) => m.wordTime(h, mi));
            const drift = [];
            for (let t = 0; t < 4 * 3600e3; t += 97e3) drift.push(m.driftOffset(t, 40, 30));
            return [words, drift];
        }""")
        self.assertEqual(words, ["It's quarter past ten", "It's quarter to eleven", "It's midnight", "It's midnight",
                                 "It's noon", "It's twenty-five to ten", "It's nine o'clock"])
        self.assertTrue(all(abs(x) <= 40 and abs(y) <= 30 for x, y in drift))
        self.assertGreater(len({tuple(d) for d in drift}), 50)   # it really moves around

    def test_ambient_clock_drifts_within_screen(self):
        self.page.click("#clock")
        self.page.wait_for_selector("#ambient .cf-digital")
        box = self.page.evaluate("""() => { const r = document.querySelector('#ambient-face').getBoundingClientRect();
                                    return [r.left, r.top, r.right, r.bottom, innerWidth, innerHeight]; }""")
        left, top, right, bottom, w, h = box
        self.assertTrue(left >= 0 and top >= 0 and right <= w and bottom <= h, box)
        self.page.locator("#ambient").click()


if __name__ == "__main__":
    unittest.main()
