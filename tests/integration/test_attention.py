"""What the panel says when a device needs a person, a room is empty, or nothing is on."""
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

SET_STATE = """async ([id, patch, drop]) => {
  const {store, upsertDevice} = await import('/js/store.js'), d = store.devices.get(id);
  const state = {...d.state, ...patch};
  for (const key of drop || []) delete state[key];
  upsertDevice({...d, state});
}"""
SHOW_ROOM = "async room => { const s = await import('/js/store.js'); s.setRoom(room); s.setView('rooms'); }"


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class AttentionTests(unittest.TestCase):
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
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 720}, reduced_motion="reduce")
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.goto(self.server.url)
        self.page.wait_for_selector(".tile, .widget")

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def test_vacuum_tile_shows_problems_and_worn_parts(self):
        page = self.page
        page.evaluate(SHOW_ROOM, "all")
        tile = page.locator('#grid .tile[data-id="lr-vacuum"]')
        tile.wait_for()
        self.assertEqual(tile.locator(".tile-status").inner_text(), "Docked, 100%")
        self.assertNotIn("attn", tile.get_attribute("class"))
        resting = tile.locator(".tile-status").evaluate("e => getComputedStyle(e).color")

        page.evaluate(SET_STATE, ["lr-vacuum", {"problem": "The dirty water tank is full. Empty it and put it back."}, []])
        page.wait_for_selector('#grid .tile.attn[data-id="lr-vacuum"]')
        self.assertEqual(tile.locator(".tile-status").inner_text(), "Needs attention")
        self.assertRegex(page.inner_text("#subtitle"), r"^\d+ of \d+ on · 1 needs attention$")      # the page header says so too
        self.assertIn("Needs attention", tile.locator(".tile-open").get_attribute("aria-label"))
        self.assertNotEqual(tile.locator(".tile-status").evaluate("e => getComputedStyle(e).color"), resting)

        page.evaluate(SET_STATE, ["lr-vacuum", {"parts": [{"id": "tray", "name": "Mop washing tray", "percent": 0}]}, ["problem"]])
        page.wait_for_function("""() => document.querySelector('#grid .tile[data-id="lr-vacuum"] .tile-status').textContent === 'Maintenance due'""")
        self.assertIn("attn", tile.get_attribute("class"))

        page.evaluate(SET_STATE, ["lr-vacuum", {"parts": []}, []])
        page.wait_for_selector('#grid .tile[data-id="lr-vacuum"]:not(.attn)')
        self.assertEqual(tile.locator(".tile-status").inner_text(), "Docked, 100%")
        self.assertNotIn("attention", page.inner_text("#subtitle"))

    def test_phone_room_heading_keeps_its_status_and_touch_targets(self):
        page = self.page
        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate(SHOW_ROOM, "all")
        head = page.locator('#grid .room-head[data-head="Living room"]')
        head.wait_for()
        status = head.locator(".room-status")
        self.assertRegex(status.inner_text(), r"^(\d+ of \d+ on|Everything is off)$")
        self.assertTrue(status.evaluate("e => e.scrollWidth <= e.clientWidth"))             # not cut to "5 of…"
        self.assertGreater(status.bounding_box()["y"], head.locator(".room-title").bounding_box()["y"] + 20)   # on its own line
        edit = head.locator("[data-edit-room]")
        box = edit.bounding_box()
        self.assertGreaterEqual(min(box["width"], box["height"]), 48)
        self.assertLess(box["width"], 80)                                                   # just the pencil
        self.assertEqual(edit.get_attribute("aria-label"), "Edit Living room tiles")
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        page.set_viewport_size({"width": 1280, "height": 720})                              # wide screens keep the words
        self.assertGreater(edit.bounding_box()["width"], 100)

    def test_home_widgets_explain_themselves_before_they_are_set_up(self):
        page = self.page
        api = self.server.url + "/api/v1"
        layout = page.request.get(api + "/state").json()["settings"]["home_layout"]
        try:
            widgets = [{k: v for k, v in w.items() if k != "positions"} for w in layout["widgets"]]
            widgets.append({"id": "photos-1", "type": "photos", "size": "2x2", "hidden": False, "options": {}})
            r = page.request.put(api + "/profiles/me/layout", data={"home_layout": {"version": 3, "widgets": widgets}})
            self.assertEqual(r.status, 200, r.text())
            page.reload()
            page.wait_for_selector(".w-photos.empty")
            self.assertEqual(page.locator(".w-scenes .w-hint").count(), 0)          # scenes exist: no explanation needed
            page.evaluate("""async () => {                                          // a household with none saved yet
              const {store} = await import('/js/store.js'), home = await import('/js/home.js');
              store.scenes = []; home.refreshHomeParts(['scenes']);
            }""")
            hint = page.locator(".w-scenes .w-hint")
            self.assertIn("save that as a scene", hint.inner_text())
            self.assertTrue(hint.is_visible())
            self.assertTrue(page.locator(".w-scenes [data-new-scene]").is_visible())
            # Photos with no library: the widget's own glass, not an opaque dark block over it.
            for selector in (".w-photos.empty", ".w-photos.empty .photo-placeholder"):
                self.assertEqual(page.locator(selector).evaluate("e => getComputedStyle(e).backgroundColor"), "rgba(0, 0, 0, 0)")
            self.assertIn("Connect a photo library", page.locator(".photo-placeholder").inner_text())
            self.assertGreaterEqual(page.locator("[data-photo-settings]").bounding_box()["height"], 48)
        finally:
            page.request.put(api + "/profiles/me/layout", data={"home_layout": layout})

    def test_empty_room_is_one_line_in_all_rooms_and_a_full_page_alone(self):
        page = self.page
        rooms = page.request.get(self.server.url + "/api/v1/state").json()["rooms"]
        try:
            page.request.put(self.server.url + "/api/v1/rooms", data={"rooms": [*rooms, "Guest room"]})
            page.evaluate("async () => (await import('/js/store.js')).reload()")
            page.evaluate(SHOW_ROOM, "all")
            section = page.locator('#grid .room-section[aria-label="Guest room"]')
            section.wait_for()
            self.assertEqual(section.locator(".room-status").inner_text(), "No devices yet")
            self.assertEqual(section.locator(".room-empty").count(), 0)
            add = section.locator(".room-head [data-add-device]")
            self.assertEqual(add.get_attribute("aria-label"), "Add a device to Guest room")
            self.assertGreaterEqual(add.bounding_box()["height"], 48)
            self.assertLess(section.bounding_box()["height"], 120)
            other = page.locator('#grid .room-section[aria-label="Living room"]')
            self.assertEqual(other.locator(".room-head [data-add-device]").count(), 0)
            self.assertRegex(other.locator(".room-status").inner_text(), r"Everything is off|\d+ of \d+ on")

            page.evaluate(SHOW_ROOM, "Guest room")
            page.wait_for_selector("#grid .room-empty [data-add-device]")
            self.assertEqual(page.locator("#grid .room-status").inner_text(), "No devices yet")
            self.assertEqual(page.locator("#grid .room-head [data-add-device]").count(), 0)
        finally:
            page.request.put(self.server.url + "/api/v1/rooms", data={"rooms": rooms})

    def test_all_off_stops_looking_active_when_nothing_is_on(self):
        page = self.page
        page.evaluate(SET_STATE, ["lr-lamp", {"on": True}, []])
        page.wait_for_selector("#all-off:not(.idle)")
        lit = page.locator("#all-off .i").evaluate("e => getComputedStyle(e).color")
        page.evaluate("""async () => {
          const {store, upsertDevice} = await import('/js/store.js');
          for (const d of [...store.devices.values()]) upsertDevice({...d, state: {...d.state, on: false}});
        }""")
        page.wait_for_selector("#all-off.idle")
        self.assertNotEqual(page.locator("#all-off .i").evaluate("e => getComputedStyle(e).color"), lit)
        self.assertTrue(page.locator("#all-off").is_enabled())           # still works if the picture was stale

    def test_tv_in_standby_has_no_unknown_mute_button(self):
        page = self.page
        page.evaluate(SET_STATE, ["lr-tv", {"on": False}, ["muted"]])
        page.evaluate("async id => (await import('/js/sheet.js')).openDevice(id)", "lr-tv")
        page.wait_for_selector("#sheet:not([hidden]) [data-power]")
        self.assertEqual(page.locator("#sheet [data-mute]").count(), 0)
        self.assertNotIn("Unknown", page.locator("#sheet").inner_text())


if __name__ == "__main__":
    unittest.main()
