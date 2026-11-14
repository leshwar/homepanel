"""Device-panel usability and command safety on isolated household fixtures."""
import itertools
import io
import os
import shutil
import tempfile
import unittest

from PIL import Image

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
        self.page.evaluate("""async () => {
          const {upsertDevice} = await import('/js/store.js');
          upsertDevice({id:'test-purifier', name:'Air purifier with a long room name', kind:'purifier',
            caps:['power','air_quality','filter_life','fan_mode','fan_speed'],
            meta:{fan_modes:[{id:'auto',name:'Automatic'},{id:'manual',name:'Manual'}],
                  fan_speeds:[{id:'1',name:'Low'},{id:'3',name:'High'}]},
            state:{online:true,on:true,pm25:12,air_quality:'Good',filter_life:80,fan_mode:'auto'}});
        }""")

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
            for size, (w, h) in itertools.product(("small", "medium", "large"), ((390, 844), (720, 1280), (1280, 720))):
                for did in ("lr-tv", "lr-strip", "kt-fridge", "lr-vacuum", "lr-soundbar", "test-purifier"):
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
                        for selector in (".panel-head h2", ".panel-head p", ".power-orb b", '.panel-tabs [aria-selected="true"]',
                                         '.panel-tabs [aria-selected="false"]', ".stage-hint", ".pane-help", ".rkey span", "#bri-val",
                                         ".dial-core output", ".dial-core span", '.chip[aria-pressed="true"] span',
                                         ".purifier-readings b", ".purifier-readings span"):
                            if page.locator(selector).count():
                                surface = ReadabilityTests.surface(self, selector)
                                self.assertEqual(surface["alpha"], 1)
                                self.assertGreaterEqual(surface["contrast"], 4.5, (selector, surface))
                        for control in page.locator("#sheet button").all():
                            if control.is_visible():
                                box = control.bounding_box()
                                self.assertGreaterEqual(min(box["width"], box["height"]), 48, control.evaluate("e => e.outerHTML.slice(0, 80)"))
                        self.assertTrue(page.locator(".panel-head [data-close]").is_visible())
                        for selector in (".panel-head", ".panel-tabs"):                      # nothing is cut off sideways
                            if page.locator(selector).count():
                                self.assertLessEqual(page.locator(selector).bounding_box()["width"], w)
        self.assertEqual(self.commands, [])

    def test_fill_readout_idle_volume_and_selected_controls_keep_contrast(self):
        from tests.integration.test_readability import ReadabilityTests
        page = self.page
        graphic_contrast = """([front, back]) => {
          const rgb = value => value.match(/[\\d.]+/g).slice(0, 3).map(Number);
          const luma = value => rgb(value).map(v => v / 255)
            .map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
            .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
          const values = [luma(front), luma(back)].sort((a,b) => a-b);
          return (values[1]+.05) / (values[0]+.05);
        }"""
        for theme, (w, h) in itertools.product(("light", "dark"), ((390, 844), (720, 1280), (1280, 720))):
            page.set_viewport_size({"width": w, "height": h})
            page.evaluate("""async theme => {
              const {store, emit} = await import('/js/store.js');
              store.settings.tile_style = theme; store.settings.font_size = 'large'; emit('all');
            }""", theme)
            self.open("lr-lamp")
            for brightness in (0, 1, 16, 24, 50, 80, 85, 86, 90, 100):
                page.evaluate("""async brightness => {
                  const {store,upsertDevice} = await import('/js/store.js'), d = store.devices.get('lr-lamp');
                  upsertDevice({...d,state:{...d.state,on:true,brightness,color_mode:'color',color:{r:0,g:0,b:255}}});
                }""", brightness)
                self.assertGreaterEqual(ReadabilityTests.surface(self, "#bri-val")["contrast"], 4.5)
                value, track = page.locator("#bri-val").bounding_box(), page.locator("#bri").bounding_box()
                self.assertGreaterEqual(value["y"], track["y"] + track["height"])
            fill = page.locator(".pill-fill").evaluate("e => getComputedStyle(e).backgroundColor")
            well = page.locator("#bri").evaluate("e => getComputedStyle(e).backgroundColor")
            self.assertGreaterEqual(page.evaluate(graphic_contrast, [fill, well]), 3)
            switch = page.locator('.switch[aria-checked="true"] i')
            thumb, track = switch.evaluate("e => [getComputedStyle(e,'::after').backgroundColor, getComputedStyle(e).backgroundColor]")
            self.assertGreaterEqual(page.evaluate(graphic_contrast, [thumb, track]), 3)
            self.open("lr-soundbar")
            page.evaluate("""async () => {
              const {store,upsertDevice} = await import('/js/store.js'), d = store.devices.get('lr-soundbar');
              upsertDevice({...d,state:{...d.state,on:true,volume:12}});
            }""")
            # Inspect the rendered native range, not just accent-color: Chromium can
            # otherwise choose a bright white track even on a dark surface.
            slider = page.locator("[data-speaker-volume]")
            image = Image.open(io.BytesIO(slider.screenshot())).convert("RGB")
            track = image.getpixel((image.width - 8, image.height // 2))
            thumb = image.getpixel((round(12 + (image.width - 24) * .12), image.height // 2))
            colors = ["rgb(%s)" % ", ".join(map(str, color)) for color in (thumb, track)]
            self.assertGreaterEqual(page.evaluate(graphic_contrast, colors), 3)
            if theme == "dark":
                self.assertLess(max(track), 65)
            else:
                self.assertGreater(min(track), 130)
            page.evaluate("""async () => {
              const {store,upsertDevice} = await import('/js/store.js'), d = store.devices.get('lr-soundbar');
              upsertDevice({...d,state:{...d.state,on:false,volume:12}});
            }""")
            self.assertGreaterEqual(ReadabilityTests.surface(self, ".dial-core output")["contrast"], 4.5)
            self.assertGreaterEqual(ReadabilityTests.surface(self, ".dial-core span")["contrast"], 4.5)
            self.open("lr-vacuum")
            page.click('[data-tab="rooms"]')
            if page.locator("[data-rooms-clear]").count():
                page.click("[data-rooms-clear]")
            page.locator('[data-room-pick]').first.click()  # selection only, not a cleaning command
            chip = page.locator('.room-chip[aria-pressed="true"]').first
            self.assertGreaterEqual(ReadabilityTests.surface(self, '.room-chip[aria-pressed="true"]')["contrast"], 4.5)
            self.assertNotEqual(chip.evaluate("e => getComputedStyle(e).borderColor"),
                                page.locator('.room-chip[aria-pressed="false"]').first.evaluate("e => getComputedStyle(e).borderColor"))
            page.click('[data-tab="options"]')
            tab = page.locator('[data-tab="options"]')
            page.keyboard.press("Tab")
            tab.focus()
            self.assertEqual(tab.evaluate("e => getComputedStyle(e).outlineStyle"), "solid")
            self.assertLess(float(tab.evaluate("e => getComputedStyle(e).outlineOffset").removesuffix("px")), 0)
        self.assertEqual(self.commands, [])

    def test_pending_command_is_visible_without_replacing_held_controls(self):
        page = self.page
        pending = []
        page.route("**/devices/lr-soundbar/command", lambda route: pending.append(route))
        self.open("lr-soundbar")
        page.evaluate("""async () => {
          const {store,upsertDevice} = await import('/js/store.js'), d = store.devices.get('lr-soundbar');
          upsertDevice({...d,state:{...d.state,on:true,volume:12}});
        }""")
        slider = page.locator("[data-speaker-volume]")
        slider.evaluate("e => {window.pendingVolume = e;}")
        before = slider.bounding_box()
        slider.focus()
        slider.press("ArrowRight")
        page.wait_for_selector(".panel-pending:not([hidden])")
        self.assertEqual(page.locator("#sheet").get_attribute("aria-busy"), "true")
        self.assertTrue(slider.evaluate("e => e === window.pendingVolume && e === document.activeElement"))
        self.assertEqual(slider.bounding_box(), before)
        self.assertEqual(len(pending), 1)
        pending[0].fulfill(status=400, json={"error": "The speaker is busy. Try again."})
        page.wait_for_selector("#sheet[aria-busy=false] .panel-pending", state="hidden")
        page.wait_for_selector("text=The speaker is busy. Try again.")
        self.assertEqual(slider.input_value(), "12")
        self.assertEqual(len(self.commands), 1)

    def test_group_sync_is_not_camera_video_and_keeps_source_and_errors_honest(self):
        from app.adapters.govee import CAMERA_SYNC_HELP, GROUP_SYNC_HELP
        page = self.page
        page.evaluate("""async help => {
          const {store,upsertDevice}=await import('/js/store.js'), d=store.devices.get('lr-strip');
          upsertDevice({...d,meta:{...d.meta,toggles:[{id:'sync',name:'DreamView group sync',help:help.group}],
            mode_help:help.camera},state:{online:true,on:true,brightness:50,toggles:{}}});
        }""", {"group": GROUP_SYNC_HELP, "camera": CAMERA_SYNC_HELP})
        self.open("lr-strip")
        page.click('[data-tab="options"]')
        self.assertIn("does not select the camera", page.locator(".panel-pane").inner_text())
        self.assertIn("not exposed", page.locator(".panel-pane").inner_text())
        self.assertEqual(page.locator('[data-toggle-status="sync"]').inner_text(), "Not reported")
        self.assertEqual(page.locator('[data-toggle="sync"]').get_attribute("aria-label"), "Turn on DreamView group sync")
        pending = []
        page.route("**/devices/lr-strip/command", lambda route: pending.append(route))
        page.click('[data-toggle="sync"]')
        page.wait_for_selector("#sheet[aria-busy=true]")
        self.assertEqual(self.commands, [{"action": "set_toggle", "value": {"id": "sync", "on": True}}])
        pending[0].fulfill(status=400, json={"error": "Provider unavailable. Try again later."})
        page.wait_for_selector("text=Provider unavailable. Try again later.")
        page.wait_for_function("document.querySelector('[data-toggle-status=sync]').textContent==='Not reported'")
        for source, expected in (("requested", "Last requested: on"), ("reported", "Reported: on")):
            page.evaluate("""async source => {
              const {store,upsertDevice}=await import('/js/store.js'),d=store.devices.get('lr-strip');
              upsertDevice({...d,state:{...d.state,toggles:{sync:true},toggle_sources:{sync:source}}});
            }""", source)
            self.assertEqual(page.locator('[data-toggle-status="sync"]').inner_text(), expected)
        self.assertEqual(page.locator('[data-video], [data-camera-sync]').count(), 0)

    def test_light_slider_taps_cancel_and_close_send_nothing_then_release_sends_once(self):
        page = self.page
        self.open("lr-ceiling")
        page.wait_for_selector("#bri")
        before = page.inner_text("#bri-val")
        page.locator("#bri").evaluate("e=>{window.noopBrightness=e;}")
        page.click("#bri")
        self.assertEqual(page.inner_text("#bri-val"), before)
        page.click("#ct")
        self.assertEqual(self.commands, [])
        self.assertTrue(page.locator("#bri").evaluate("e=>e===window.noopBrightness"))
        for close in (False, True):
            slider = page.locator("#bri")
            slider.scroll_into_view_if_needed()
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

    def test_tabs_and_keyboard_focus_survive_snapshots_and_reopening(self):
        page = self.page
        self.open("lr-strip")
        self.assertEqual(page.locator("#sheet [data-tab]").all_inner_texts(), ["Color", "White", "Scenes", "Music", "Segments", "Options"])
        self.assertEqual(page.locator("#sheet [role=tabpanel]").count(), 1)          # one pane at a time
        tab = page.locator('#sheet [data-tab="scenes"]')
        tab.focus(); tab.press("Enter")
        page.wait_for_selector(".fx-search")
        self.assertEqual(tab.get_attribute("aria-selected"), "true")
        self.assertEqual(page.locator("#sheet [role=tabpanel]").get_attribute("aria-labelledby"), "tab-scenes")
        page.evaluate("async () => (await import('/js/store.js')).reload()")
        self.assertTrue(page.locator(".fx-search").is_visible())                     # a live update keeps the tab
        self.assertTrue(tab.evaluate("e => e === document.activeElement"))           # and the keyboard focus
        tab.press("ArrowRight")                                                      # arrow keys walk the tab list
        page.wait_for_selector("[data-music-mode]")
        self.assertTrue(page.locator('#sheet [data-tab="music"]').evaluate("e => e === document.activeElement"))
        page.keyboard.press("ArrowLeft")
        page.wait_for_selector(".fx-search")
        self.open("lr-lamp")                                                         # another device has its own tabs
        self.assertEqual(page.locator("#sheet .fx").count(), 0)
        self.assertEqual(page.locator("#sheet [data-tab]").all_inner_texts(), ["Color", "White"])
        self.open("lr-strip")                                                        # and coming back remembers the choice
        self.assertEqual(page.locator('#sheet [data-tab="scenes"]').get_attribute("aria-selected"), "true")
        # Tab stays inside the panel: from the first control back to the last and round again.
        first = page.locator("#sheet .panel-head [data-power]")
        first.focus(); first.press("Shift+Tab")
        self.assertTrue(page.evaluate("document.querySelector('#sheet').contains(document.activeElement) && document.activeElement !== document.querySelector('#sheet [data-power]')"))
        page.keyboard.press("Tab")
        self.assertTrue(first.evaluate("e => e === document.activeElement"))
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
                                ({"needs_pairing": True}, "Pair now"), ({"online": True}, "power not reported")):
            with self.subTest(state=state):
                page.evaluate("""async state => {
                  const {store,upsertDevice} = await import('/js/store.js');
                  const device=store.devices.get('lr-lamp');
                  upsertDevice({...device,state});
                }""", state)
                self.assertIn(expected, page.locator("#sheet").inner_text())
                if state.get("online") is False or state.get("needs_pairing"):
                    self.assertEqual(page.locator("#sheet [data-power], #bri, #wheel, #sheet [data-tab]").count(), 0)
                    self.assertTrue(page.locator("#sheet .panel-head [data-close]").is_visible())
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
        page.wait_for_selector('#sheet [data-power][aria-checked="true"]:not([disabled])')
        self.assertEqual(self.commands, [])

    def test_stale_power_is_unavailable_but_an_explicit_wake_remains_possible(self):
        page=self.page
        page.evaluate("""async()=>{
          const {store,upsertDevice,setView}=await import('/js/store.js'),d=store.devices.get('lr-tv');
          setView('rooms');
          upsertDevice({...d,state:{online:false,on:null,stale:true,last_known:{on:true,volume:22},
            wake_available:true,remote_ready:false,error:'TV connection unavailable; its power is unknown.'}});
        }""")
        self.assertEqual(page.locator('.tile[data-id="lr-tv"] .tile-status').first.inner_text(),"Unavailable")
        self.open("lr-tv")
        self.assertIn("Last reported on; current power is unknown",page.locator("#sheet").inner_text())
        self.assertEqual(page.locator("#sheet [data-key],#sheet [data-power]").count(),0)
        wake=page.locator("#sheet [data-wake]")
        self.assertTrue(wake.is_enabled())
        self.assertGreaterEqual(wake.bounding_box()["height"],48)
        pending=[]
        page.route("**/devices/lr-tv/command",lambda route:pending.append(route))
        wake.click()
        page.wait_for_selector("#sheet[aria-busy=true]")
        self.assertEqual(self.commands,[{"action":"power","value":True}])
        wake.evaluate("e=>e.click()")
        self.assertEqual(len(self.commands),1)
        pending.pop().fulfill(status=400,json={"error":"The TV did not become ready."})
        page.wait_for_selector("text=The TV did not become ready.")
        self.assertIn("Unavailable",page.locator("#sheet .panel-title").inner_text())
        page.evaluate("""async()=>{
          const {store,upsertDevice}=await import('/js/store.js'),d=store.devices.get('lr-tv');
          upsertDevice({...d,state:{online:true,on:true,remote_ready:true,stale:false}});
        }""")
        page.wait_for_selector("#sheet [data-key]")
        self.assertEqual(page.locator("#sheet [data-wake]").count(),0)
        self.assertEqual(page.locator(".tile[data-id='lr-tv'] .tile-status").first.inner_text(),"On")

    def test_music_sensitivity_and_remote_holds_cancel_without_commands(self):
        page = self.page
        self.open("lr-strip")
        page.click('#sheet [data-tab="music"]')
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
        page.click('#sheet [data-tab="scenes"]')
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
