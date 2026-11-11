"""Speaker controls against isolated fixture devices, never real hardware."""
import copy
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
class SpeakerControlTests(unittest.TestCase):
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
        cls.original_meta = copy.deepcopy(cls.server.app.state.service.store.devices["lr-soundbar"].meta)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        svc = self.server.app.state.service
        state = {"on": True, "muted": False, "volume": 12, "input": "arc", "sound_mode": "ai"}
        svc.adapters["demo"]._state["lr-soundbar"] = dict(state)
        device = svc.store.devices["lr-soundbar"]
        device.state = {**state, "online": True}
        device.meta = {**copy.deepcopy(self.original_meta), "sound_modes": [
            *self.original_meta["sound_modes"],
            {"id": "26", "name": "Device-reported mode 26", "advanced": True},
            {"id": "15", "name": "Dolby Atmos", "advanced": True},
        ]}
        self.errors, self.commands = [], []
        self.page = self.browser.new_page(viewport={"width": 720, "height": 1280}, has_touch=True, reduced_motion="reduce")
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("request", self.record)
        self.page.add_init_script("localStorage.setItem('view',JSON.stringify('rooms'))")
        self.page.goto(self.server.url)
        self.page.wait_for_selector('.tile[data-id="lr-soundbar"] [data-more]')
        self.page.click('.tile[data-id="lr-soundbar"] [data-more]')
        self.page.wait_for_selector('#sheet[data-kind="speaker"] [data-speaker-volume]')

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def record(self, request):
        if request.method == "POST" and request.url.endswith("/devices/lr-soundbar/command"):
            self.commands.append(request.post_data_json)

    def value(self):
        return int(self.page.locator("[data-speaker-volume]").input_value())

    def test_relative_volume_drag_does_not_jump_on_tap_or_poll_and_cancel_does_not_send(self):
        page = self.page
        slider = page.locator("[data-speaker-volume]")
        box = slider.bounding_box()
        page.mouse.click(box["x"] + box["width"] * .8, box["y"] + box["height"] / 2)
        self.assertEqual(self.value(), 12)
        self.assertEqual(self.commands, [])
        box = slider.bounding_box()
        x, y = box["x"] + box["width"] * .3, box["y"] + box["height"] / 2
        page.mouse.move(x, y); page.mouse.down()
        page.mouse.move(x + box["width"] * .2, y, steps=8)
        self.assertEqual(self.commands, [])  # release to apply
        page.evaluate("""async () => {
          window.heldVolume = document.querySelector('[data-speaker-volume]');
          const {store,upsertDevice} = await import('/js/store.js');
          const d = store.devices.get('lr-soundbar');
          upsertDevice({...d,state:{...d.state,volume:90}});
        }""")
        self.assertTrue(slider.evaluate("e => e === window.heldVolume"))
        self.assertEqual(self.value(), 32)
        page.mouse.up()
        page.wait_for_function("document.querySelector('[data-speaker-volume]').value === '32'")
        page.wait_for_timeout(200)
        self.assertEqual(self.commands, [{"action": "volume", "value": 32}])
        box = slider.bounding_box()
        page.mouse.move(box["x"] + 30, box["y"] + 25); page.mouse.down()
        page.mouse.move(box["x"] + 90, box["y"] + 25, steps=6)
        slider.dispatch_event("pointercancel", {"pointerId": 1})
        page.mouse.up()
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.value(), 32)
        slider.focus(); slider.press("ArrowRight")
        page.wait_for_function("document.querySelector('[data-speaker-volume]').value === '33'")
        page.wait_for_timeout(200)
        self.assertEqual(self.commands[-1], {"action": "volume", "value": 33})

    def test_switch_mute_and_chip_choices_reconcile(self):
        page = self.page
        self.assertEqual(page.inner_text("[data-speaker-level]"), "12")
        self.assertEqual(page.locator("#sheet .dial").evaluate("e => e.style.getPropertyValue('--pct')"), "12")
        self.assertEqual(page.locator("#sheet [data-tab]").all_inner_texts(), ["Input", "Sound mode"])
        power = page.locator('#sheet .panel-head [data-power][role="switch"]')
        self.assertEqual(power.get_attribute("aria-checked"), "true")
        page.click('#sheet [data-input="bt"]')                                      # inputs are chips on the first tab
        page.wait_for_selector('#sheet [data-input="bt"][aria-pressed="true"]')
        self.assertEqual(self.commands[-1], {"action": "set_input", "value": "bt"})
        page.click('#sheet [data-tab="sound"]')
        named = page.locator("#sheet .pane-set .chips").nth(0)
        reported = page.locator("#sheet .pane-set .chips").nth(1)
        self.assertEqual(named.locator('[data-sound-mode="26"], [data-sound-mode="15"]').count(), 0)   # numbered modes are kept apart
        self.assertIn("ID 26", reported.locator('[data-sound-mode="26"]').inner_text())
        reported.locator('[data-sound-mode="26"]').click()
        page.wait_for_selector('#sheet [data-sound-mode="26"][aria-pressed="true"]')
        self.assertEqual(self.commands[-1], {"action": "set_sound_mode", "value": "26"})
        self.assertEqual(page.locator('#sheet [data-sound-mode][aria-pressed="true"]').count(), 1)
        page.click("#sheet [data-mute]")
        page.wait_for_selector('#sheet [data-mute][aria-pressed="true"]')
        self.assertIn("Unmute", page.inner_text("#sheet [data-mute]"))
        self.assertIn("Muted", page.inner_text("#sheet .dial-core"))
        self.assertIn("Muted", page.inner_text("#sheet .panel-head p"))
        power.click()
        page.wait_for_selector('#sheet [data-power][aria-checked="false"]')
        self.assertTrue(page.locator("[data-speaker-volume]").is_disabled())
        self.assertTrue(page.locator('#sheet [data-sound-mode="26"]').is_disabled())
        self.assertIn("Turn it on to change the volume", page.inner_text("#sheet .speaker-stage"))
        page.click("#sheet .panel-head [data-close]")
        page.wait_for_selector("#sheet", state="hidden")

    def test_touch_volume_applies_once_on_release_and_tap_does_not_jump(self):
        page = self.page
        cdp = page.context.new_cdp_session(page)
        box = page.locator("[data-speaker-volume]").bounding_box()
        x, y = box["x"] + box["width"] * .8, box["y"] + box["height"] / 2
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        self.assertEqual(self.value(), 12)
        self.assertEqual(self.commands, [])
        box = page.locator("[data-speaker-volume]").bounding_box()
        x, y = box["x"] + box["width"] * .25, box["y"] + box["height"] / 2
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        for step in range(1, 7):
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [
                {"x": x + box["width"] * .15 * step / 6, "y": y}]})
        self.assertEqual(self.commands, [])
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_timeout(250)
        self.assertEqual(self.commands, [{"action": "volume", "value": 27}])
        self.assertEqual(self.value(), 27)

    def test_failed_volume_command_restores_reported_level_and_shows_error(self):
        self.page.route("**/api/v1/devices/lr-soundbar/command",
                        lambda route: route.fulfill(status=400, json={"error": "The speaker is busy. Try again."}))
        slider = self.page.locator("[data-speaker-volume]")
        slider.focus(); slider.press("ArrowRight")
        self.page.wait_for_selector("text=The speaker is busy. Try again.")
        self.page.wait_for_function("document.querySelector('[data-speaker-volume]').value === '12'")

    def test_panel_is_opaque_and_readable_at_all_sizes_and_glass_settings(self):
        from tests.integration.test_readability import ReadabilityTests
        page = self.page
        for style in ("light", "dark"):
            for size, width, height, transparency in (("small", 393, 852, 100), ("medium", 720, 1280, 0), ("large", 1280, 720, 100)):
                with self.subTest(style=style, size=size):
                    page.set_viewport_size({"width": width, "height": height})
                    page.evaluate("""async s => {
                      await (await import('/js/api.js')).api.saveSettings(s);
                      await (await import('/js/store.js')).reload();
                    }""", {"tile_style": style, "font_size": size, "glass_effect": False, "glass_transparency": transparency})
                    sheet = page.locator("#sheet")
                    self.assertTrue(sheet.evaluate("e => e.scrollWidth <= e.clientWidth"))
                    self.assertEqual(sheet.evaluate("e => getComputedStyle(e).backdropFilter"), "none")
                    for selector in (".panel-head h2", ".panel-head p", ".dial-core span", "[data-speaker-level]", ".pane-help",
                                     '.panel-tabs [aria-selected="true"]', '.panel-tabs [aria-selected="false"]', ".chip span"):
                        if not page.locator(selector).count():
                            continue
                        surface = ReadabilityTests.surface(self, selector)
                        self.assertEqual(surface["alpha"], 1)
                        self.assertGreaterEqual(surface["contrast"], 4.5, (selector, surface))
                    for control in page.locator("#sheet button, [data-speaker-volume]").all():
                        if control.is_visible():
                            self.assertGreaterEqual(control.bounding_box()["height"], 48)
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
        self.assertEqual(self.commands, [])
