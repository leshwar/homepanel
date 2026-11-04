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

    def tab(self, name):
        return self.page.locator("#rooms .room", has_text=name)

    def swipe(self, dx):
        box = self.page.locator("#grid .tile").first.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.mouse.move(x + dx, y + 4, steps=8)
        self.page.mouse.up()

    def shown_ids(self):
        return set(self.page.eval_on_selector_all("#grid .tile", "els => els.map(e => e.dataset.id)"))

    def test_room_tabs_switch_swipe_and_remember(self):
        names = self.page.eval_on_selector_all("#rooms .room", "els => els.map(e => e.firstChild.textContent)")
        self.assertEqual(names, ["All", "Living room", "Bedroom", "Kitchen"])
        for b in self.page.locator("#rooms .room").all():
            self.assertGreaterEqual(b.bounding_box()["height"], 48)            # touch target
        self.assertEqual(self.page.locator(".room-section").count(), 3)       # "All" = every room, with headings

        self.tab("Kitchen").click()
        self.page.wait_for_function("document.querySelector('#rooms [aria-selected=true]').textContent.startsWith('Kitchen')")
        self.assertEqual(self.shown_ids(), {"kt-pendant", "kt-kettle", "kt-fridge"})
        self.assertIn("1 of 3 on", self.page.locator(".room-head").inner_text())

        self.page.reload()                                                     # the chosen room is remembered
        self.page.wait_for_selector(".tile")
        self.assertEqual(self.shown_ids(), {"kt-pendant", "kt-kettle", "kt-fridge"})

        kettle_on = self.tile("kt-kettle").evaluate("el => el.classList.contains('on')")
        self.swipe(200)                                                        # swipe right = previous room
        self.page.wait_for_function("document.querySelector('#rooms [aria-selected=true]').textContent.startsWith('Bedroom')")
        self.assertEqual(self.shown_ids(), {"bd-lamp", "bd-tv", "bd-fan"})
        self.swipe(-200)                                                       # and back
        self.page.wait_for_function("document.querySelector('#rooms [aria-selected=true]').textContent.startsWith('Kitchen')")
        self.assertEqual(kettle_on, self.tile("kt-kettle").evaluate("el => el.classList.contains('on')"))  # not a tap

        self.tab("All").click()
        self.page.locator(".room-title", has_text="Bedroom").click()          # a heading in "All" opens its tab
        self.page.wait_for_function("document.querySelector('#rooms [aria-selected=true]').textContent.startsWith('Bedroom')")

    def test_other_tab_nudges_to_pick_a_room_and_turns_off_just_those(self):
        api = "(path, body, method = 'POST') => fetch('/api/v1' + path, {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})"
        self.page.evaluate(f"({api})('/devices/bd-fan', {{room: ''}}, 'PATCH')")
        try:
            self.page.evaluate(f"({api})('/devices/bd-fan/command', {{action: 'power', value: true}})")
            self.page.reload()
            self.page.wait_for_selector("#rooms .room:has-text('Other')")
            self.tab("Other").click()
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

    def test_home_page_clocks_device_widgets_and_rooms(self):
        page = self.home(timezone_id="America/Denver")
        try:
            page.wait_for_selector('.widget[data-wid="clock"] [data-time]')
            for wid, tz in (("zone-in", "Asia/Kolkata"), ("zone-us", "America/Denver")):   # US = this screen's zone
                zone = page.locator(f'.widget[data-wid="{wid}"] .w-zone')
                self.assertEqual(zone.get_attribute("data-zone"), tz)
                expected = page.evaluate(f"new Date().toLocaleTimeString([], {{timeZone: '{tz}', hour: 'numeric', minute: '2-digit'}})")
                self.assertTrue(expected.startswith(zone.locator("[data-time]").inner_text()))
            self.assertIn("India", page.inner_text('.widget[data-wid="zone-in"]'))

            lamp = page.locator('.widget[data-wid="dev-lr-lamp"] .tile')
            was_on = lamp.get_attribute("data-on")
            lamp.locator(".tile-name").click()                                  # tap = on/off
            page.wait_for_function(f"document.querySelector('.widget[data-wid=\"dev-lr-lamp\"] .tile').dataset.on !== '{was_on}'")
            lamp.locator(".tile-name").click()                                  # and back
            page.wait_for_function(f"document.querySelector('.widget[data-wid=\"dev-lr-lamp\"] .tile').dataset.on === '{was_on}'")
            self.long_press(page, '.widget[data-wid="dev-lr-lamp"] .tile')      # long press = controls, no toggle
            page.wait_for_selector("#sheet:not([hidden]) #bri")
            self.assertEqual(lamp.get_attribute("data-on"), was_on)
            page.keyboard.press("Escape")
            page.wait_for_selector("#sheet", state="hidden")

            page.click('[data-go-room="Kitchen"]')                              # Rooms widget opens that room
            page.wait_for_function("document.documentElement.dataset.view === 'rooms'")
            page.wait_for_selector('#rooms [aria-selected="true"]:has-text("Kitchen")')
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
        sizes = [(393, 852, True), (820, 1180, False), (1180, 820, False), (720, 1280, False), (1280, 720, False)]
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
                    if wide:
                        page.click('#rail [data-room="Kitchen"]')
                        page.wait_for_selector('#grid .tile[data-id="kt-kettle"]')
                        self.assertEqual(page.inner_text("#title"), "Kitchen")
                        self.assertTrue(page.locator("#rooms").is_hidden())
                        page.click('#rail [data-nav="home"]')
                        page.wait_for_selector(".widget")
                finally:
                    page.close()

    def test_edit_home_page_hide_resize_move_and_save_for_every_screen(self):
        page = self.home()
        try:
            self.long_press(page, '.widget[data-wid="clock"]')                 # long press the page = edit
            page.wait_for_selector(".home.editing .editbar")
            page.click('.widget[data-wid="scenes"] [data-hide]')
            page.click('.widget[data-wid="weather"] [data-resize]')            # a tap on the corner: next size
            self.assertIn("s-2x2", page.get_attribute('.widget[data-wid="weather"]', "class"))
            page.click('.widget[data-wid="zone-us"] [data-menu]')
            page.select_option("[data-zone-pick]", "America/Chicago")
            page.click('[data-size-pick="2x1"]')
            page.click(".wmenu button.btn[data-menu-close]")
            a = page.locator('.widget[data-wid="clock"]').bounding_box()       # hold the clock and drag it down
            t = page.locator('.widget[data-wid="rooms"]').bounding_box()
            page.mouse.move(a["x"] + 50, a["y"] + 50)
            page.mouse.down()
            page.wait_for_timeout(350)
            page.mouse.move(t["x"] + t["width"] / 2, t["y"] + t["height"] / 2, steps=10)
            page.mouse.up()
            self.assertNotEqual(self.order(page)[0], "clock")
            moved = self.order(page)
            page.click("[data-edit-done]")
            page.wait_for_selector("text=Home page saved")

            other = self.home(width=1180, height=820)                           # another screen: same Home page
            try:
                self.assertEqual(self.order(other), moved)
                self.assertEqual(other.locator('.widget[data-wid="scenes"]').count(), 0)
                self.assertIn("s-2x2", other.get_attribute('.widget[data-wid="weather"]', "class"))
                self.assertIn("s-2x1", other.get_attribute('.widget[data-wid="zone-us"]', "class"))
                self.assertEqual(other.get_attribute('.widget[data-wid="zone-us"] .w-zone', "data-zone"), "America/Chicago")
            finally:
                other.close()

            page.click("#edit-home")                                           # Cancel puts it all back
            page.click('.widget[data-wid="weather"] [data-hide]')
            page.click("[data-add-widget]")                                    # hidden widgets can come back
            page.wait_for_selector('.wmenu [data-unhide="scenes"]')
            page.click('.wmenu [data-unhide="scenes"]')
            page.wait_for_selector('.widget[data-wid="scenes"]')
            page.click("[data-edit-cancel]")
            page.wait_for_selector(".home:not(.editing)")
            self.assertEqual(self.order(page), moved)
        finally:
            page.evaluate("fetch('/api/v1/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: '{\"home_layout\": null}'})")
            page.close()

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
                    ["Samsung TV", "tv"], ["Robot", "vacuum"], ["Hallway", "light"], ["Thing", "other"]]
              .map(([name, kind]) => m.deviceIconName({ name, kind })); }""")
        self.assertEqual(names, ["lamp", "strip", "kettle", "fridge", "tv", "vacuum", "bulb", "power"])
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


if __name__ == "__main__":
    unittest.main()
