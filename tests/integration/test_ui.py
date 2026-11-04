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

from tests.helpers import DemoServer


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

    def test_ambient_clock_wakes_without_toggling(self):
        self.page.click("#clock")
        self.page.wait_for_selector("#ambient:not([hidden])")
        before = self.tile("lr-lamp").evaluate("el => el.classList.contains('on')")
        self.page.locator("#ambient").click()
        self.page.wait_for_selector("#ambient", state="hidden")
        self.assertEqual(before, self.tile("lr-lamp").evaluate("el => el.classList.contains('on')"))


if __name__ == "__main__":
    unittest.main()
