"""Integration tests for the touch UI in a real browser (skipped unless Playwright is installed).

    pip install playwright && playwright install chromium
"""
import json
import os
import shutil
import tempfile
import unittest
import urllib.request

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    if os.environ.get("REQUIRE_UI_TESTS"):   # CI sets this so UI tests can never be skipped silently
        raise
    sync_playwright = None

from tests.helpers import IPAPI_SEATTLE, REVERSE_SEATTLE, DemoServer, FakeJsonServer, FakeWeatherSource


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
        self.errors = []
        self.page = self.open(view="rooms")     # most tests work with device tiles; Home has its own tests
        self.page.wait_for_selector(".tile")

    def open(self, width=720, height=1280, view=None, room=None, **kw):
        """A new page (a new screen: its own remembered view and room)."""
        page = self.browser.new_page(viewport={"width": width, "height": height}, has_touch=True, **kw)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        if view or room:
            page.add_init_script("".join(f"localStorage.setItem({k!r}, JSON.stringify({v!r}));"
                                         for k, v in (("view", view), ("room", room)) if v is not None))
        page.goto(f"http://127.0.0.1:{self.port}/")
        return page

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def tile(self, did):
        return self.page.locator(f'.tile[data-id="{did}"]')

    def sheet_settled(self):
        """Wait until the device sheet has finished sliding in (positions are final)."""
        self.page.wait_for_function("(() => { const s = document.querySelector('#sheet');"
                                    " return s && !s.hidden && s.getAnimations().every(a => a.playState !== 'running'); })()")

    def test_tile_opens_controls_and_explicit_power_toggles_plug(self):
        self.page.wait_for_function("document.querySelector('.tile[data-id=\"kt-kettle\"] .tile-status').textContent === 'Off'")
        self.tile("kt-kettle").locator(".tile-name").click()
        self.page.wait_for_selector('#sheet[data-device-id="kt-kettle"]:not([hidden])')
        self.assertFalse(self.tile("kt-kettle").evaluate("el=>el.classList.contains('on')"))
        self.page.click("#sheet [data-close]")
        self.page.wait_for_selector("#sheet", state="hidden")
        self.tile("kt-kettle").locator('[data-quick-action="power"]').click()
        self.page.wait_for_function("document.querySelector('.tile[data-id=\"kt-kettle\"]').classList.contains('on')")

    def test_tv_tap_opens_remote_not_power(self):
        self.tile("lr-tv").locator(".tile-name").click()
        self.page.wait_for_selector(".dpad")
        self.assertTrue(self.tile("lr-tv").evaluate("el => el.classList.contains('on')"))

    def test_sound_bar_opens_media_controls_and_picks_sound_mode(self):
        self.page.wait_for_selector('.tile[data-id="lr-soundbar"].wide')
        self.tile("lr-soundbar").locator(".tile-name").click()
        self.page.click('[data-control-section="speaker-options"] > summary')
        self.page.wait_for_selector('[data-speaker-select="set_sound_mode"]')
        self.assertTrue(self.tile("lr-soundbar").evaluate("el => el.classList.contains('on')"))  # tap didn't turn it off
        self.assertEqual(self.page.locator(".dpad").count(), 0)       # no TV remote for a speaker
        self.assertTrue(self.page.locator('[data-speaker-select="set_input"]').is_visible())
        self.page.select_option('[data-speaker-select="set_sound_mode"]', "cinema")
        self.page.wait_for_function("document.querySelector('[data-speaker-select=\"set_sound_mode\"]').value === 'cinema'")
        box = self.page.locator('[data-speaker-select="set_sound_mode"]').bounding_box()
        self.assertGreaterEqual(box["height"], 48)
        # A labeled speaker panel, without TV keys or touchpad.
        sheet = self.page.locator("#sheet")
        for sel in (".speaker-controls [data-power]", ".speaker-controls [data-mute]", '.speaker-volume [data-act="volume_up"]'):
            self.assertEqual(sheet.locator(sel).count(), 1, sel)
        for sel in ("[data-mode]", "#touchpad", "[data-key]", "[data-app]"):
            self.assertEqual(sheet.locator(sel).count(), 0, sel)
        self.page.select_option('#sheet [data-speaker-select="set_input"]', "bt")
        self.page.wait_for_function("document.querySelector('[data-speaker-select=\"set_input\"]').value === 'bt'")

    def test_brightness_pill(self):
        # Brightness applies on release; power now has its own explicit button.
        self.tile("lr-ceiling").locator("[data-more]").click()
        self.sheet_settled()
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
        self.page.locator("#bri").click()
        self.assertEqual(self.page.inner_text("#bri-val"), "30%")
        self.page.locator("#sheet [data-power]").click()
        self.page.wait_for_function("document.querySelector('#bri-val').textContent === 'Off'")
        self.page.wait_for_function("!document.querySelector('.tile[data-id=\"lr-ceiling\"]').classList.contains('on')")
        self.page.locator("#sheet [data-power]").click()
        self.page.wait_for_function("document.querySelector('#bri-val').textContent === '30%'")
        # this light has white temperature only: a warm-to-cool pill, no color wheel
        self.assertEqual(self.page.locator("#sheet #wheel").count(), 0)
        self.page.click('[data-control-section="light-color"] > summary')
        ct = self.page.locator("#sheet #ct")
        ct.focus()
        ct.press("End")
        for _ in range(15):
            ct.press("ArrowUp")
        self.page.wait_for_function("document.querySelector('#sheet #ct').getAttribute('aria-valuenow') > 6000")

    def test_light_color_wheel_and_presets(self):
        self.tile("lr-lamp").locator("[data-more]").click()
        self.page.click('[data-control-section="light-color"] > summary')
        # Locator clicks wait for the sheet to finish sliding in, so the spot is where we mean it.
        wheel = self.page.locator("#sheet #wheel")
        wheel.click(position={"x": wheel.bounding_box()["width"] / 2, "y": 3})   # top edge of the wheel = red
        self.page.wait_for_function("document.querySelector('#sheet #wheel').getAttribute('aria-valuetext') === '#ff0000'")
        self.page.wait_for_function("(() => { const s = document.querySelector('.tile[data-id=\"lr-lamp\"]').style"
                                    ".getPropertyValue('--glow'); return s.trim() === '255 0 0'; })()")
        self.page.click('#sheet [data-color="#5ee07a"]')
        self.page.wait_for_selector('#sheet [data-color="#5ee07a"][aria-pressed="true"]')
        # White presets are explicit choices; a slider track tap cannot jump.
        self.page.click('#sheet [data-kelvin="2700"]')
        self.page.locator("#sheet .temp-strip").focus()
        self.page.locator("#sheet .temp-strip").press("ArrowLeft")
        self.page.locator("#sheet .temp-strip").press("ArrowLeft")
        self.page.wait_for_function("document.querySelector('#sheet .temp-strip').getAttribute('aria-valuenow') < 2400")
        self.page.wait_for_selector("#sheet .wheel-thumb.idle")
        self.page.wait_for_timeout(1800)                                   # the follow-up refresh keeps white
        self.assertEqual(self.page.locator("#sheet .wheel-thumb.idle").count(), 1)
        heights = self.page.evaluate("['#bri', '#wheel', '.temp-strip', '.swatch'].map("
                                     "s => document.querySelector('#sheet ' + s).getBoundingClientRect().height)")
        self.assertTrue(all(h >= 48 for h in heights), heights)

    def test_light_effects_pick_a_scene_music_and_strip_parts(self):
        self.tile("lr-strip").locator("[data-more]").click()
        sheet = self.page.locator("#sheet")
        self.page.click('[data-control-section="scenes"] > summary')
        self.page.wait_for_selector("#sheet:not([hidden]) [data-effect]")
        # search narrows the chips without redrawing the sheet, then a tap picks the scene
        self.page.fill("#sheet .fx-search", "sun")
        self.assertEqual(sheet.locator("[data-effect]:visible").count(), 2)          # Sunrise, Sunset
        self.page.fill("#sheet .fx-search", "zzz")
        self.page.wait_for_selector("#sheet .fx-none:visible")
        self.page.fill("#sheet .fx-search", "sunset")
        self.page.click('#sheet [data-effect="scene-sunset"]')
        self.page.wait_for_selector('#sheet [data-effect="scene-sunset"][aria-pressed="true"]')
        self.page.wait_for_function(
            "document.querySelector('.tile[data-id=\"lr-strip\"] .tile-status').textContent.startsWith('Sunset')")
        self.assertEqual(self.page.input_value("#sheet .fx-search"), "sunset")     # kept across the redraw
        self.assertEqual(sheet.locator(".fx-group-name").all_text_contents(), ["Scenes", "DIY", "Snapshots"])
        self.assertEqual(sheet.locator("[data-fx-group]:visible").count(), 1)     # only the group with a match
        # music: pick a mode; the scene is no longer the active one
        self.page.click('[data-control-section="music"] > summary')
        self.page.click('#sheet [data-music-mode="spectrum"]')
        self.page.wait_for_selector('#sheet [data-music-mode="spectrum"][aria-pressed="true"]')
        self.assertEqual(sheet.locator('[data-effect][aria-pressed="true"]').count(), 0)
        # strip parts: a color first asks for parts; tap two parts, then a color
        self.page.click('[data-control-section="segments"] > summary')
        self.page.click('#sheet [data-seg-color="#4f7bff"]')
        self.page.wait_for_selector("#toast:not([hidden])")
        self.assertIn("Tap the parts", self.page.inner_text("#toast"))
        self.page.click('#sheet [data-seg="0"]')
        self.page.click('#sheet [data-seg="3"]')
        self.page.click('#sheet [data-seg-color="#4f7bff"]')
        self.page.wait_for_selector('#sheet [data-seg="3"].lit')
        self.assertEqual(sheet.locator(".seg-part.lit").count(), 2)
        # a toggle switches and stays switched after the follow-up refresh
        self.page.click('[data-control-section="light-options"] > summary')
        pressed = self.page.get_attribute('#sheet [data-toggle="sync"]', "aria-pressed")
        self.page.click('#sheet [data-toggle="sync"]')
        want = "false" if pressed == "true" else "true"
        self.page.wait_for_selector(f'#sheet [data-toggle="sync"][aria-pressed="{want}"]')
        self.page.wait_for_timeout(1800)
        self.assertEqual(self.page.get_attribute('#sheet [data-toggle="sync"]', "aria-pressed"), want)
        # touch targets: every effect control is at least 48 px tall (links aside)
        small = self.page.evaluate("""[...document.querySelectorAll('#sheet .fx button, #sheet .fx input')]
            .filter(e => e.offsetParent && !e.classList.contains('link'))
            .map(e => e.getBoundingClientRect()).filter(r => r.height < 44 || r.width < 48).length""")
        self.assertEqual(small, 0)

    def test_light_effects_fit_phone_tablet_and_panel(self):
        for w, h in ((393, 852), (820, 1180), (1280, 720)):
            page = self.open(width=w, height=h, view="rooms")
            page.locator('.tile[data-id="lr-strip"] [data-more]').click()
            page.click('[data-control-section="segments"] > summary')
            page.wait_for_selector("#sheet:not([hidden]) [data-seg]")
            wide = page.evaluate("document.documentElement.scrollWidth > innerWidth"
                                 " || document.querySelector('#sheet').scrollWidth > document.querySelector('#sheet').clientWidth")
            self.assertFalse(wide, (w, h))
            # lights without effects don't get the sections
            page.click("#sheet [data-close]")
            page.locator('.tile[data-id="lr-lamp"] [data-more]').click()
            page.click('[data-control-section="light-color"] > summary')
            page.wait_for_selector("#sheet:not([hidden]) #wheel")
            self.assertEqual(page.locator("#sheet .fx").count(), 0)
            page.close()

    def test_add_room_and_open_add_flow(self):
        original = self.page.request.get(self.server.url + "/api/v1/state").json()["rooms"]
        try:
            self.page.click("#open-settings")
            self.page.click("[data-go=rooms]")
            self.page.click("#settings [data-edit-rooms]")
            self.page.fill("input[name=room]", "Office")
            self.page.click("[data-room-add] button[type=submit]")
            self.page.wait_for_selector('#settings [data-room-name="Office"]')
            self.page.click("[data-back]")
            self.page.click("[data-go=add]")
            self.page.wait_for_selector("text=Shelly")
        finally:
            self.page.request.put(self.server.url + "/api/v1/rooms", data={"rooms": original})

    def test_weather_data_attribution_is_visible_in_location_settings(self):
        self.page.click("#open-settings")
        self.page.click('[data-go="location"]')
        source = self.page.locator('#settings a[href="https://open-meteo.com/"]')
        self.assertTrue(source.is_visible())
        self.assertEqual(source.get_attribute("rel"), "noopener")
        self.assertTrue(self.page.locator('#settings a[href="https://creativecommons.org/licenses/by/4.0/"]').is_visible())

    def test_sidebar_adds_empty_rooms_and_reorders_with_accessible_controls(self):
        page = self.page
        page.set_viewport_size({"width": 1280, "height": 720})
        original = page.request.get(self.server.url + "/api/v1/state").json()
        try:
            page.click("#rail [data-edit-rooms]")
            page.click("#rail [data-add-room]")
            page.fill("#rail [data-room-add] input", "  Empty office  ")
            page.click("#rail [data-room-add] button[type=submit]")
            page.wait_for_selector('#rail [data-room-name="Empty office"]')
            page.wait_for_selector('#title:text-is("Empty office")')
            self.assertTrue(page.locator(".room-empty").is_visible())
            self.assertEqual(page.locator("#grid .tile").count(), 0)
            self.assertEqual(page.locator("[data-arrange-rooms], [data-room-step], [data-room-move]").count(), 0)
            page.locator('#rail [data-room-grip="Empty office"]').focus()
            page.keyboard.press("ArrowUp")
            page.wait_for_selector("text=Room order saved")
            expected = ["Living room", "Bedroom", "Empty office", "Kitchen"]
            self.assertEqual(page.request.get(self.server.url + "/api/v1/state").json()["rooms"], expected)
            self.assertEqual(page.locator('#rail [data-room="all"]').count(), 1)
            self.assertEqual(page.locator('#rail [data-room-grip="all"], #rail [data-room-grip=""]').count(), 0)
            self.assertIn("Empty office moved to position 3", page.inner_text("#room-sort-status"))
            for button in page.locator("#rail [data-room-grip]").all():
                self.assertGreaterEqual(button.bounding_box()["width"], 48)
                self.assertGreaterEqual(button.bounding_box()["height"], 48)
            page.reload()
            page.wait_for_selector('#rail [data-room="Empty office"]')
            self.assertEqual(page.locator("[data-room-grip]").count(), 0)
            self.assertEqual(page.eval_on_selector_all("#rail [data-room]", "els => els.map(e => e.dataset.room)"),
                             ["all", *expected])
            page.click('#rail [data-nav="home"]')
            self.assertEqual(page.eval_on_selector_all("[data-go-room]", "els => els.map(e => e.dataset.goRoom)"), expected)
            page.set_viewport_size({"width": 393, "height": 852})
            page.click('#dock [data-nav="rooms"]')
            page.click("#room-tools [data-edit-rooms]")
            self.assertTrue(page.locator("#room-tools [data-add-room]").is_visible())
            page.click("#room-tools [data-add-room]")
            page.wait_for_selector("#room-tools [data-room-add] input:focus")
            page.fill("#room-tools [data-room-add] input", "Empty office")
            page.click("#room-tools [data-room-add] button[type=submit]")
            page.wait_for_selector("text=That room already exists.")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 393)
            saved = page.request.get(self.server.url + "/api/v1/state").json()
            self.assertEqual({d["id"]: d["room"] for d in saved["devices"]},
                             {d["id"]: d["room"] for d in original["devices"]})
            self.assertEqual(saved["settings"]["home_layout"], original["settings"]["home_layout"])
        finally:
            page.request.put(self.server.url + "/api/v1/rooms", data={"rooms": original["rooms"]})

    def test_room_grips_support_mouse_touch_and_normal_navigation(self):
        page = self.page
        original = page.request.get(self.server.url + "/api/v1/state").json()["rooms"]
        try:
            page.set_viewport_size({"width": 1280, "height": 720})
            page.click("#rail [data-edit-rooms]")
            page.wait_for_selector('#rail [data-room-grip="Kitchen"]')
            self.assertEqual(page.evaluate("Sortable.version"), "1.15.7")
            grip = page.locator('#rail [data-room-grip="Kitchen"]').bounding_box()
            target = page.locator('#rail [data-sort-room="Living room"]').bounding_box()
            with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/v1/rooms")):
                page.mouse.move(grip["x"] + 24, grip["y"] + 24)
                page.mouse.down()
                page.mouse.move(target["x"] + target["width"] - 24, target["y"] + 5, steps=12)
                page.wait_for_selector(".room-sort-ghost")
                page.wait_for_timeout(200)
                page.mouse.up()
            page.wait_for_function("document.querySelector('#rail [data-sort-room]').dataset.sortRoom === 'Kitchen'")
            self.assertEqual(page.request.get(self.server.url + "/api/v1/state").json()["rooms"],
                             ["Kitchen", "Living room", "Bedroom"])
            page.click("#rail [data-edit-rooms]")
            page.locator('#rail [data-room="Kitchen"]').click()
            self.assertEqual(page.inner_text("#title"), "Kitchen")
            page.set_viewport_size({"width": 720, "height": 1280})
            page.click("#room-tools [data-edit-rooms]")
            page.wait_for_selector('#rooms [data-room-grip="Kitchen"]')
            grip = page.locator('#rooms [data-room-grip="Kitchen"]').bounding_box()
            target = page.locator('#rooms [data-sort-room="Living room"]').bounding_box()
            cdp = page.context.new_cdp_session(page)
            x, y = grip["x"] + 24, grip["y"] + 24
            with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/v1/rooms")):
                cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
                page.wait_for_timeout(180)
                end = target["y"] + target["height"] - 5
                for step in range(1, 11):
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y + (end - y) * step / 10}]})
                    page.wait_for_timeout(20)
                page.wait_for_timeout(200)
                cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            page.wait_for_function("document.querySelector('#rooms [data-sort-room]').dataset.sortRoom === 'Living room'")
            self.assertEqual(page.request.get(self.server.url + "/api/v1/state").json()["rooms"],
                             ["Living room", "Kitchen", "Bedroom"])
            page.reload()
            page.wait_for_selector('[data-room-picker]')
            self.assertEqual(page.locator("[data-room-grip]").count(), 0)
            self.assertEqual(page.eval_on_selector_all("[data-room-picker] option", "els => els.map(e => e.value)"),
                             ["all", "Living room", "Kitchen", "Bedroom"])
            page.set_viewport_size({"width": 393, "height": 852})
            page.select_option("[data-room-picker]", "all")
            page.evaluate("window.scrollTo(0,0)")
            button = page.locator("#grid .tile").first.bounding_box()
            x, y = button["x"] + button["width"] / 2, button["y"] + button["height"] / 2
            cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
            for step in range(1, 9):
                cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y - 140 * step / 8}]})
                page.wait_for_timeout(20)
            cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            page.wait_for_function("window.scrollY > 0")
            self.assertEqual(page.locator(".room-sort-ghost").count(), 0)
            self.assertEqual(page.request.get(self.server.url + "/api/v1/state").json()["rooms"],
                             ["Living room", "Kitchen", "Bedroom"])
        finally:
            page.request.put(self.server.url + "/api/v1/rooms", data={"rooms": original})

    def test_room_drag_does_not_remove_a_concurrently_added_room(self):
        page = self.page
        page.set_viewport_size({"width": 1280, "height": 720})
        original = page.request.get(self.server.url + "/api/v1/state").json()
        try:
            page.click("#rail [data-edit-rooms]")
            grip = page.locator('#rail [data-room-grip="Kitchen"]').bounding_box()
            target = page.locator('#rail [data-sort-room="Living room"]').bounding_box()
            page.mouse.move(grip["x"] + 24, grip["y"] + 24)
            page.mouse.down()
            page.mouse.move(target["x"] + target["width"] - 24, target["y"] + 5, steps=12)
            page.wait_for_selector(".room-sort-ghost")
            latest = [*original["rooms"], "New office"]
            page.request.put(self.server.url + "/api/v1/rooms",
                             data={"rooms": latest, "expected_rooms": original["rooms"]})
            page.wait_for_function("async () => (await import('/js/store.js')).store.rooms.includes('New office')")
            page.mouse.up()
            page.wait_for_selector("text=Rooms changed on another screen.")
            page.wait_for_selector('#rail [data-room-name="New office"]')
            self.assertEqual(page.eval_on_selector_all("#rail [data-sort-room]", "els => els.map(e => e.dataset.sortRoom)"), latest)
            state = page.request.get(self.server.url + "/api/v1/state").json()
            self.assertEqual(state["rooms"], latest)
            self.assertEqual({d["id"]: d["room"] for d in state["devices"]},
                             {d["id"]: d["room"] for d in original["devices"]})
        finally:
            page.mouse.up()
            page.request.put(self.server.url + "/api/v1/rooms", data={"rooms": original["rooms"]})

    def test_room_edit_is_opt_in_and_rename_keeps_devices_and_tile_layout(self):
        page = self.page
        page.set_viewport_size({"width": 1280, "height": 720})
        original = page.request.get(self.server.url + "/api/v1/state").json()
        layout_before = original["settings"].get("room_layouts", {}).get("Bedroom")
        layout = {"widgets": [{"id": "bd-lamp", "size": "2x2",
                               "positions": {"4": {"x": 2, "y": 2, "size": "2x2"}}}]}
        try:
            page.request.put(self.server.url + "/api/v1/profiles/me/rooms/layout", data={"room": "Bedroom", "layout": layout})
            page.reload()
            page.wait_for_selector("#rail [data-edit-rooms]")
            self.assertEqual(page.locator("#rail [data-edit-rooms]").inner_text(), "Edit")
            self.assertEqual(page.locator("[data-room-grip], [data-room-name], #rail [data-add-room]").count(), 0)
            self.assertTrue(page.locator("#rail [data-room-sort]").evaluate("e => Sortable.get(e).option('disabled')"))
            page.click('#rail [data-room="Bedroom"]')
            page.click("#rail [data-edit-rooms]")
            self.assertFalse(page.locator("#rail [data-room-sort]").evaluate("e => Sortable.get(e).option('disabled')"))
            ids = page.eval_on_selector_all("#grid .tile", "els => els.map(e => e.dataset.id).sort()")
            saved_layout = page.request.get(self.server.url + "/api/v1/state").json()["settings"]["room_layouts"]["Bedroom"]
            page.fill('#rail [data-room-name="Bedroom"]', "Study")
            page.press('#rail [data-room-name="Bedroom"]', "Enter")
            page.wait_for_selector('#rail [data-room-name="Study"]')
            page.wait_for_selector('#title:text-is("Study")')
            state = page.request.get(self.server.url + "/api/v1/state").json()
            self.assertEqual(state["rooms"], ["Living room", "Study", "Kitchen"])
            self.assertEqual(state["settings"]["room_layouts"]["Study"], saved_layout)
            self.assertNotIn("Bedroom", state["settings"]["room_layouts"])
            self.assertEqual(page.eval_on_selector_all("#grid .tile", "els => els.map(e => e.dataset.id).sort()"), ids)
            page.click("#rail [data-edit-rooms]")
            self.assertEqual(page.locator("[data-room-grip], [data-room-name], #rail [data-add-room]").count(), 0)
            self.assertTrue(page.locator("#rail [data-room-sort]").evaluate("e => Sortable.get(e).option('disabled')"))
            page.reload()
            page.wait_for_selector('#title:text-is("Study")')
            self.assertEqual(page.locator("[data-room-grip]").count(), 0)
        finally:
            current = page.request.get(self.server.url + "/api/v1/state").json()["rooms"]
            if "Study" in current:
                page.request.put(self.server.url + "/api/v1/rooms", data={
                    "rooms": original["rooms"], "expected_rooms": current,
                    "rename": {"from": "Study", "to": "Bedroom"}})
            page.request.put(self.server.url + "/api/v1/profiles/me/rooms/layout", data={"room": "Bedroom", "layout": layout_before})

    def test_inline_room_names_save_cancel_validate_and_survive_live_updates(self):
        page = self.page
        original = page.request.get(self.server.url + "/api/v1/state").json()["rooms"]
        try:
            for width, scope, tools in ((1280, "#rail", "#rail"), (393, "#rooms", "#room-tools"),
                                         (720, "#settings", "#settings")):
                with self.subTest(width=width, scope=scope):
                    page.set_viewport_size({"width": width, "height": 900})
                    if scope == "#settings":
                        page.click("#open-settings")
                        page.click('[data-go="rooms"]')
                    page.click(f"{tools} [data-edit-rooms]")
                    field = page.locator(f'{scope} [data-room-name="Bedroom"]')
                    self.assertEqual(page.locator("[data-rename-room], .room-name-dialog").count(), 0)
                    self.assertEqual(page.locator('[data-room-name="all"], [data-room-name=""]').count(), 0)
                    field.fill("Not saved")
                    field.evaluate("e => e.setSelectionRange(2, 5)")
                    page.evaluate("async () => (await import('/js/store.js')).reload()")
                    self.assertEqual(field.input_value(), "Not saved")
                    self.assertEqual(field.evaluate("e => [e.selectionStart, e.selectionEnd]"), [2, 5])
                    self.assertTrue(page.locator(f"{scope} [data-room-sort]").evaluate("e => Sortable.get(e).option('disabled')"))
                    self.assertEqual(page.locator(".room-sort-ghost").count(), 0)
                    field.press("Escape")
                    self.assertEqual(field.input_value(), "Bedroom")
                    self.assertTrue(field.is_visible())
                    field.fill("Cancel by touch")
                    page.locator(f"{tools} [data-cancel-room-names]").click()
                    self.assertEqual(field.input_value(), "Bedroom")
                    for invalid, message in (("  ", "Give the room a name."), ("Kitchen", "That room already exists."),
                                             ("all", 'Choose a name other than "all"')):
                        field.fill(invalid)
                        page.click(f"{tools} [data-edit-rooms]")
                        page.wait_for_selector(f'{scope} [data-room-name="Bedroom"][aria-invalid="true"]')
                        self.assertEqual(field.input_value(), invalid)
                        self.assertIn(message, field.locator("..").inner_text())
                        self.assertTrue(field.evaluate("e => e === document.activeElement"))
                        self.assertEqual(page.locator(f"{tools} [data-edit-rooms]").inner_text(), "Done")
                    field.fill("Study")
                    page.click(f"{tools} [data-edit-rooms]")
                    page.wait_for_selector(f"{tools} [data-edit-rooms]:text-is('Edit')")
                    self.assertEqual(page.locator("[data-room-name]").count(), 0)
                    state = page.request.get(self.server.url + "/api/v1/state").json()
                    self.assertIn("Study", state["rooms"])
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                    page.request.put(self.server.url + "/api/v1/rooms", data={
                        "rooms": original, "expected_rooms": state["rooms"],
                        "rename": {"from": "Study", "to": "Bedroom"}})
                    if scope == "#settings":
                        page.click("#settings [data-back]")
                        page.click("#settings [data-back]")
                    page.wait_for_function("async () => (await import('/js/store.js')).store.rooms.includes('Bedroom')")
        finally:
            state = page.request.get(self.server.url + "/api/v1/state").json()
            if "Study" in state["rooms"]:
                page.request.put(self.server.url + "/api/v1/rooms", data={
                    "rooms": original, "rename": {"from": "Study", "to": "Bedroom"}})

    def test_inline_room_name_retains_removed_draft_and_rejects_stale_save(self):
        page = self.page
        page.set_viewport_size({"width": 1280, "height": 720})
        original = page.request.get(self.server.url + "/api/v1/state").json()["rooms"]
        try:
            page.click("#rail [data-edit-rooms]")
            field = page.locator('#rail [data-room-name="Bedroom"]')
            field.fill("Study")
            current = ["Office" if r == "Bedroom" else r for r in original]
            page.request.put(self.server.url + "/api/v1/rooms", data={
                "rooms": current, "expected_rooms": original,
                "rename": {"from": "Bedroom", "to": "Office"}})
            page.wait_for_function("async () => (await import('/js/store.js')).store.rooms.includes('Office')")
            self.assertEqual(field.input_value(), "Study")
            page.click("#rail [data-edit-rooms]")
            page.wait_for_selector('#rail [data-room-name="Bedroom"][aria-invalid="true"]')
            self.assertEqual(field.input_value(), "Study")
            self.assertIn("no longer available", field.locator("..").inner_text())
            self.assertEqual(page.request.get(self.server.url + "/api/v1/state").json()["rooms"], current)
            field.press("Escape")
            self.assertEqual(field.count(), 0)
            page.wait_for_selector('#rail [data-room-name="Office"]')
        finally:
            current = page.request.get(self.server.url + "/api/v1/state").json()["rooms"]
            if "Office" in current:
                page.request.put(self.server.url + "/api/v1/rooms", data={
                    "rooms": original, "rename": {"from": "Office", "to": "Bedroom"}})

    def test_energy_chart_for_metering_plug(self):
        self.tile("kt-fridge").locator("[data-more]").click()
        self.page.wait_for_selector(".bars .bar")
        self.assertEqual(self.page.locator(".bars .bar").count(), 7)

    def pick_room(self, name):
        self.page.select_option("[data-room-picker]", "all" if name == "All rooms" else "" if name == "Other" else name)

    def swipe(self, dx):
        box = self.page.locator("#grid .tile").first.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.mouse.move(x + dx, y + 4, steps=8)
        self.page.mouse.up()

    def shown_ids(self):
        return set(self.page.eval_on_selector_all("#grid .tile", "els => els.map(e => e.dataset.id)"))

    def test_room_picker_switches_swipes_and_remembers(self):
        names = self.page.locator("[data-room-picker] option").all_text_contents()
        self.assertEqual(names, ["All rooms", "Living room", "Bedroom", "Kitchen"])
        self.assertGreaterEqual(self.page.locator("[data-room-picker]").bounding_box()["height"], 48)
        self.assertEqual(self.page.locator(".room-section").count(), 3)       # "All" = every room, with headings

        self.pick_room("Kitchen")
        self.page.wait_for_function("document.querySelector('[data-room-picker]').value === 'Kitchen'")
        self.assertEqual(self.shown_ids(), {"kt-pendant", "kt-kettle", "kt-fridge"})
        self.assertEqual((self.page.inner_text("#title"), self.page.inner_text("#subtitle")), ("Kitchen", "1 of 3 on"))

        self.page.reload()                                                     # the chosen room is remembered
        self.page.wait_for_selector(".tile")
        self.assertEqual(self.shown_ids(), {"kt-pendant", "kt-kettle", "kt-fridge"})

        kettle_on = self.tile("kt-kettle").evaluate("el => el.classList.contains('on')")
        self.swipe(200)                                                        # swipe right = previous room
        self.page.wait_for_function("document.querySelector('[data-room-picker]').value === 'Bedroom'")
        self.assertEqual(self.shown_ids(), {"bd-lamp", "bd-tv", "bd-fan"})
        self.swipe(-200)                                                       # and back
        self.page.wait_for_function("document.querySelector('[data-room-picker]').value === 'Kitchen'")
        self.assertEqual(kettle_on, self.tile("kt-kettle").evaluate("el => el.classList.contains('on')"))  # not a tap

        self.pick_room("All rooms")
        self.tile("lr-lamp").locator("[data-more]").focus()
        self.tile("lr-lamp").locator("[data-more]").press("Enter")
        self.page.wait_for_selector('#sheet[data-device-id="lr-lamp"]:not([hidden])')
        self.page.click("#sheet [data-close]")
        self.page.wait_for_selector("#sheet", state="hidden")
        self.page.locator(".room-title", has_text="Bedroom").click()          # a heading in "All" opens its tab
        self.page.wait_for_function("document.querySelector('[data-room-picker]').value === 'Bedroom'")

    def test_other_tab_nudges_to_pick_a_room_and_turns_off_just_those(self):
        api = "(path, body, method = 'POST') => fetch('/api/v1' + path, {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})"
        self.page.evaluate(f"({api})('/devices/bd-fan', {{room: ''}}, 'PATCH')")
        try:
            self.page.evaluate(f"({api})('/devices/bd-fan/command', {{action: 'power', value: true}})")
            self.page.reload()
            self.page.wait_for_selector('[data-room-picker] option[value=""]', state="attached")
            self.pick_room("Other")
            self.page.wait_for_selector(".nudge")
            self.assertEqual(self.shown_ids(), {"bd-fan"})
            self.page.wait_for_selector('.tile.on[data-id="bd-fan"]')
            self.page.click(".room-head [data-room-off]")                      # "Turn off" for this group only
            self.page.wait_for_selector('.tile[data-id="bd-fan"]:not(.on)')
            self.assertTrue(self.page.evaluate(
                "fetch('/api/v1/state').then(r => r.json()).then(s => s.devices.find(d => d.id === 'lr-tv').state.on)"))
            self.page.click("[data-sort-rooms]")                               # one device: straight to its room picker
            self.page.wait_for_selector("#d-room")
            self.assertEqual(self.page.input_value("#d-room"), "")
        finally:
            self.page.evaluate(f"({api})('/devices/bd-fan', {{room: 'Bedroom'}}, 'PATCH')")

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
        self.page.wait_for_function(f"{root}.dataset.bg === 'sky' && {root}.classList.contains('glass')")
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
                              body: JSON.stringify({background: 'sky', glass_transparency: 45})})""")

    def test_device_illustrations_and_own_photo(self):
        # with the icon on "Auto", tiles show a drawing of the device
        self.assertEqual(self.tile("lr-tv").locator(".tile-icon.art svg.art").count(), 1)
        self.assertEqual(self.tile("lr-vacuum").locator(".tile-icon.art").count(), 1)
        ids = self.page.evaluate("[...document.querySelectorAll('.tile svg.art [id]')].map(e => e.id)")
        self.assertEqual(len(ids), len(set(ids)))               # each drawing has its own gradient ids
        # your own photo of the device replaces the drawing
        import os
        import tempfile
        from PIL import Image
        path = os.path.join(tempfile.mkdtemp(), "my-kettle.png")
        img = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
        img.paste((200, 200, 210, 255), (150, 100, 450, 500))
        img.save(path, "PNG")
        self.page.click("#open-settings")
        self.page.click("[data-go=devices]")
        self.page.click("[data-arg=kt-kettle]")
        self.page.set_input_files("#d-pic-input", path)
        self.page.wait_for_selector("text=Photo added")
        self.page.wait_for_selector('#d-pic-preview img.dev-photo.cutout')
        self.page.wait_for_selector("[data-clear-pic]")
        self.assertEqual(self.tile("kt-kettle").locator("img.dev-photo").count(), 1)
        self.page.click("[data-clear-pic]")
        self.page.wait_for_selector("text=Photo removed")
        self.assertEqual(self.tile("kt-kettle").locator("img.dev-photo").count(), 0)
        self.assertEqual(self.errors, [])

    def _put_settings(self, **changes):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/settings", method="PUT",
                                     data=json.dumps(changes).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def _bright_wallpaper(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1600, 1000), (250, 238, 214)).save(buf, "JPEG")      # pale cream: a light background
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/wallpapers?name=cream.jpg", method="POST",
                                     data=buf.getvalue(), headers={"Content-Type": "image/jpeg"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())["id"]

    def _text_luma(self, page, selector):
        return page.evaluate(f"""(() => {{ const c = getComputedStyle(document.querySelector('{selector}')).color
            .match(/\\d+(\\.\\d+)?/g).map(Number); return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255; }})()""")

    def test_tiles_contrast_with_the_background(self):
        root = "document.documentElement"
        try:
            # a dark background (the Sky, Ocean…): light tiles with dark text, page text stays light
            self._put_settings(background="ocean", tile_style="auto")
            page = self.open(view="rooms")
            page.wait_for_function(f"{root}.dataset.tiles === 'light' && {root}.dataset.tone === 'dark'")
            self.assertLess(self._text_luma(page, '.tile[data-id="lr-tv"] .tile-name'), 0.3)
            self.assertGreater(self._text_luma(page, ".topbar-title h1"), 0.7)
            page.close()
            # a bright wallpaper: dark tiles with light text, and the page title turns dark
            wid = self._bright_wallpaper()
            self._put_settings(background="wallpaper", wallpaper=wid, wallpaper_dim=0)
            page = self.open(view="rooms")
            page.wait_for_function(f"{root}.dataset.tiles === 'dark' && {root}.dataset.tone === 'light'")
            self.assertGreater(self._text_luma(page, '.tile[data-id="lr-tv"] .tile-name'), 0.7)
            self.assertLess(self._text_luma(page, ".topbar-title h1"), 0.3)
            # darkening it a lot makes it a dark background again
            self._put_settings(wallpaper_dim=80)
            page.reload()
            page.wait_for_function(f"{root}.dataset.tiles === 'light' && {root}.dataset.tone === 'dark'")
            # choosing a style by hand wins, previewed live in Settings → Display
            page.click("#open-settings")
            page.click("[data-go=display]")
            page.click('.seg-choice:has(input[value="dark"])')
            page.wait_for_function(f"{root}.dataset.tiles === 'dark'")
            page.click("[data-display] button[type=submit]")
            page.wait_for_selector("text=Saved")
            page.reload()
            page.wait_for_function(f"{root}.dataset.tiles === 'dark'")
            page.close()
        finally:
            self._put_settings(background="sky", wallpaper="shuffle", wallpaper_dim=25, tile_style="auto")

    def test_wallpaper_background(self):
        root = "document.documentElement"
        self.page.click("#open-settings")
        self.page.click("[data-go=display]")
        self.assertEqual(self.page.locator("#wall-panel").is_hidden(), True)
        self.page.click(".bg-choice:has(input[value=wallpaper])")
        self.page.wait_for_selector("#wall-panel:not([hidden]) .wall-choice")
        self.page.wait_for_function(f"{root}.classList.contains('has-wallpaper')")       # live preview
        self.page.wait_for_selector(".wall-layer .wp.show")
        first = self.page.locator('#wall-grid input[name=wallpaper]:not([value=shuffle])').first
        wid = first.get_attribute("value")
        self.page.click(f'.wall-choice:has(input[value="{wid}"])')
        self.page.fill("input[name=wallpaper_dim]", "40")
        self.page.click("[data-display] button[type=submit]")
        self.page.wait_for_selector("text=Saved")
        self.page.reload()
        self.page.wait_for_function(f"{root}.dataset.bg === 'wallpaper' && {root}.classList.contains('has-wallpaper')")
        self.page.wait_for_function(f"document.querySelector('.wall-layer .wp.show').style.backgroundImage.includes('{wid}')")
        self.assertAlmostEqual(float(self.page.evaluate(f"getComputedStyle({root}).getPropertyValue('--wall-dim')")), 0.4)
        self.assertEqual(self.errors, [])
        self.page.evaluate("""fetch('/api/v1/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'},
                              body: JSON.stringify({background: 'sky', wallpaper: 'shuffle', wallpaper_dim: 25})})""")

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

    def test_internal_fixtures_direct_real_device_use_to_the_canonical_app(self):
        self.page.click("#open-settings")
        self.page.click("[data-go=add]")
        self.page.click("[data-arg=shelly]")          # a brand with no extra libraries, so always available
        self.page.wait_for_selector("text=Internal test fixtures, not household data.")
        self.assertIn("native panel on port 8080", self.page.locator("#settings .note").inner_text())

    def test_diagnostics_says_where_to_open_on_a_phone(self):
        self.page.click("#open-settings")
        self.page.get_by_text("Diagnostics and logs").click()
        self.page.wait_for_selector("#phone-url")
        self.assertIn("same Wi-Fi", self.page.locator("#phone-url").inner_text())
        self.assertEqual(self.errors, [])

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
        self.page.click('[data-control-section="vac-rooms"] > summary')
        self.page.click('#sheet [data-room-pick="2"]')
        self.page.click('#sheet [data-room-pick="3"]')
        self.page.wait_for_selector("#sheet [data-clean-rooms] >> text=Clean 2 rooms")
        self.page.click("#sheet [data-clean-rooms]")
        self.page.wait_for_selector("#sheet [data-clean=pause]")
        self.page.click('[data-control-section="vac-options"] > summary')
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
        self.page.wait_for_selector("#sheet:not([hidden]) .device-head")
        if self.page.locator("#sheet .tv-off").count():
            self.page.click("#sheet [data-power]")
        self.page.wait_for_selector("#sheet .remote")

    def test_remote_layout_and_modes(self):
        sent = self.commands()
        self.open_tv("lr-tv")                       # demo "Samsung TV": no pointer
        top = self.page.locator("#sheet .device-power")
        self.assertEqual(top.locator("[data-power]").count(), 1)
        self.assertIn("Samsung TV", self.page.locator("#sheet .device-head h2").inner_text())
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
        self.page.click('[data-control-section="apps"] > summary')
        self.page.click("#sheet [data-app]:not([aria-pressed=true]) >> nth=0")
        self.page.wait_for_function("() => true")
        self.page.wait_for_timeout(300)
        actions = [a for a in sent]
        self.assertIn(("key", "OK"), actions)
        self.assertIn(("volume_up", None), actions)
        self.assertIn(("key", "7"), actions)
        self.assertTrue(any(a == "launch_app" for a, _ in actions))
        self.page.click('[data-control-section="remote-more"] > summary')
        for sel in ("[data-key=MENU]", "[data-key=UP]", "[data-act=volume_up]", "[data-mode=dpad]", "[data-app]"):
            box = self.page.locator(f"#sheet {sel}").first.bounding_box()
            self.assertGreaterEqual(min(box["width"], box["height"]), 48, sel)

    def test_remote_fits_a_phone_with_accessible_primary_controls_and_close(self):
        self.page.set_viewport_size({"width": 393, "height": 852})
        self.open_tv("lr-tv")
        self.page.wait_for_timeout(350)               # sheet animation
        fits = self.page.evaluate("(() => { const s = document.querySelector('#sheet').getBoundingClientRect();"
                                  " const pad = document.querySelector('#sheet .dpad').getBoundingClientRect();"
                                  " return s.top >= 0 && pad.top >= s.top && pad.bottom <= s.bottom; })()")
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
        self.page.click('[data-control-section="vac-options"] > summary')
        opts = self.page.locator("#sheet .opts")
        self.assertIn("Suction", opts.inner_text())
        self.assertIn("Mode", opts.inner_text())
        self.assertIn("Dock actions", opts.inner_text())
        self.assertEqual(opts.locator("[data-clean-mode] svg").count(), 3)          # every mode has an icon
        self.page.click('#sheet [data-clean-mode="mop"]')
        self.page.wait_for_selector('#sheet [data-clean-mode="mop"][aria-pressed="true"]')
        self.page.click('#sheet [data-clean-mode="vacuum"]')
        self.page.wait_for_selector('#sheet [data-clean-mode="vacuum"][aria-pressed="true"]')
        self.page.click('[data-control-section="station"] > summary')
        self.page.click('#sheet [data-station="empty_dustbin"]')
        self.page.wait_for_selector("text=Empty dustbin: sent to the station")
        # parts wear stays folded behind one Maintenance row
        part = self.page.locator("#sheet .vac-parts .part").first
        self.assertFalse(part.is_visible())
        self.assertIn("Filter", self.page.locator("#sheet .maint-row").inner_text())
        self.page.click("#sheet .maint-row")
        part.wait_for(state="visible")
        # picking rooms turns the main button into "Clean 1 room"; Clear undoes it
        self.page.click('[data-control-section="vac-rooms"] > summary')
        self.page.click('#sheet [data-room-pick="2"]')
        self.page.wait_for_selector("#sheet .vac-main >> text=Clean 1 room")
        self.page.click("#sheet [data-rooms-clear]")
        self.page.wait_for_selector("#sheet .vac-main >> text=Start cleaning")
        for sel in (".vac-main", "[data-locate]", '[data-suction="max"]', '[data-clean-mode="mop"]', ".maint-row"):
            self.assertGreaterEqual(self.page.locator(f"#sheet {sel}").bounding_box()["height"], 48, sel)
        no_overflow = self.page.evaluate("document.querySelector('#sheet').scrollWidth <= 393")
        self.assertTrue(no_overflow)


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

    def test_use_my_location_fills_form_without_saving(self):
        svc = FakeJsonServer({"/ipapi/": (200, IPAPI_SEATTLE), "/reverse": (200, REVERSE_SEATTLE)})
        env = {"HOMEPANEL_GEO_IP_URLS": f"{svc.base}/ipapi/", "HOMEPANEL_GEO_REVERSE_URL": f"{svc.base}/reverse"}
        os.environ.update(env)
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True,
                                       geolocation={"latitude": 47.606209, "longitude": -122.332071},
                                       permissions=["geolocation"])
        page = ctx.new_page()
        try:
            def open_location(p):
                p.goto(f"http://127.0.0.1:{self.port}/")
                p.wait_for_selector(".widget, .tile")
                p.click("#open-settings")
                p.click("[data-go=location]")
                p.wait_for_selector("[data-locate]")

            # 1. the browser shares this device's location (127.0.0.1 counts as a secure page)
            open_location(page)
            self.assertEqual(svc.requests, [])                  # nothing sent before the tap
            page.click("[data-locate]")
            page.wait_for_selector("#locate-status:not([hidden])")
            self.assertIn("Found Seattle, WA (from this device)", page.inner_text("#locate-status"))
            self.assertEqual(page.input_value("input[name=latitude]"), "47.61")
            self.assertEqual(page.input_value("input[name=longitude]"), "-122.33")
            self.assertEqual(page.input_value("input[name=place_name]"), "Seattle, WA")
            self.assertEqual(svc.requests, ["/reverse?latitude=47.61&longitude=-122.33&localityLanguage=en"])
            self.assertIsNone(page.evaluate("fetch('/api/v1/state').then(r => r.json()).then(s => s.settings.latitude)"))
            page.click("[data-location] button[type=submit]")    # only Save stores it
            page.wait_for_selector("text=Location saved")
            self.assertEqual(page.evaluate("fetch('/api/v1/state').then(r => r.json()).then(s => s.settings.place_name)"),
                             "Seattle, WA")

            # 2. location blocked (like plain HTTP over Tailscale) → approximate, from the internet address
            self.page.click("#open-settings")
            self.page.click("[data-go=location]")
            self.page.fill("input[name=place_name]", "")
            self.page.click("[data-locate]")
            self.page.wait_for_selector("#locate-status:not([hidden])")
            self.assertIn("approximate, from your internet address", self.page.inner_text("#locate-status"))
            self.assertEqual(self.page.input_value("input[name=place_name]"), "Seattle, WA")

            # 3. services unreachable → plain message, typing still works
            svc.stop()
            self.page.click("[data-locate]")
            self.page.wait_for_selector("#locate-status.error")
            self.assertIn("enter your location by hand", self.page.inner_text("#locate-status"))
            self.page.fill("input[name=place_name]", "Home")
            self.assertEqual(self.page.input_value("input[name=place_name]"), "Home")
        finally:
            for k in env:
                os.environ.pop(k, None)
            ctx.close()
            self.put_settings(latitude=None, longitude=None, place_name="")

    def test_turn_on_weather_from_home_uses_my_location(self):
        svc = FakeJsonServer({"/ipapi/": (200, IPAPI_SEATTLE)})
        os.environ["HOMEPANEL_GEO_IP_URLS"] = f"{svc.base}/ipapi/"
        page = self.home()
        try:
            page.click("[data-setup-weather]")
            page.wait_for_selector("[data-locate]")
            self.assertTrue(page.is_checked("input[name=weather_enabled]"))   # that's why they came here
            self.assertEqual(svc.requests, [])
            page.click("[data-locate]")
            page.wait_for_selector("#locate-status:not([hidden])")
            page.click("[data-location] button[type=submit]")
            page.wait_for_selector("text=Location saved")
            s = page.evaluate("fetch('/api/v1/state').then(r => r.json()).then(s => s.settings)")
            self.assertEqual((s["latitude"], s["longitude"], s["place_name"], s["weather_enabled"]),
                             (47.61, -122.33, "Seattle, WA", True))
        finally:
            os.environ.pop("HOMEPANEL_GEO_IP_URLS", None)
            svc.stop()
            page.close()
            self.put_settings(latitude=None, longitude=None, place_name="", weather_enabled=False)

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


    # ---------- Home page, room rail, dock, edit mode, sky ----------
    def home(self, **kw):
        page = self.open(view="home", reduced_motion="reduce", **kw)   # no wiggle, so clicks land
        page.wait_for_selector(".widget")
        return page

    def long_press(self, page, selector, ms=700):
        box = page.locator(selector).bounding_box()
        page.mouse.move(box["x"] + 30, box["y"] + 30)
        page.mouse.down()
        page.wait_for_timeout(ms)
        page.mouse.up()

    def order(self, page):
        return page.eval_on_selector_all(".home-grid > .widget", "els => els.map(e => e.dataset.wid)")

    def test_home_headings_are_not_visible_but_status_navigation_and_room_titles_remain(self):
        page = self.home()
        try:
            for width, height in ((720, 1280), (1280, 720)):
                with self.subTest(width=width):
                    page.set_viewport_size({"width": width, "height": height})
                    page.wait_for_timeout(100)
                    self.assertEqual(page.locator("#rail .rail-head").count(), 0)
                    self.assertEqual(page.get_by_role("heading", name="Home", exact=True).count(), 1)
                    title = page.locator("#title")
                    self.assertEqual(title.evaluate("e => getComputedStyle(e).clipPath"), "inset(50%)")
                    self.assertLessEqual(title.bounding_box()["height"], 1)
                    self.assertRegex(page.inner_text("#subtitle"), r"^(Everything is off|[0-9]+ (thing is|things are) on)$")
                    self.assertLessEqual(page.locator(".topbar").bounding_box()["height"], 80 if width < 768 else 48)
                    for control in ("#voice-btn", "#edit-home", "#all-off", "#open-frame", "#profile-btn"):
                        self.assertTrue(page.locator(control).is_visible())
                        self.assertGreaterEqual(page.locator(control).bounding_box()["height"], 48)
                    nav = '#rail [data-nav="home"]' if width >= 768 else '#dock [data-nav="home"]'
                    self.assertTrue(page.locator(nav).is_visible())
                    if width >= 768:
                        self.assertLessEqual(page.locator(nav).bounding_box()["y"], 24)
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                    page.click('[data-go-room="Kitchen"]')
                    page.wait_for_selector('#title:text-is("Kitchen")')
                    self.assertEqual(title.evaluate("e => getComputedStyle(e).clipPath"), "none")
                    self.assertGreater(title.bounding_box()["height"], 20)
                    self.assertTrue(page.locator('[data-room-off="Kitchen"]').is_visible())
                    page.click(nav)
                    page.wait_for_function("document.documentElement.dataset.view === 'home'")
        finally:
            page.close()

    def drag_to_cell(self, page, selector, x, y, cancel=False):
        box = page.locator(selector)
        box.scroll_into_view_if_needed()
        metrics = box.evaluate("""el => {
            const r = el.getBoundingClientRect(), grid = el.parentElement, g = grid.getBoundingClientRect();
            const cs = getComputedStyle(grid);
            return {left:r.left, top:r.top, x:g.left, y:g.top,
              stepX:parseFloat(cs.gridTemplateColumns) + parseFloat(cs.columnGap),
              stepY:parseFloat(cs.gridAutoRows) + parseFloat(cs.rowGap)};
        }""")
        page.mouse.move(metrics["left"] + 55, metrics["top"] + 55)
        page.mouse.down()
        page.wait_for_timeout(250)
        page.mouse.move(metrics["x"] + x * metrics["stepX"] + 55,
                        metrics["y"] + y * metrics["stepY"] + 55, steps=6)
        self.assertEqual(page.locator(".grid-drop-target").count(), 1)
        self.assertTrue(box.evaluate("""async el => {
            await (await import('/js/store.js')).reload();
            return el.isConnected && !!el.closest('[data-grid-gesture]');
        }"""))
        if cancel:
            box.evaluate("el => el.parentElement.dispatchEvent(new PointerEvent('pointercancel', {bubbles:true, pointerId:1}))")
        page.mouse.up()
        self.assertEqual(page.locator(".grid-drop-target").count(), 0)

    def placements(self, page, selector=".home-grid > .widget"):
        return page.eval_on_selector_all(selector, """els => Object.fromEntries(els.map(el =>
          [el.dataset.wid, {column:el.style.gridColumnStart, row:el.style.gridRowStart,
                           size:[...el.classList].find(c => c.startsWith('s-'))}]))""")

    def assert_grid_fits(self, page, selector):
        self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        boxes = page.locator(selector).evaluate_all("""els => els.map(el => {
          const r = el.getBoundingClientRect(); return {x:r.x, y:r.y, right:r.right, bottom:r.bottom};
        })""")
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(a["x"] < b["right"] - 1 and b["x"] < a["right"] - 1
                                 and a["y"] < b["bottom"] - 1 and b["y"] < a["bottom"] - 1, (a, b))

    def test_home_page_has_clocks_and_rooms_but_no_devices(self):
        page = self.home(timezone_id="America/Denver")
        try:
            page.wait_for_selector('.widget[data-wid="clock"] [data-time]')
            for wid, tz in (("zone-in", "Asia/Kolkata"), ("zone-us", "America/Denver")):   # US = this screen's zone
                zone = page.locator(f'.widget[data-wid="{wid}"] .w-zone')
                self.assertEqual(zone.get_attribute("data-zone"), tz)
                expected = page.evaluate(f"new Date().toLocaleTimeString([], {{timeZone: '{tz}', hour: 'numeric', minute: '2-digit'}})")
                self.assertTrue(expected.startswith(zone.locator("[data-time]").inner_text()))
            self.assertIn("India", page.inner_text('.widget[data-wid="zone-in"]'))

            # devices aren't on Home: they're on each room's page
            self.assertEqual(page.locator("#home .tile, #home .t-device").count(), 0)
            self.assertEqual(page.locator("#grid .tile:visible").count(), 0)
            rooms = page.eval_on_selector_all('.widget[data-wid="rooms"] [data-go-room]', "els => els.map(e => e.dataset.goRoom)")
            self.assertEqual(rooms, ["Living room", "Bedroom", "Kitchen"])

            page.click('[data-go-room="Kitchen"]')                              # Rooms widget opens that room
            page.wait_for_function("document.documentElement.dataset.view === 'rooms'")
            page.wait_for_function("document.querySelector('[data-room-picker]').value === 'Kitchen'")
            ids = set(page.eval_on_selector_all("#grid .tile", "els => els.map(e => e.dataset.id)"))
            self.assertEqual(ids, {"kt-pendant", "kt-kettle", "kt-fridge"})
            page.click('#dock [data-nav="home"]')
            page.wait_for_selector('.widget[data-wid="clock"]')
        finally:
            page.close()

    def test_us_clock_falls_back_to_eastern_outside_the_us(self):
        page = self.home(timezone_id="Europe/London")
        try:
            self.assertEqual(page.get_attribute('.widget[data-wid="zone-us"] .w-zone', "data-zone"), "America/New_York")
        finally:
            page.close()

    def test_iphone_ipad_and_panel_sizes(self):
        sizes = [(320, 568, True), (360, 640, True), (393, 852, True), (568, 320, True),
                 (768, 1024, False), (820, 1180, False), (1024, 768, False),
                 (1180, 820, False), (720, 1280, False), (1280, 720, False)]
        for w, h, phone in sizes:
            with self.subTest(size=f"{w}x{h}"):
                page = self.home(width=w, height=h, is_mobile=phone)
                try:
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth - innerWidth"), 0)
                    wide = w >= 768
                    self.assertEqual(page.locator("#rail").is_visible(), wide)       # vertical room tabs
                    self.assertEqual(page.locator("#dock").is_visible(), not wide)   # floating dock
                    targets = page.locator("#rail button:visible, #dock button:visible, .topbar button:visible")
                    for i in range(targets.count()):
                        box = targets.nth(i).bounding_box()
                        self.assertGreaterEqual(min(box["width"], box["height"]), 48, targets.nth(i).inner_text())
                        self.assertGreaterEqual(box["x"], 0)
                        self.assertLessEqual(box["x"] + box["width"], w)
                    if not wide:
                        dock = page.locator(".dock-bar").bounding_box()
                        add = page.locator(".dock-add").bounding_box()
                        self.assertGreaterEqual(dock["x"], 12)
                        self.assertLessEqual(add["x"] + add["width"], w - 12)
                    # Small clocks must not collapse when a sidebar is introduced.
                    for widget in page.locator(".widget.s-1x1").all():
                        self.assertGreaterEqual(widget.bounding_box()["width"], 130)
                    if wide:
                        page.click('#rail [data-room="Kitchen"]')
                        page.wait_for_selector('#grid .tile[data-id="kt-kettle"]')
                        self.assertEqual(page.inner_text("#title"), "Kitchen")
                        self.assertTrue(page.locator("#rooms").is_hidden())
                        page.click('#rail [data-nav="home"]')
                        page.wait_for_selector(".widget")
                finally:
                    page.close()

    def test_unrelated_device_updates_keep_room_tiles_and_navigation(self):
        page = self.page
        page.set_viewport_size({"width": 1180, "height": 820})
        page.click('#rail [data-room="Kitchen"]')
        page.wait_for_selector('.tile[data-id="kt-kettle"]')
        result = page.evaluate("""async () => {
            const {store, upsertDevice} = await import('/js/store.js');
            const tile = document.querySelector('.tile[data-id="kt-kettle"]');
            const opener = tile.querySelector('[data-more]');
            const nav = document.querySelector('#rail [data-room="Kitchen"]');
            opener.focus();
            const device = structuredClone(store.devices.get('lr-lamp'));
            device.state.on = !device.state.on;
            upsertDevice(device);
            const focusKept = document.activeElement === opener;
            nav.focus();
            device.state.brightness = 43;
            upsertDevice(device);
            return {tile: tile === document.querySelector('.tile[data-id="kt-kettle"]'),
                    focusKept, nav: document.activeElement === nav && nav.isConnected};
        }""")
        self.assertEqual(result, {"tile": True, "focusKept": True, "nav": True})

    def test_home_room_counts_keep_buttons_focus_and_scroll(self):
        page = self.home(width=393, height=852)
        try:
            result = page.evaluate("""async () => {
                const {store, upsertDevice} = await import('/js/store.js');
                const button = document.querySelector('#home [data-go-room="Living room"]');
                const list = button.parentElement;
                list.style.height = '48px'; list.style.flex = 'none';
                button.focus();
                list.scrollTop = 30;
                const scroll = list.scrollTop;
                const before = Number(button.querySelector('.count').textContent);
                const device = structuredClone(store.devices.get('lr-lamp'));
                const wasOn = device.state.on;
                device.state.on = !wasOn;
                upsertDevice(device);
                const after = Number(button.querySelector('.count').textContent);
                return {same: button === document.querySelector('#home [data-go-room="Living room"]'),
                        focus: document.activeElement === button, scroll: list.scrollTop === scroll,
                        updated: after === before + (wasOn ? -1 : 1)};
            }""")
            self.assertEqual(result, {"same": True, "focus": True, "scroll": True, "updated": True})
        finally:
            page.close()

    def test_long_room_names_and_short_landscape_rail_remain_usable(self):
        page = self.page
        page.set_viewport_size({"width": 320, "height": 568})
        page.evaluate("""async () => {
            const {store, emit} = await import('/js/store.js');
            const name = 'A very long room name ' + 'x'.repeat(80);
            store.rooms = [name];
            for (const d of store.devices.values()) d.room = name;
            emit('all');
        }""")
        head = page.locator('.room-head')
        self.assertTrue(head.evaluate('e => e.scrollWidth <= e.clientWidth'))
        off = head.locator('.room-off').bounding_box()
        self.assertGreaterEqual(off["height"], 48)
        self.assertLessEqual(off["x"] + off["width"], 320)
        # Lots of rooms on a short screen should scroll, never shrink Home/Settings.
        page.set_viewport_size({"width": 844, "height": 390})
        page.evaluate("""async () => {
            const {store, emit} = await import('/js/store.js');
            store.rooms = Array.from({length: 20}, (_, i) => `Room ${i}`);
            const template = store.devices.values().next().value;
            store.devices = new Map(store.rooms.map((room, i) => [String(i), {...template, id: String(i), room}]));
            emit('all');
        }""")
        for button in page.locator('#rail button').all():
            self.assertGreaterEqual(button.bounding_box()["height"], 48)
        page.locator('#rail [data-open-settings]').scroll_into_view_if_needed()
        self.assertTrue(page.locator('#rail [data-open-settings]').is_visible())

    def test_edit_home_page_hide_resize_move_and_save_for_every_screen(self):
        page = self.home()
        try:
            self.long_press(page, '.widget[data-wid="clock"]')                 # long press the page = edit
            page.wait_for_selector(".home.editing .editbar")
            page.click('.widget[data-wid="scenes"] [data-hide]')
            before = self.placements(page)
            self.drag_to_cell(page, '.widget[data-wid="weather"]', 2, 2)
            page.click('.widget[data-wid="weather"] [data-resize]')            # a tap on the corner: next size
            self.assertIn("s-2x2", page.get_attribute('.widget[data-wid="weather"]', "class"))
            page.click('.widget[data-wid="zone-us"] [data-menu]')
            page.select_option("[data-zone-pick]", "America/Chicago")
            page.click('[data-size-pick="1x1"]')
            page.click(".wmenu button.btn[data-menu-close]")
            self.drag_to_cell(page, '.widget[data-wid="clock"]', 0, 2)         # occupied: don't displace Rooms
            self.assertEqual(self.placements(page)["clock"], before["clock"])
            self.drag_to_cell(page, '.widget[data-wid="clock"]', 0, 4, cancel=True)
            self.assertEqual(self.placements(page)["clock"], before["clock"])
            self.drag_to_cell(page, '.widget[data-wid="clock"]', 0, 4)         # empty space, not another tile
            moved = self.placements(page)
            self.assertEqual(moved["clock"]["row"], "5")
            self.assertEqual(moved["rooms"], before["rooms"])                 # the other tiles stay put
            self.assert_grid_fits(page, ".home-grid > .widget")
            page.click("[data-edit-done]")
            page.wait_for_selector("text=Home page saved")

            other = self.home(width=1180, height=820)                           # another screen: same Home page
            try:
                self.assertEqual(self.placements(other), moved)
                self.assertEqual(other.locator('.widget[data-wid="scenes"]').count(), 0)
                self.assertIn("s-2x2", other.get_attribute('.widget[data-wid="weather"]', "class"))
                self.assertIn("s-1x1", other.get_attribute('.widget[data-wid="zone-us"]', "class"))
                self.assertEqual(other.get_attribute('.widget[data-wid="zone-us"] .w-zone', "data-zone"), "America/Chicago")
            finally:
                other.close()

            page.click("#edit-home")                                           # Cancel puts it all back
            page.click('.widget[data-wid="weather"] [data-hide]')
            page.click("[data-add-widget]")                                    # hidden widgets can come back
            page.wait_for_selector('.wmenu [data-unhide="scenes"]')
            self.assertNotIn("Devices", page.inner_text(".wmenu"))            # devices aren't Home widgets any more
            page.click('.wmenu [data-unhide="scenes"]')
            page.wait_for_selector('.widget[data-wid="scenes"]')
            page.click("[data-edit-cancel]")
            page.wait_for_selector(".home:not(.editing)")
            self.assertEqual(self.placements(page), moved)
            saved = page.evaluate("async () => (await (await import('/js/api.js')).api.state()).settings.home_layout")
            for width, height in ((393, 852), (1280, 720), (720, 1280)):
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(100)
                self.assert_grid_fits(page, ".home-grid > .widget")
                self.assertEqual(page.evaluate("async () => (await (await import('/js/api.js')).api.state()).settings.home_layout"), saved)
            self.assertEqual(self.placements(page), moved)
        finally:
            page.evaluate("fetch('/api/v1/profiles/me/layout', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: '{\"home_layout\": null}'})")
            page.close()

    def test_room_settings_edit_tiles_resize_save_cancel_and_live_updates(self):
        page = self.page
        page.set_viewport_size({"width": 1280, "height": 720})
        page.click('#rail [data-open-settings]')
        page.click('[data-go="rooms"]')
        page.click("#settings [data-edit-rooms]")
        page.click('[data-room-layout="Kitchen"]')
        page.wait_for_selector("#settings", state="hidden")
        page.wait_for_selector(".tiles.editing")
        # Portrait provides room to drag down into unused grid cells.
        page.set_viewport_size({"width": 720, "height": 1280})
        page.wait_for_timeout(100)
        selector = '.room-tile[data-wid="kt-pendant"]'
        before = self.placements(page, ".room-tile")
        state_before = page.locator('.tile[data-id="kt-pendant"]').get_attribute("data-on")
        try:
            self.drag_to_cell(page, selector, 2, 2)
            page.click(selector + " [data-resize]")
            page.click(selector + " [data-resize]")
            self.assertIn("s-2x2", page.get_attribute(selector, "class"))
            moved = self.placements(page, ".room-tile")
            self.assertEqual(moved["kt-pendant"]["row"], "3")
            self.assertEqual(moved["kt-kettle"], before["kt-kettle"])
            self.assertEqual(page.locator('.tile[data-id="kt-pendant"]').get_attribute("data-on"), state_before)
            page.evaluate("""async () => {
              const {store, upsertDevice} = await import('/js/store.js');
              upsertDevice({...store.devices.get('kt-pendant')});
            }""")
            self.assertEqual(self.placements(page, ".room-tile"), moved)
            for handle in page.locator(".tiles.editing .w-resize, .tiles.editing .w-menu").all():
                self.assertGreaterEqual(handle.bounding_box()["width"], 48)
                self.assertGreaterEqual(handle.bounding_box()["height"], 48)
            page.click("[data-room-done]")
            page.wait_for_selector("text=Kitchen layout saved")
            page.reload()
            page.wait_for_selector(selector)
            self.assertEqual(self.placements(page, ".room-tile"), moved)
            page.click('[data-edit-room="Kitchen"]')
            page.click(selector + " [data-room-options]")
            page.click('[data-room-size="1x1"]')
            page.click("[data-room-options-close].btn")
            page.click("[data-room-cancel]")
            self.assertEqual(self.placements(page, ".room-tile"), moved)
            saved = page.evaluate("async () => (await (await import('/js/api.js')).api.state()).settings.room_layouts")
            for width, height in ((393, 852), (1280, 720), (720, 1280)):
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(100)
                self.assert_grid_fits(page, ".room-tile")
            self.assertEqual(self.placements(page, ".room-tile"), moved)
            self.assertEqual(page.evaluate("async () => (await (await import('/js/api.js')).api.state()).settings.room_layouts"), saved)
        finally:
            page.evaluate("async () => (await import('/js/api.js')).api.saveRoomLayout('Kitchen', null)")

    def test_sky_background_follows_the_weather(self):
        source = FakeWeatherSource(temperature=28.4, code=71)                 # snow
        os.environ["HOMEPANEL_WEATHER_URL"] = source.url
        try:
            self.put_settings(weather_enabled=True, latitude=40.7, longitude=-74.0, place_name="New York")
            page = self.home()
            try:
                page.wait_for_function("document.documentElement.dataset.sky === 'snow'")
                self.assertEqual(page.evaluate("document.documentElement.dataset.bg"), "sky")
                self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.sky-snow')).opacity"), "1")
                text = page.inner_text('.widget[data-wid="weather"]')
                self.assertIn("28°", text)
                self.assertIn("New York", text)
                periods = page.evaluate("""async () => { const m = await import('/js/sky.js');
                    return [6, 12, 18, 23].map((h) => m.periodAt(new Date(2026, 0, 5, h, 0), null)); }""")
                self.assertEqual(periods, ["dawn", "day", "dusk", "night"])
            finally:
                page.close()
        finally:
            source.stop()
            os.environ.pop("HOMEPANEL_WEATHER_URL", None)
            self.put_settings(weather_enabled=False, latitude=None, longitude=None, place_name="")

    def test_device_icons_from_name_kind_or_choice(self):
        names = self.page.evaluate("""async () => { const m = await import('/js/icons.js');
            return [["Floor lamp", "light"], ["TV backlight", "light"], ["Kettle plug", "plug"], ["Fridge plug", "plug"],
                    ["Samsung TV", "tv"], ["Robot", "vacuum"], ["Living Room Soundbar", "speaker"], ["TV sound", "speaker"],
                    ["Deebot T8", "vacuum"], ["Hallway", "light"], ["Thing", "other"]]
              .map(([name, kind]) => m.deviceIconName({ name, kind })); }""")
        self.assertEqual(names, ["lamp", "strip", "kettle", "fridge", "tv", "vacuum", "soundbar", "soundbar", "vacuum", "bulb", "power"])
        self.page.click("#open-settings")                                      # pick one in Settings → device
        self.page.click("[data-go=devices]")
        self.page.click("[data-arg=kt-kettle]")
        self.page.click(".icon-choice:has(input[value=heater])")
        self.page.click("[data-save-device]")
        self.page.wait_for_selector("text=Saved")
        try:
            icon = self.page.evaluate("fetch('/api/v1/state').then(r => r.json()).then(s => s.devices.find(d => d.id === 'kt-kettle').icon)")
            self.assertEqual(icon, "heater")
        finally:
            self.page.evaluate("""fetch('/api/v1/devices/kt-kettle', {method: 'PATCH', headers: {'Content-Type': 'application/json'},
                                  body: JSON.stringify({icon: ''})})""")


    # ---------- room sidebar: All rooms, then each room on its own ----------
    def rail_rooms(self, page):
        return page.eval_on_selector_all("#rail .rail-rooms .rail-item", "els => els.map(e => e.querySelector('span').textContent)")

    def shown(self, page):
        return set(page.eval_on_selector_all("#grid .tile", "els => els.map(e => e.dataset.id)"))

    def test_sidebar_lists_each_room_and_shows_only_its_devices(self):
        page = self.open(width=1180, height=820, reduced_motion="reduce")       # a new screen starts on Home
        try:
            page.wait_for_selector("#rail .rail-rooms .rail-item")
            all_ids = set(page.evaluate("fetch('/api/v1/state').then(r => r.json()).then(s => s.devices.map(d => d.id))"))
            self.assertEqual(self.rail_rooms(page), ["All rooms", "Living room", "Bedroom", "Kitchen"])   # room order

            page.click('#rail [data-room="Bedroom"]')
            page.wait_for_selector('#rail [data-room="Bedroom"][aria-selected="true"]')
            self.assertEqual(self.shown(page), {"bd-lamp", "bd-tv", "bd-fan"})                       # only that room
            self.assertEqual(page.inner_text("#title"), "Bedroom")

            page.click('#rail [data-room="Living room"]')
            page.wait_for_selector('#grid .tile[data-id="lr-tv"]')
            self.assertTrue(all(i.startswith("lr-") for i in self.shown(page)))
            self.assertEqual(page.inner_text("#title"), "Living room")
            self.assertEqual(page.locator("#grid .room-head [data-room-off]").count(), 1)          # its own Turn off

            page.click('#rail [data-room="all"]')                                                 # All rooms: everything,
            page.wait_for_selector('#grid .tile[data-id="kt-kettle"]')                            # grouped by room
            self.assertEqual(self.shown(page), all_ids)
            self.assertEqual(page.locator("#grid .room-section").count(), 3)

            page.click('#rail [data-room="Kitchen"]')
            page.wait_for_selector('#grid .tile[data-id="kt-kettle"]')
            page.reload()                                                                         # remembered
            page.wait_for_selector('#rail [data-room="Kitchen"][aria-selected="true"]')
            self.assertEqual(self.shown(page), {"kt-pendant", "kt-kettle", "kt-fridge"})
            self.assertEqual(page.locator("#rail [data-room='']").count(), 0)                    # no "Other" yet

            page.evaluate("""fetch('/api/v1/devices/bd-fan', {method: 'PATCH', headers: {'Content-Type': 'application/json'},
                             body: JSON.stringify({room: ''})})""")
            page.wait_for_selector("#rail [data-room='']")                                        # a device with no room
            self.assertEqual(self.rail_rooms(page)[-1], "Other")
        finally:
            page.evaluate("""fetch('/api/v1/devices/bd-fan', {method: 'PATCH', headers: {'Content-Type': 'application/json'},
                             body: JSON.stringify({room: 'Bedroom'})})""")
            page.close()

    def test_phone_dock_opens_the_same_rooms(self):
        page = self.home(width=393, height=852, is_mobile=True)
        try:
            page.click('#dock [data-nav="rooms"]')
            page.wait_for_selector("[data-room-picker]")
            self.assertEqual(page.locator("[data-room-picker] option").all_text_contents(),
                             ["All rooms", "Living room", "Bedroom", "Kitchen"])
            page.select_option("[data-room-picker]", "Kitchen")
            page.wait_for_function("document.querySelector('[data-room-picker]').value === 'Kitchen'")
            self.assertEqual(self.shown(page), {"kt-pendant", "kt-kettle", "kt-fridge"})
        finally:
            page.close()



@unittest.skipIf(sync_playwright is None, "playwright not installed")
class SignedInRoomsTests(unittest.TestCase):
    """With sign-in on, a member only gets rooms that have devices they can see.
    Demo member Sam sees bd-fan, bd-lamp, bd-tv and kt-pendant: no Living room."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir, sign_in=True).start()
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

    def test_member_sees_only_rooms_with_their_devices(self):
        page = self.browser.new_page(viewport={"width": 1180, "height": 820})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            page.goto(f"{self.server.url}/")
            status = page.evaluate("""fetch('/api/v1/auth/sign-in', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                      body: JSON.stringify({profile_id: 'sam'})}).then(r => r.status)""")
            self.assertEqual(status, 200)
            page.add_init_script("localStorage.setItem('view', '\"home\"')")
            page.reload()
            page.wait_for_selector("#rail .rail-rooms .rail-item")
            rooms = page.eval_on_selector_all("#rail .rail-rooms .rail-item", "els => els.map(e => e.querySelector('span').textContent)")
            self.assertEqual(rooms, ["All rooms", "Bedroom", "Kitchen"])                      # Living room: all hidden
            widget = page.eval_on_selector_all('.widget[data-wid="rooms"] [data-go-room]', "els => els.map(e => e.dataset.goRoom)")
            self.assertEqual(widget, ["Bedroom", "Kitchen"])
            page.click('#rail [data-room="all"]')
            page.wait_for_selector("#grid .tile")
            ids = set(page.eval_on_selector_all("#grid .tile", "els => els.map(e => e.dataset.id)"))
            self.assertEqual(ids, {"bd-fan", "bd-lamp", "bd-tv", "kt-pendant"})
            page.click('#rail [data-room="Kitchen"]')
            page.wait_for_selector('#rail [data-room="Kitchen"][aria-selected="true"]')
            self.assertEqual(page.eval_on_selector_all("#grid .tile", "els => els.map(e => e.dataset.id)"), ["kt-pendant"])
            self.assertEqual(errors, [])
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
