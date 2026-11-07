"""Device-panel usability and command safety on isolated household fixtures."""
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
class DevicePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir).start()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as error:
            cls.pw.stop()
            cls.server.stop()
            shutil.rmtree(cls.dir, ignore_errors=True)
            if os.environ.get("REQUIRE_UI_TESTS"):
                raise
            raise unittest.SkipTest(f"chromium not available: {error}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 720, "height": 1280}, has_touch=True, reduced_motion="reduce")
        self.errors, self.commands = [], []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("request", lambda r: self.commands.append(r.post_data_json)
                     if r.method == "POST" and r.url.endswith("/command") else None)
        self.page.goto(self.server.url)
        self.page.wait_for_selector(".tile, .widget")

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def open(self, did):
        self.page.evaluate("async id => (await import('/js/sheet.js')).openDevice(id)", did)
        self.page.wait_for_selector("#sheet:not([hidden])")

    def test_all_panels_are_opaque_readable_and_fit_font_sizes(self):
        from tests.integration.test_readability import ReadabilityTests
        page = self.page
        for theme in ("light", "dark"):
            for size, w, h in (("small", 393, 852), ("medium", 720, 1280), ("large", 1280, 720),
                                ("large", 393, 852), ("large", 720, 1280)):
                for did in ("lr-tv", "lr-strip", "kt-fridge", "lr-vacuum"):
                    with self.subTest(theme=theme, size=size, device=did):
                        page.set_viewport_size({"width": w, "height": h})
                        page.evaluate("""async prefs => {
                          const {store,emit} = await import('/js/store.js');
                          Object.assign(store.settings,prefs); emit('all');
                        }""", {"tile_style": theme, "font_size": size, "glass_effect": False, "glass_transparency": 100})
                        self.assertEqual(page.locator("html").get_attribute("data-font-size"), size)
                        self.assertEqual(page.locator("html").get_attribute("data-tiles"), theme)
                        self.open(did)
                        self.assertEqual(page.locator("#sheet").evaluate("e => getComputedStyle(e).backdropFilter"), "none")
                        self.assertTrue(page.locator("#sheet").evaluate("e => e.scrollWidth <= e.clientWidth"))
                        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), w)
                        for selector in (".device-head h2", ".device-head p", ".device-power b", ".control-section > summary", "#bri-val"):
                            if page.locator(selector).count():
                                surface = ReadabilityTests.surface(self, selector)
                                self.assertEqual(surface["alpha"], 1)
                                self.assertGreaterEqual(surface["contrast"], 4.5, (selector, surface))
                        for control in page.locator("#sheet button, #sheet summary").all():
                            if control.is_visible():
                                self.assertGreaterEqual(control.bounding_box()["height"], 48)
                        self.assertTrue(page.locator(".device-head [data-close]").is_visible())
        self.assertEqual(self.commands, [])

    def test_light_slider_taps_cancel_and_close_send_nothing_then_release_sends_once(self):
        page = self.page
        self.open("lr-ceiling")
        page.wait_for_selector("#bri")
        before = page.inner_text("#bri-val")
        page.click("#bri")
        self.assertEqual(page.inner_text("#bri-val"), before)
        page.click("#ct")
        self.assertEqual(self.commands, [])
        for close in (False, True):
            slider = page.locator("#bri")
            box = slider.bounding_box()
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            page.mouse.move(x, y); page.mouse.down()
            page.mouse.move(x, y - 40, steps=6)
            self.assertEqual(self.commands, [])
            if close:
                page.keyboard.press("Escape")
                page.wait_for_selector("#sheet", state="hidden")
            else:
                slider.dispatch_event("pointercancel", {"pointerId": 1})
            page.mouse.up()
            self.assertEqual(self.commands, [])
        self.open("lr-ceiling")
        slider = page.locator("#bri")
        box = slider.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y); page.mouse.down()
        page.mouse.move(x, y + 35, steps=6)
        self.assertEqual(self.commands, [])
        page.mouse.up()
        page.wait_for_timeout(200)
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.commands[0]["action"], "brightness")
        self.assertTrue(slider.evaluate("e => e === document.activeElement"))

    def test_sections_and_keyboard_focus_survive_snapshots_and_reset_for_another_device(self):
        page = self.page
        self.open("lr-strip")
        self.assertFalse(page.locator('[data-control-section="scenes"]').evaluate("e => e.open"))
        summary = page.locator('[data-control-section="scenes"] > summary')
        summary.focus(); summary.press("Enter")
        page.wait_for_selector(".fx-search")
        page.evaluate("async () => (await import('/js/store.js')).reload()")
        self.assertTrue(page.locator('[data-control-section="scenes"]').evaluate("e => e.open"))
        self.assertTrue(summary.evaluate("e => e === document.activeElement"))
        self.open("lr-lamp")
        self.assertEqual(page.locator("#sheet .fx").count(), 0)
        close = page.locator(".device-head [data-close]")
        close.focus(); close.press("Shift+Tab")
        self.assertTrue(page.locator('#sheet [data-edit]').evaluate("e => e === document.activeElement"))
        page.keyboard.press("Tab")
        self.assertTrue(close.evaluate("e => e === document.activeElement"))
        self.assertEqual(self.commands, [])

    def test_unchanged_snapshots_keep_panel_nodes_and_rapid_reopen_cancels_close(self):
        page = self.page
        self.open("lr-tv")
        result = page.evaluate("""async () => {
          const sheet=document.querySelector('#sheet'), button=sheet.querySelector('[data-key="OK"]');
          button.focus(); let replaced=0;
          const observer=new MutationObserver(records=>{replaced+=records.length;});
          observer.observe(sheet,{childList:true});
          for(let i=0;i<8;i++) await (await import('/js/store.js')).reload();
          observer.disconnect();
          return {replaced, same:button===sheet.querySelector('[data-key="OK"]'), focused:document.activeElement===button};
        }""")
        self.assertEqual(result, {"replaced": 0, "same": True, "focused": True})
        page.evaluate("""async () => {
          const sheet=await import('/js/sheet.js');
          sheet.closeSheet(); sheet.openDevice('lr-lamp');
        }""")
        page.wait_for_timeout(300)
        self.assertTrue(page.locator("#sheet").is_visible())
        self.assertEqual(page.locator("#sheet").get_attribute("data-device-id"), "lr-lamp")
        self.assertEqual(self.commands, [])

    def test_offline_pairing_and_unknown_values_do_not_offer_unsafe_actions(self):
        page = self.page
        self.open("lr-lamp")
        for state, expected in (({"online": False, "error": "Device unavailable"}, "Try again"),
                                ({"needs_pairing": True}, "Pair now"), ({"online": True}, "Unknown")):
            with self.subTest(state=state):
                page.evaluate("""async state => {
                  const {store,upsertDevice} = await import('/js/store.js');
                  const device=store.devices.get('lr-lamp');
                  upsertDevice({...device,state});
                }""", state)
                self.assertIn(expected, page.locator("#sheet").inner_text())
                if state.get("online") is False or state.get("needs_pairing"):
                    self.assertEqual(page.locator("#sheet [data-power], #bri, #wheel").count(), 0)
                    self.assertNotIn("same Wi-Fi", page.locator("#sheet").inner_text())
                else:
                    self.assertTrue(page.locator("#sheet [data-power]").is_disabled())
                    self.assertEqual(page.locator("#bri").get_attribute("aria-disabled"), "true")
                    self.assertEqual(page.inner_text("#bri-val"), "Not reported")
        box = page.locator("#sheet [data-power]").bounding_box()
        page.touchscreen.tap(box["x"] + 20, box["y"] + 20)
        page.evaluate("""async () => {
          const {store,upsertDevice}=await import('/js/store.js'), d=store.devices.get('lr-lamp');
          upsertDevice({...d,state:{online:true,on:true,brightness:50}});
        }""")
        page.wait_for_selector('#sheet [data-power][aria-pressed="true"]:not([disabled])')
        self.assertEqual(self.commands, [])

    def test_music_sensitivity_and_remote_holds_cancel_without_commands(self):
        page = self.page
        self.open("lr-strip")
        page.click('[data-control-section="music"] > summary')
        slider = page.locator("[data-sensitivity]")
        original = slider.input_value()
        slider.click(position={"x": 20, "y": 24})
        self.assertEqual(slider.input_value(), original)
        self.assertEqual(self.commands, [])
        self.open("lr-tv")
        button = page.locator('[data-act="volume_up"]')
        box = button.bounding_box()
        page.mouse.move(box["x"] + 20, box["y"] + 20); page.mouse.down()
        page.mouse.move(box["x"] + 20, box["y"] + 100, steps=5)
        page.wait_for_timeout(600)
        page.keyboard.press("Escape"); page.mouse.up()
        self.assertEqual(self.commands, [])

    def test_search_blur_does_not_replace_a_scene_button_while_pressed(self):
        page = self.page
        self.open("lr-strip")
        page.click('[data-control-section="scenes"] > summary')
        page.fill(".fx-search", "sunset")
        button = page.locator('[data-effect="scene-sunset"]')
        button.evaluate("e => {window.pressedScene=e;}")
        box = button.bounding_box()
        page.mouse.move(box["x"] + 20, box["y"] + 20); page.mouse.down()
        page.evaluate("async () => (await import('/js/store.js')).reload()")
        self.assertTrue(button.evaluate("e => e === window.pressedScene"))
        page.mouse.up()
        page.wait_for_selector('[data-effect="scene-sunset"][aria-pressed="true"]')
        self.assertEqual(self.commands, [{"action": "set_effect", "value": "scene-sunset"}])
        page.fill(".fx-search", "sunrise")
        sunrise = page.locator('[data-effect="scene-sunrise"]')
        sunrise.scroll_into_view_if_needed()
        box = sunrise.bounding_box()
        page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_selector('[data-effect="scene-sunrise"][aria-pressed="true"]')
        self.assertEqual(self.commands[-1], {"action": "set_effect", "value": "scene-sunrise"})
        self.assertEqual(len(self.commands), 2)

    def test_brightness_only_capability_does_not_invent_power_or_color_controls(self):
        page = self.page
        self.open("lr-lamp")
        page.evaluate("""async () => {
          const {store,upsertDevice} = await import('/js/store.js');
          const device=store.devices.get('lr-lamp');
          upsertDevice({...device,caps:['brightness'],state:{online:true,brightness:45}});
        }""")
        self.assertEqual(page.locator("#sheet [data-power], #wheel, #ct").count(), 0)
        self.assertEqual(page.inner_text("#bri-val"), "45%")
        page.locator("#bri").press("Home")
        page.wait_for_timeout(200)
        self.assertEqual(self.commands, [{"action": "brightness", "value": 1}])

    def test_touch_light_drag_applies_only_on_release_and_failure_restores_state(self):
        page = self.page
        self.open("lr-ceiling")
        slider = page.locator("#bri")
        original = page.inner_text("#bri-val")
        box = slider.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        cdp = page.context.new_cdp_session(page)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        self.assertEqual(self.commands, [])
        self.assertEqual(page.inner_text("#bri-val"), original)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y + 30}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchCancel", "touchPoints": []})
        self.assertEqual(self.commands, [])
        self.assertEqual(page.inner_text("#bri-val"), original)
        page.route("**/devices/lr-ceiling/command", lambda route: route.fulfill(
            status=400, json={"error": "The light is busy. Try again."}))
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y + 30}]})
        self.assertEqual(self.commands, [])
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_selector("text=The light is busy. Try again.")
        page.wait_for_function("(value) => document.querySelector('#bri-val').textContent === value", arg=original)
        self.assertEqual(len(self.commands), 1)

    def test_map_and_energy_failures_are_explicit_without_device_commands(self):
        page = self.page
        page.route("**/map*", lambda route: route.fulfill(status=503, body="Unavailable"))
        self.open("lr-vacuum")
        page.wait_for_selector(".vac-map.empty")
        self.assertIn("Map unavailable", page.locator(".vac-map").inner_text())
        page.route("**/energy?*", lambda route: route.fulfill(status=503, json={"error": "Energy history unavailable."}))
        self.open("kt-fridge")
        page.wait_for_selector("[data-energy-refresh]")
        self.assertIn("Energy history unavailable.", page.locator("#energy").inner_text())
        page.unroute("**/energy?*")
        page.click("[data-energy-refresh]")
        page.wait_for_selector("#energy .bars")
        page.route("**/energy?*", lambda route: route.fulfill(status=503, json={"error": "Energy history unavailable."}))
        page.evaluate("""async () => {
          const now = Date.now; Date.now = () => now() + 61000;
          (await import('/js/sheet.js')).refreshSheet();
        }""")
        page.wait_for_selector("[data-energy-refresh]")
        self.assertIn("Showing the last available history.", page.locator("#energy").inner_text())
        self.assertTrue(page.locator("#energy .bars").is_visible())
        self.assertEqual(self.commands, [])
