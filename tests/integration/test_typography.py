"""Typography controls and responsive layouts on isolated test data."""
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
class TypographyTests(unittest.TestCase):
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
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 720}, reduced_motion="reduce")
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.add_init_script("localStorage.setItem('view', JSON.stringify('rooms'))")
        self.page.goto(self.server.url)
        self.page.wait_for_selector(".tile")
        self.set_size("medium")
        self.page.evaluate("document.fonts.ready")

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def set_size(self, size):
        self.page.evaluate("""async size => {
          await (await import('/js/api.js')).api.saveSettings({font_size:size});
          await (await import('/js/store.js')).reload();
        }""", size)

    def state(self):
        return self.page.request.get(self.server.url + "/api/v1/state").json()

    def open_display(self):
        self.page.click("#rail [data-open-settings]")
        self.page.click('[data-go="display"]')
        self.page.wait_for_selector('input[name="font_size"]')

    def test_slider_previews_three_values_cancels_and_saves_for_all_profiles(self):
        page = self.page
        self.assertTrue(page.evaluate("document.fonts.check('17px Manrope')"))
        self.assertTrue(page.locator("body").evaluate("e => getComputedStyle(e).fontFamily.startsWith('Manrope')"))
        original = self.state()
        self.open_display()
        self.assertFalse(page.locator("[data-display]").evaluate("e => getComputedStyle(e).backgroundColor.startsWith('rgba')"))
        self.assertEqual(page.locator("[data-display]").evaluate("e => getComputedStyle(e).backdropFilter"), "none")
        slider = page.locator('input[name="font_size"]')
        self.assertEqual([slider.get_attribute(k) for k in ("min", "max", "step")], ["0", "2", "1"])
        self.assertEqual(slider.get_attribute("aria-valuetext"), "Medium")
        self.assertGreaterEqual(slider.bounding_box()["height"], 48)
        sizes = []
        for key, name, value in (("Home", "Small", "small"), ("ArrowRight", "Medium", "medium"), ("End", "Large", "large")):
            slider.focus()
            slider.press(key)
            self.assertEqual(slider.get_attribute("aria-valuetext"), name)
            self.assertEqual(page.locator("html").get_attribute("data-font-size"), value)
            sizes.append(page.locator("#rail .rail-item").first.evaluate("e => parseFloat(getComputedStyle(e).fontSize)"))
            self.assertEqual(self.state()["settings"]["font_size"], "medium")
        self.assertLess(sizes[0], sizes[1])
        self.assertLess(sizes[1], sizes[2])
        page.click("#settings [data-back]")
        self.assertEqual(page.locator("html").get_attribute("data-font-size"), "medium")
        page.click('[data-go="display"]')
        page.locator('input[name="font_size"]').press("End")
        page.click("[data-display] button[type=submit]")
        page.wait_for_selector("text=Saved")
        page.reload()
        page.wait_for_selector(".tile")
        self.assertEqual(page.locator("html").get_attribute("data-font-size"), "large")
        self.assertEqual(self.state()["settings"]["home_layout"], original["settings"]["home_layout"])
        self.assertEqual(self.state()["rooms"], original["rooms"])
        other = self.browser.new_page(viewport={"width": 720, "height": 1280})
        try:
            other.goto(self.server.url)
            other.wait_for_selector(".widget")
            self.assertEqual(other.locator("html").get_attribute("data-font-size"), "large")
            other.request.post(self.server.url + "/api/v1/auth/sign-in", data={"profile_id": "sam"})
            other.reload()
            other.wait_for_function("document.documentElement.dataset.role === 'member'")
            self.assertEqual(other.locator("html").get_attribute("data-font-size"), "large")
            self.assertEqual(other.request.put(self.server.url + "/api/v1/settings", data={"font_size": "small"}).status, 403)
        finally:
            other.close()

    def test_all_sizes_fit_long_rooms_small_tiles_settings_and_device_sheet(self):
        page = self.page
        for size in ("small", "medium", "large"):
            self.set_size(size)
            for width, height in ((393, 852), (720, 1280), (1280, 720)):
                with self.subTest(size=size, width=width):
                    page.set_viewport_size({"width": width, "height": height})
                    page.evaluate("""async () => {
                      const {store,emit} = await import('/js/store.js');
                      const room = 'Family entertainment room';
                      store.rooms = [room];
                      for (const d of store.devices.values()) d.room = room;
                      emit('all');
                    }""")
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                    for button in page.locator("#rail button:visible, #rooms button:visible, #room-tools button:visible").all():
                        self.assertGreaterEqual(button.bounding_box()["height"], 48)
                    page.locator('.tile[data-id="lr-lamp"] [data-more]').click()
                    page.wait_for_selector("#sheet:not([hidden])")
                    self.assertTrue(page.locator("#sheet").evaluate("e => e.scrollWidth <= e.clientWidth"))
                    page.click("#sheet [data-close]")
                    page.evaluate("""async () => {
                      const {store,setView} = await import('/js/store.js');
                      store.settings.home_layout = {widgets:[
                        {id:'clock',type:'clock',size:'1x1'},
                        {id:'weather',type:'weather',size:'1x1'}]};
                      setView('home');
                    }""")
                    for button in page.locator(".w-weather button:visible").all():
                        box = button.bounding_box()
                        tile = page.locator(".w-weather").bounding_box()
                        self.assertGreaterEqual(box["height"], 48)
                        self.assertLessEqual(box["x"] + box["width"], tile["x"] + tile["width"] + 1)
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                    page.evaluate("async () => (await import('/js/settings.js')).openSettings('display')")
                    page.wait_for_selector('[data-display] input[name="font_size"]')
                    self.assertTrue(page.locator("#settings").evaluate("e => e.scrollWidth <= e.clientWidth"))
                    self.assertGreaterEqual(page.locator('input[name="font_size"]').bounding_box()["height"], 48)
                    page.evaluate("async () => (await import('/js/settings.js')).closeSettings()")
                    page.evaluate("async () => (await import('/js/store.js')).setView('rooms')")

    def test_non_latin_text_uses_platform_fallback_without_losing_manrope(self):
        page = self.page
        page.evaluate("""() => {
          const sample = document.createElement('p');
          sample.id = 'fallback-sample'; sample.textContent = 'Home \\u5ba2\\u5385';
          document.body.append(sample);
        }""")
        page.evaluate("document.fonts.ready")
        page.locator("#fallback-sample").scroll_into_view_if_needed()
        cdp = page.context.new_cdp_session(page)
        cdp.send("DOM.enable")
        cdp.send("CSS.enable")
        document = cdp.send("DOM.getDocument")
        node = cdp.send("DOM.querySelector", {"nodeId": document["root"]["nodeId"], "selector": "#fallback-sample"})
        fonts = cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node["nodeId"]})["fonts"]
        self.assertTrue(any(f["isCustomFont"] and f["familyName"].startswith("Manrope") and f["glyphCount"] for f in fonts), fonts)
        self.assertTrue(any(not f["isCustomFont"] and f["glyphCount"] for f in fonts), fonts)

    def test_missing_font_uses_readable_local_fallback(self):
        page = self.browser.new_page(viewport={"width": 393, "height": 852})
        try:
            page.route("**/fonts/manrope-variable.ttf", lambda route: route.abort())
            page.add_init_script("localStorage.setItem('view', JSON.stringify('rooms'))")
            page.goto(self.server.url)
            page.wait_for_selector(".tile")
            page.evaluate("document.fonts.ready")
            self.assertFalse(page.evaluate("document.fonts.check('17px Manrope')"))
            self.assertTrue(page.locator(".tile-name").first.is_visible())
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 393)
        finally:
            page.close()
