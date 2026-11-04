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

    def test_brightness_pill(self):
        # Ceiling light starts at 80%. Dragging the pill down by half its height dims it to 30%;
        # a tap without dragging switches it off and on.
        self.tile("lr-ceiling").locator("[data-more]").click()
        box = self.page.locator("#bri").bounding_box()
        self.assertGreater(box["height"], box["width"])                 # a tall, vertical pill
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.4
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        for i in range(1, 11):
            self.page.mouse.move(x, y + box["height"] * 0.05 * i)
        self.page.mouse.up()
        self.page.wait_for_function("document.querySelector('#bri-val').textContent === '30%'")
        self.page.wait_for_function(
            "document.querySelector('.tile[data-id=\"lr-ceiling\"] .tile-status').textContent === 'On, 30%'")
        self.page.locator("#bri").click()                                # tap = off
        self.page.wait_for_function("document.querySelector('#bri-val').textContent === 'Off'")
        self.page.wait_for_function("!document.querySelector('.tile[data-id=\"lr-ceiling\"]').classList.contains('on')")
        self.page.locator("#bri").click()                                # tap again = back on
        self.page.wait_for_function("document.querySelector('#bri-val').textContent === '30%'")
        # this light has white temperature only: a warm-to-cool pill, no color wheel
        self.assertEqual(self.page.locator("#sheet #wheel").count(), 0)
        ct = self.page.locator("#sheet #ct").bounding_box()
        self.page.mouse.click(ct["x"] + ct["width"] / 2, ct["y"] + 4)  # top = coolest
        self.page.wait_for_function("document.querySelector('#sheet #ct').getAttribute('aria-valuenow') > 6000")

    def test_light_color_wheel_and_presets(self):
        self.tile("lr-lamp").locator("[data-more]").click()
        wheel = self.page.locator("#sheet #wheel")
        box = wheel.bounding_box()
        self.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + 3)    # top edge of the wheel = red
        self.page.wait_for_function("document.querySelector('#sheet #wheel').getAttribute('aria-valuetext') === '#ff0000'")
        self.page.wait_for_function("(() => { const s = document.querySelector('.tile[data-id=\"lr-lamp\"]').style"
                                    ".getPropertyValue('--glow'); return s.trim() === '255 0 0'; })()")
        self.page.click('#sheet [data-color="#5ee07a"]')
        self.page.wait_for_selector('#sheet [data-color="#5ee07a"][aria-pressed="true"]')
        # white strip: tapping the warm end switches back to white light
        strip = self.page.locator("#sheet .temp-strip").bounding_box()
        self.page.mouse.click(strip["x"] + 6, strip["y"] + strip["height"] / 2)
        self.page.wait_for_function("document.querySelector('#sheet .temp-strip').getAttribute('aria-valuenow') < 2400")
        self.page.wait_for_selector("#sheet .wheel-thumb.idle")
        self.page.wait_for_timeout(1800)                                   # let the follow-up refresh settle
        heights = self.page.evaluate("['#bri', '#wheel', '.temp-strip', '.swatch'].map("
                                     "s => document.querySelector('#sheet ' + s).getBoundingClientRect().height)")
        self.assertTrue(all(h >= 48 for h in heights), heights)

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
        self.page.wait_for_selector("#sheet [data-clean-rooms] >> text=Clean 2 rooms")
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

    # ---------- TV remote ----------
    def commands(self):
        """Collect the commands the page sends: [(action, value), …]."""
        import json
        sent = []
        def on_request(r):
            if r.method == "POST" and r.url.endswith("/command"):
                body = json.loads(r.post_data or "{}")
                sent.append((body.get("action"), body.get("value")))
        self.page.on("request", on_request)
        return sent

    def open_tv(self, did):
        self.tile(did).locator("[data-more]").click()
        self.page.wait_for_selector("#sheet:not([hidden]) .remote-top")
        if self.page.locator("#sheet .tv-off").count():
            self.page.click("#sheet .tv-off [data-power]")
        self.page.wait_for_selector("#sheet .remote")

    def test_remote_layout_and_modes(self):
        sent = self.commands()
        self.open_tv("lr-tv")                       # demo "Samsung TV": no pointer
        top = self.page.locator("#sheet .remote-top")
        self.assertEqual(top.locator("[data-power]").count(), 1)
        self.assertIn("Samsung TV", top.locator(".tv-pill").inner_text())
        self.assertEqual(top.locator("[data-mute]").count(), 1)
        for key in ("MENU", "SOURCE", "EXIT", "CHANNEL_LIST", "UP", "OK", "HOME", "BACK"):
            self.assertEqual(self.page.locator(f'#sheet [data-key="{key}"]').count(), 1, key)
        self.assertEqual(self.page.locator("#sheet [data-mode=touchpad]").count(), 0)   # only when the TV has a pointer
        self.page.click('#sheet [data-key="OK"]')
        self.page.click('#sheet [data-act="volume_up"]')
        self.page.click("#sheet [data-mode=numbers]")
        self.page.wait_for_selector("#sheet .numpad")
        self.assertEqual(self.page.locator("#sheet .numpad .num").count(), 12)
        self.page.click('#sheet .numpad [data-key="7"]')
        self.page.wait_for_function("document.querySelector('#sheet [data-mode=numbers]').getAttribute('aria-pressed') === 'true'")
        self.page.click("#sheet [data-mode=dpad]")
        self.page.wait_for_selector("#sheet .dpad")
        self.page.click("#sheet [data-app]:not([aria-pressed=true]) >> nth=0")
        self.page.wait_for_function("() => true")
        self.page.wait_for_timeout(300)
        actions = [a for a in sent]
        self.assertIn(("key", "OK"), actions)
        self.assertIn(("volume_up", None), actions)
        self.assertIn(("key", "7"), actions)
        self.assertTrue(any(a == "launch_app" for a, _ in actions))
        for sel in ("[data-key=MENU]", "[data-key=UP]", "[data-act=volume_up]", "[data-mode=dpad]", "[data-app]"):
            box = self.page.locator(f"#sheet {sel}").first.bounding_box()
            self.assertGreaterEqual(min(box["width"], box["height"]), 48, sel)

    def test_remote_fits_a_phone_without_scrolling(self):
        self.page.set_viewport_size({"width": 393, "height": 852})
        self.open_tv("lr-tv")
        self.page.wait_for_timeout(350)               # sheet animation
        fits = self.page.evaluate("(() => { const s = document.querySelector('#sheet');"
                                  " return s.scrollHeight <= s.clientHeight + 1 && s.getBoundingClientRect().top >= 0; })()")
        self.assertTrue(fits)
        width = self.page.evaluate("document.querySelector('#sheet').scrollWidth <= 393")
        self.assertTrue(width)

    def test_touchpad_moves_clicks_and_scrolls_the_pointer(self):
        sent = self.commands()
        self.open_tv("bd-tv")                       # demo "LG TV" has a pointer
        self.page.click("#sheet [data-mode=touchpad]")
        pad = self.page.locator("#sheet #touchpad")
        pad.wait_for()
        box = pad.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        for i in range(1, 16):
            self.page.mouse.move(x + i * 6, y - i * 2)
            self.page.wait_for_timeout(10)
        self.page.mouse.up()
        self.page.wait_for_timeout(200)
        moves = [v for a, v in sent if a == "pointer" and "dx" in v]
        self.assertTrue(moves)
        self.assertLess(len(moves), 15)                                  # batched, not one per finger move
        self.assertGreater(sum(m["dx"] for m in moves), 90)              # moved right (with acceleration) …
        self.assertLess(sum(m["dy"] for m in moves), 0)                  # … and up
        self.page.mouse.click(x, y)                                      # tap = click
        self.page.wait_for_timeout(200)
        self.assertIn(("pointer", {"click": True}), sent)
        clicks = sent.count(("pointer", {"click": True}))
        # two fingers dragging up scroll the page down
        pad.evaluate("""el => {
            const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
            const ev = (type, id, dy) => el.dispatchEvent(new PointerEvent(type, {
                pointerId: id, clientX: x + id * 20, clientY: y + dy, bubbles: true, pointerType: "touch" }));
            ev("pointerdown", 1, 0); ev("pointerdown", 2, 0);
            for (let i = 1; i <= 6; i++) { ev("pointermove", 1, -i * 10); ev("pointermove", 2, -i * 10); }
            ev("pointerup", 1, -60); ev("pointerup", 2, -60);
        }""")
        self.page.wait_for_timeout(250)
        scrolls = [v["scroll"] for a, v in sent if a == "pointer" and "scroll" in v]
        self.assertTrue(scrolls and sum(scrolls) > 0)
        self.assertEqual(sent.count(("pointer", {"click": True})), clicks)   # a scroll isn't a click
        self.page.click("#sheet [data-mode=dpad]")                       # leave the TV in D-pad mode
        self.page.wait_for_selector("#sheet .dpad")

    # ---------- robot vacuum ----------
    def test_robot_vacuum_options_and_maintenance(self):
        self.page.set_viewport_size({"width": 393, "height": 852})
        self.tile("lr-vacuum").click()
        self.page.wait_for_selector("#sheet .vac")
        opts = self.page.locator("#sheet .opts")
        self.assertIn("Suction", opts.inner_text())
        self.assertIn("Mode", opts.inner_text())
        self.assertIn("Station", opts.inner_text())
        self.assertEqual(opts.locator("[data-clean-mode] svg").count(), 3)          # every mode has an icon
        self.page.click('#sheet [data-clean-mode="mop"]')
        self.page.wait_for_selector('#sheet [data-clean-mode="mop"][aria-pressed="true"]')
        self.page.click('#sheet [data-clean-mode="vacuum"]')
        self.page.wait_for_selector('#sheet [data-clean-mode="vacuum"][aria-pressed="true"]')
        self.page.click('#sheet [data-station="empty_dustbin"]')
        self.page.wait_for_selector("text=Empty dustbin: sent to the station")
        # parts wear stays folded behind one Maintenance row
        part = self.page.locator("#sheet .vac-parts .part").first
        self.assertFalse(part.is_visible())
        self.assertIn("Filter", self.page.locator("#sheet .maint-row").inner_text())
        self.page.click("#sheet .maint-row")
        part.wait_for(state="visible")
        # picking rooms turns the main button into "Clean 1 room"; Clear undoes it
        self.page.click('#sheet [data-room-pick="2"]')
        self.page.wait_for_selector("#sheet .vac-main >> text=Clean 1 room")
        self.page.click("#sheet [data-rooms-clear]")
        self.page.wait_for_selector("#sheet .vac-main >> text=Start cleaning")
        for sel in (".vac-main", "[data-locate]", '[data-suction="max"]', '[data-clean-mode="mop"]', ".maint-row"):
            self.assertGreaterEqual(self.page.locator(f"#sheet {sel}").bounding_box()["height"], 48, sel)
        no_overflow = self.page.evaluate("document.querySelector('#sheet').scrollWidth <= 393")
        self.assertTrue(no_overflow)


if __name__ == "__main__":
    unittest.main()
