"""Consistent tile/navigation behavior on isolated fixtures, never household devices."""
import os
import shutil
import tempfile
import unittest

from app.core.adapter import Cap, Device, Kind
from tests.helpers import DemoServer

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    if os.environ.get("REQUIRE_UI_TESTS"):
        raise
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class InteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(); cls.server = DemoServer(cls.dir).start()
        svc = cls.server.app.state.service
        for kind in (Kind.SWITCH, Kind.PURIFIER, Kind.OTHER):
            did = "interaction-" + kind
            state = {"online": True, "on": False}
            svc.store.devices[did] = Device(id=did, adapter="demo", name=kind.title(), kind=kind, room="Living room",
                                            caps=[] if kind == Kind.OTHER else [Cap.POWER], state=state)
            svc.adapters["demo"]._state[did] = dict(state)
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as error:
            cls.pw.stop(); cls.server.stop(); shutil.rmtree(cls.dir, ignore_errors=True)
            if os.environ.get("REQUIRE_UI_TESTS"):
                raise
            raise unittest.SkipTest(f"chromium not available: {error}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.server.stop(); shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 720}, has_touch=True, reduced_motion="reduce")
        self.errors, self.commands, self.writes = [], [], []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("request", self.record)
        self.page.add_init_script("localStorage.setItem('view',JSON.stringify('rooms'))")
        self.page.goto(self.server.url); self.page.wait_for_selector(".tile")

    def tearDown(self):
        self.page.close(); self.assertEqual(self.errors, [])

    def record(self, request):
        if request.method == "POST" and request.url.endswith("/command"):
            self.commands.append(request.post_data_json)
        if request.method in ("PUT", "PATCH", "DELETE"):
            self.writes.append(request.url)

    def test_every_device_opens_controls_for_mouse_touch_and_keyboard_without_commands(self):
        page = self.page
        ids = ("lr-lamp", "kt-kettle", "bd-fan", "lr-tv", "lr-soundbar", "lr-vacuum",
               "interaction-switch", "interaction-purifier", "interaction-other")
        for did in ids:
            for method in ("mouse", "touch", "Enter", "Space"):
                with self.subTest(device=did, method=method):
                    opener = page.locator(f'.tile[data-id="{did}"] [data-more]')
                    opener.scroll_into_view_if_needed()
                    if method == "mouse":
                        opener.locator(".tile-name").click()
                    elif method == "touch":
                        box = opener.bounding_box()
                        page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    else:
                        opener.focus(); opener.press(" " if method == "Space" else method)
                    page.wait_for_selector(f'#sheet[data-device-id="{did}"]:not([hidden])')
                    self.assertEqual(self.commands, [])
                    page.locator("#sheet .speaker-head [data-close], #sheet .device-head [data-close]").click()
                    page.wait_for_selector("#sheet", state="hidden")
        self.assertEqual(page.locator('.tile[data-id="interaction-other"] [data-quick-action]').count(), 0)

    def test_explicit_quick_actions_act_once_without_opening_and_preserve_pending_intent(self):
        page = self.page
        button = page.locator('.tile[data-id="kt-kettle"] [data-quick-action="power"]')
        button.scroll_into_view_if_needed()
        intent = button.get_attribute("data-value") == "true"
        box = button.bounding_box()
        page.mouse.move(box["x"] + 24, box["y"] + 24); page.mouse.down()
        page.evaluate("""async () => {
          const {store,upsertDevice}=await import('/js/store.js'),d=store.devices.get('kt-kettle');
          window.heldQuick=document.querySelector('.tile[data-id="kt-kettle"] [data-quick-action]');
          upsertDevice({...d,state:{...d.state,on:!d.state.on}});
        }""")
        self.assertTrue(button.evaluate("e=>e===window.heldQuick"))
        page.mouse.up()
        page.wait_for_function("!document.querySelector('.tile[data-id=\"kt-kettle\"]').classList.contains('busy')")
        self.assertEqual(self.commands, [{"action": "power", "value": intent}])
        self.assertTrue(page.locator("#sheet").is_hidden())
        button.focus(); button.press(" ")
        page.wait_for_function("!document.querySelector('.tile[data-id=\"kt-kettle\"]').classList.contains('busy')")
        self.assertEqual(len(self.commands), 2)
        self.assertTrue(button.evaluate("e=>e===document.activeElement"))
        button.scroll_into_view_if_needed(); box = button.bounding_box()
        page.touchscreen.tap(box["x"] + 24, box["y"] + 24)
        page.wait_for_function("!document.querySelector('.tile[data-id=\"kt-kettle\"]').classList.contains('busy')")
        self.assertEqual(len(self.commands), 3)
        self.assertTrue(page.locator("#sheet").is_hidden())
        self.assertGreaterEqual(button.bounding_box()["width"], 48)
        self.assertGreaterEqual(button.bounding_box()["height"], 48)

    def test_identical_and_changed_updates_preserve_tile_controls_focus_and_scroll(self):
        page = self.page
        page.locator('.tile[data-id="kt-fridge"]').scroll_into_view_if_needed()
        result = page.evaluate("""async () => {
          const {store,reload,upsertDevice}=await import('/js/store.js');
          const tile=document.querySelector('.tile[data-id="kt-fridge"]'),button=tile.querySelector('[data-more]'),picture=tile.querySelector('.tile-icon');
          button.focus({preventScroll:true});const scroll=scrollY;
          for(let i=0;i<8;i++)upsertDevice({...store.devices.get('kt-fridge')});
          for(let i=0;i<8;i++)await reload();
          const d=store.devices.get('kt-fridge');upsertDevice({...d,state:{...d.state,on:!d.state.on}});
          return {tile:tile===document.querySelector('.tile[data-id="kt-fridge"]'),button:button===tile.querySelector('[data-more]'),
            picture:picture===tile.querySelector('.tile-icon'),focus:document.activeElement===button,scroll:Math.abs(scrollY-scroll)<1};
        }""")
        self.assertEqual(result, dict(tile=True, button=True, picture=True, focus=True, scroll=True))
        self.assertEqual(self.commands, [])

    def test_quick_action_pending_error_and_offline_states_are_explicit(self):
        page = self.page
        requests = []
        page.route("**/devices/kt-kettle/command", lambda route: requests.append(route))
        button = page.locator('.tile[data-id="kt-kettle"] [data-quick-action]')
        button.click()
        page.wait_for_selector('.tile[data-id="kt-kettle"][aria-busy="true"]')
        self.assertTrue(button.is_disabled())
        self.assertEqual(page.inner_text('.tile[data-id="kt-kettle"] .tile-status'), "Updating...")
        page.evaluate("async()=> (await import('/js/store.js')).reload()")
        button.evaluate("e=>e.click()")
        self.assertEqual(len(self.commands), 1)
        requests.pop().fulfill(status=400, json={"error": "The device is busy. Try again."})
        page.wait_for_selector("text=The device is busy. Try again.")
        page.wait_for_selector('.tile[data-id="kt-kettle"][aria-busy="false"]')
        self.assertTrue(page.locator("#sheet").is_hidden())
        page.evaluate("""async()=>{const {store,upsertDevice}=await import('/js/store.js'),d=store.devices.get('kt-kettle');
          upsertDevice({...d,state:{...d.state,online:false}});}""")
        self.assertTrue(button.is_disabled())
        page.locator('.tile[data-id="kt-kettle"] [data-more]').click()
        page.wait_for_selector("#sheet [data-refresh]")
        self.assertEqual(len(self.commands), 1)

    def test_member_has_the_same_picker_and_open_logic_without_admin_or_hidden_devices(self):
        page = self.page
        page.evaluate("""async()=>{await(await import('/js/api.js')).api.signIn({profile_id:'sam'});
          await(await import('/js/store.js')).reload();}""")
        page.set_viewport_size({"width": 393, "height": 852})
        page.wait_for_selector("[data-room-picker]")
        self.assertEqual(page.locator("[data-room-picker] option").all_text_contents(), ["All rooms", "Bedroom", "Kitchen"])
        self.assertEqual(page.locator("[data-edit-rooms], [data-room-name], [data-room-grip]").count(), 0)
        self.assertEqual(page.locator('.tile[data-id="lr-lamp"]').count(), 0)
        page.locator('.tile[data-id="bd-fan"] [data-more]').click()
        page.wait_for_selector('#sheet[data-device-id="bd-fan"]:not([hidden])')
        self.assertEqual(self.commands, [])
        self.assertTrue(page.locator("#sheet [data-edit]").is_hidden())

    def test_adaptive_room_picker_and_edit_drafts_keep_route_focus_and_selection(self):
        page = self.page
        page.click('#rail [data-room="Bedroom"]'); page.click("#rail [data-edit-rooms]")
        field = page.locator('#rail [data-room-name="Bedroom"]')
        field.fill("Draft bedroom"); field.evaluate("e=>e.setSelectionRange(2,5)")
        page.set_viewport_size({"width": 393, "height": 852})
        page.wait_for_function("document.activeElement?.matches('#rooms [data-room-name=\"Bedroom\"]')")
        phone = page.locator('#rooms [data-room-name="Bedroom"]')
        self.assertEqual(phone.input_value(), "Draft bedroom")
        self.assertEqual(phone.evaluate("e=>[e.selectionStart,e.selectionEnd]"), [2, 5])
        page.evaluate("async()=> (await import('/js/store.js')).reload()")
        self.assertTrue(phone.evaluate("e=>e===document.activeElement"))
        phone.press("Escape"); page.click("#room-tools [data-edit-rooms]")
        picker = page.locator("[data-room-picker]")
        self.assertEqual(picker.input_value(), "Bedroom")
        self.assertTrue(page.locator("#rooms").is_hidden())
        picker.focus(); picker.select_option("Kitchen")
        self.assertEqual(page.inner_text("#title"), "Kitchen")
        page.set_viewport_size({"width": 1280, "height": 720})
        page.wait_for_function("document.activeElement?.matches('#rail [data-room=\"Kitchen\"]')")
        self.assertEqual(page.get_attribute('#rail [data-room="Kitchen"]', "aria-selected"), "true")
        self.assertEqual(self.writes, [])
        self.assertEqual(self.commands, [])

    def test_inline_add_room_draft_survives_rotation_and_requires_explicit_completion(self):
        page = self.page
        original = page.request.get(self.server.url + "/api/v1/state").json()["rooms"]
        try:
            page.click("#rail [data-edit-rooms]"); page.click("#rail [data-add-room]")
            page.fill("#rail [data-room-add] input", "Office")
            page.locator("#rail [data-room-add] input").evaluate("e=>e.setSelectionRange(1,4)")
            page.set_viewport_size({"width": 720, "height": 1280})
            page.wait_for_function("document.activeElement?.matches('#room-tools [data-room-add] input')")
            self.assertEqual(page.input_value("#room-tools [data-room-add] input"), "Office")
            self.assertEqual(page.locator("#room-tools [data-room-add] input").evaluate("e=>[e.selectionStart,e.selectionEnd]"), [1, 4])
            page.click("#room-tools [data-edit-rooms]")
            page.wait_for_selector("text=Add or cancel the new room first.")
            self.assertEqual(self.writes, [])
            page.click("#room-tools [data-room-add] button[type=submit]")
            page.wait_for_selector('#rooms [data-room-name="Office"]')
            page.click("#room-tools [data-edit-rooms]"); page.reload()
            page.wait_for_selector('[data-room-picker] option[value="Office"]', state="attached")
            self.assertEqual(page.input_value("[data-room-picker]"), "Office")
            self.assertEqual(page.locator("[data-room-grip], [data-room-name]").count(), 0)
        finally:
            page.request.put(self.server.url + "/api/v1/rooms", data={"rooms": original})

    def test_settings_room_entry_survives_snapshots_and_has_explicit_cancel(self):
        page = self.page
        page.click("#rail [data-open-settings]"); page.click('[data-go="rooms"]'); page.click("#settings [data-edit-rooms]")
        field = page.locator("#settings [data-room-add] input")
        field.fill("Unsubmitted room"); field.evaluate("e=>e.setSelectionRange(2,5)")
        page.evaluate("async()=> (await import('/js/store.js')).reload()")
        self.assertEqual(field.input_value(), "Unsubmitted room")
        self.assertTrue(field.evaluate("e=>e===document.activeElement"))
        self.assertEqual(field.evaluate("e=>[e.selectionStart,e.selectionEnd]"), [2, 5])
        page.click("#settings [data-back]")
        page.wait_for_selector("text=Add or cancel the new room first.")
        page.click("#settings [data-room-add-cancel]")
        self.assertEqual(field.input_value(), "")
        self.assertEqual(self.writes, [])

    def test_saved_no_blur_and_secondary_controls_remain_capability_specific(self):
        page = self.page
        page.set_viewport_size({"width": 393, "height": 852})
        page.evaluate("""async()=>{const {store,emit}=await import('/js/store.js');store.settings.glass_effect=false;emit('all');}""")
        self.assertEqual(page.locator(".dock-bar").evaluate("e=>getComputedStyle(e).backdropFilter"), "none")
        page.locator('.tile[data-id="lr-ceiling"] [data-more]').click()
        section = page.locator('[data-control-section="light-color"]')
        self.assertFalse(section.evaluate("e=>e.open"))
        self.assertEqual(section.locator("summary").inner_text(), "White tone")
        section.locator("summary").click()
        self.assertTrue(page.locator("#ct").is_visible())
        page.click("#sheet [data-close]")
        page.locator('.tile[data-id="lr-soundbar"] [data-more]').click()
        self.assertTrue(page.locator("[data-speaker-volume]").is_visible())
        self.assertFalse(page.locator('[data-control-section="speaker-options"]').evaluate("e=>e.open"))
        self.assertEqual(self.commands, [])
