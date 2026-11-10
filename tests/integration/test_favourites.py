"""Favourites on Home, the volume level on wide tiles and "when a device turns on" automations."""
import os
import shutil
import tempfile
import time
import unittest

from tests.helpers import DemoServer

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    if os.environ.get("REQUIRE_UI_TESTS"):
        raise
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class FavouritesTests(unittest.TestCase):
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
        self.errors, self.commands = [], []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("request", lambda r: self.commands.append(r.post_data_json)
                     if r.method == "POST" and r.url.endswith("/command") else None)
        self.api = self.server.url + "/api/v1"
        self.layout = self.page.request.get(self.api + "/state").json()["settings"]["home_layout"]
        self.page.goto(self.server.url)
        self.page.wait_for_selector(".widget")

    def tearDown(self):
        self.page.request.put(self.api + "/profiles/me/layout", data={"home_layout": self.layout})
        self.page.close()
        self.assertEqual(self.errors, [])

    def save_layout(self, extra):
        widgets = [{k: v for k, v in w.items() if k != "positions"} for w in self.layout["widgets"]]
        r = self.page.request.put(self.api + "/profiles/me/layout", data={"home_layout": {"version": 3, "widgets": widgets + extra}})
        self.assertEqual(r.status, 200, r.text())
        self.page.reload()
        self.page.wait_for_selector(".widget")

    def test_favourites_open_controls_and_only_the_quick_button_sends_a_command(self):
        page = self.page
        page.request.post(f"{self.api}/devices/bd-lamp/command", data={"action": "power", "value": False})   # a known start
        self.save_layout([{"id": "favs", "type": "favourites", "size": "2x2", "hidden": False,
                           "options": {"devices": ["lr-vacuum", "bd-lamp", "gone"]}}])
        rows = page.locator(".t-favourites .w-favs .tile")
        rows.first.wait_for()
        self.assertEqual(rows.evaluate_all("els => els.map(e => e.dataset.id)"), ["lr-vacuum", "bd-lamp"])   # chosen order
        lamp = page.locator('.w-favs .tile[data-id="bd-lamp"]')
        self.assertEqual(lamp.locator(".tile-status").inner_text(), "Off")           # no room: the names differ
        box, quick = lamp.bounding_box(), lamp.locator(".tile-quick").bounding_box()
        self.assertLess(box["height"], 80)                               # a compact row, not a full tile
        self.assertGreaterEqual(min(quick["width"], quick["height"]), 48)
        self.assertGreaterEqual(lamp.locator(".tile-open").bounding_box()["height"], 48)
        self.assertTrue(page.locator(".w-favs").evaluate("e => e.scrollWidth <= e.clientWidth"))

        lamp.locator(".tile-open").click()                               # the name opens the controls
        page.wait_for_selector("#sheet:not([hidden])")
        self.assertEqual(self.commands, [])
        page.keyboard.press("Escape")
        page.wait_for_selector("#sheet", state="hidden")

        lamp.locator(".tile-quick").click()                              # the power button is the only command
        page.wait_for_function("""() => document.querySelector('.w-favs .tile[data-id="bd-lamp"]').dataset.on === 'true'""")
        self.assertEqual(self.commands, [{"action": "power", "value": True}])
        self.assertRegex(lamp.locator(".tile-status").inner_text(), r"^On")
        # A long name takes a second line instead of being cut; a shared name brings the room back.
        page.evaluate("""async () => {
          const {store, upsertDevice} = await import('/js/store.js'), home = await import('/js/home.js');
          upsertDevice({...store.devices.get('lr-vacuum'), name: 'Bedside lamp with a very long name'});
          upsertDevice({...store.devices.get('bd-lamp'), name: 'Bedside lamp with a very long name'});
          home.refreshHomeParts(['favourites']);
        }""")
        page.wait_for_function("""() => document.querySelector('.w-favs .tile[data-id="bd-lamp"] .tile-status').textContent.startsWith('Bedroom · ')""")
        name = lamp.locator(".tile-name")
        self.assertTrue(name.evaluate("e => e.scrollWidth <= e.clientWidth"))
        self.assertGreater(name.bounding_box()["height"], 30)                # two lines
        self.assertLess(lamp.bounding_box()["height"], 80)
        self.assertEqual(page.locator("#sheet:not([hidden])").count(), 0)

    def test_favourites_are_added_and_chosen_in_edit_mode(self):
        page = self.page
        page.click("#edit-home")
        page.click("[data-add-widget]")
        page.click("[data-add-favourites]")
        widget = page.locator(".widget.t-favourites")
        widget.wait_for()
        first = widget.locator(".tile").evaluate_all("els => els.map(e => e.dataset.id)")
        self.assertTrue(0 < len(first) <= 8)                             # nothing chosen yet: the first few devices
        self.assertEqual(widget.locator(".tile-quick:visible").count(), 0)   # no commands while arranging
        widget.locator("[data-menu]").click()
        page.check('.fav-pick input[value="kt-kettle"]')
        page.check('.fav-pick input[value="lr-tv"]')
        self.assertEqual(widget.locator(".tile").evaluate_all("els => els.map(e => e.dataset.id)"), ["kt-kettle", "lr-tv"])
        page.click(".wmenu [data-menu-close]")
        page.click("[data-edit-done]")
        page.wait_for_selector("#home:not(.editing) .t-favourites .tile-quick")
        saved = page.request.get(self.api + "/state").json()["settings"]["home_layout"]["widgets"]
        self.assertEqual([w["options"] for w in saved if w["type"] == "favourites"], [{"devices": ["kt-kettle", "lr-tv"]}])
        self.assertEqual(self.commands, [])

    def test_wide_media_tile_shows_its_volume_level(self):
        page = self.page
        page.evaluate("async () => { const s = await import('/js/store.js'); s.setRoom('Living room'); s.setView('rooms'); }")
        bar = page.locator('#grid .tile[data-id="lr-soundbar"]')
        bar.wait_for()
        level = bar.locator(".tile-vol")
        self.assertEqual(level.inner_text(), "12")
        self.assertEqual(level.get_attribute("aria-label"), "Volume 12%")
        page.evaluate("""async () => {
          const {store, upsertDevice} = await import('/js/store.js'), d = store.devices.get('lr-soundbar');
          upsertDevice({...d, state: {...d.state, volume: 31}});
        }""")
        page.wait_for_function("""() => document.querySelector('#grid .tile[data-id="lr-soundbar"] .tile-vol')?.textContent === '31'""")
        page.evaluate("""async () => {
          const {store, upsertDevice} = await import('/js/store.js'), d = store.devices.get('lr-soundbar');
          upsertDevice({...d, state: {...d.state, on: false}});
        }""")
        page.wait_for_selector('#grid .tile[data-id="lr-soundbar"]:not(.on)')
        self.assertEqual(bar.locator(".tile-vol, [data-act]").count(), 0)

    def test_automation_runs_when_a_device_turns_on(self):
        page = self.page
        page.click("[data-open-settings]:visible")
        page.click("[data-go=automations]")
        page.click('[data-go="automation-new"]')
        form = page.locator("[data-auto-form]")
        self.assertTrue(form.locator('[data-show="watch"]').is_hidden())
        form.locator("select[name=when]").select_option("device_on")
        self.assertTrue(form.locator('[data-show="watch"]').is_visible())
        self.assertTrue(form.locator('[data-show="time"]').is_hidden())
        form.locator("select[name=watch_id]").select_option("bd-tv")
        form.locator("select[name=do]").select_option("device")
        form.locator("select[name=device_id]").select_option("bd-lamp")
        form.locator("button[type=submit]").click()
        page.wait_for_selector("text=When LG TV turns on")
        autos = page.request.get(self.api + "/automations").json()["automations"]
        mine = next(a for a in autos if a["when"]["type"] == "device")
        try:
            self.assertEqual(mine["when"], {"type": "device", "device_id": "bd-tv", "event": "on"})
            self.assertEqual(mine["name"], "Bedside lamp on when LG TV turns on")
            state = lambda did: next(d for d in page.request.get(self.api + "/state").json()["devices"] if d["id"] == did)["state"]  # noqa: E731
            for did in ("bd-tv", "bd-lamp"):                             # both known to be off first
                page.request.post(f"{self.api}/devices/{did}/command", data={"action": "power", "value": False})
            page.wait_for_timeout(2000)                                  # the confirming re-read has landed
            self.assertFalse(state("bd-lamp")["on"])
            page.request.post(f"{self.api}/devices/bd-tv/command", data={"action": "power", "value": True})
            deadline = time.time() + 5
            while time.time() < deadline and not state("bd-lamp").get("on"):
                page.wait_for_timeout(100)
            self.assertTrue(state("bd-lamp")["on"])
        finally:
            page.request.delete(f"{self.api}/automations/{mine['id']}")


if __name__ == "__main__":
    unittest.main()
