"""Glanceable clocks and honest vacuum states on isolated fixtures, never live devices."""
from datetime import datetime
import itertools
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
class IdleVacuumBrowserTests(unittest.TestCase):
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
        self.page.clock.set_fixed_time(datetime(2026, 11, 11, 13, 45))
        self.errors, self.commands = [], []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda r: self.commands.append(r.post_data_json) if r.url.endswith("/command") else None)
        self.page.goto(self.server.url)
        self.page.wait_for_selector(".tile, .widget")

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.commands, [])

    def state(self, state):
        self.page.evaluate("""async state => {
          const {store,upsertDevice}=await import('/js/store.js'), d=store.devices.get('lr-vacuum');
          upsertDevice({...d,state});
        }""", state)

    def ambient(self, face="date", font="medium", hour=13):
        self.page.evaluate("""async ({face,font,hour}) => {
          const {store,emit}=await import('/js/store.js');
          Object.assign(store.settings,{clock_face:face,font_size:font,clock_24h:false,frame_night_clock:true});
          emit('all'); document.querySelector('#ambient').hidden=false;
          (await import('/js/clockfaces.js')).renderAmbient(new Date(2026,10,11,hour,45));
        }""", {"face": face, "font": font, "hour": hour})

    def test_idle_faces_hierarchy_contrast_and_bounds_at_all_sizes(self):
        page = self.page
        self.state({"online": True, "activity": "docked", "battery": 100, "problem": "Empty the tank."})
        for (width, height), font, face, hour in itertools.product(
                ((390, 844), (720, 1280), (1280, 720)), ("small", "medium", "large"),
                ("digital", "analog", "words", "date", "night"), (13, 23)):
            with self.subTest(width=width, font=font, face=face, hour=hour):
                page.set_viewport_size({"width": width, "height": height})
                self.ambient(face, font, hour)
                self.assertEqual(page.locator("#ambient").get_attribute("data-face"), face)
                self.assertEqual(page.locator("#ambient button, #ambient input, #ambient [role=button]").count(), 0)
                bounds = page.locator("#ambient-face").bounding_box()
                self.assertGreaterEqual(bounds["x"], 0)
                self.assertGreaterEqual(bounds["y"], 0)
                self.assertLessEqual(bounds["x"] + bounds["width"], width + 1)
                self.assertLessEqual(bounds["y"] + bounds["height"], height + 1)
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                if face == "date":
                    size = page.evaluate("""() => ['.cf-time','.cf-weekday'].map(sel =>
                      parseFloat(getComputedStyle(document.querySelector('#ambient '+sel)).fontSize))""")
                    self.assertGreaterEqual(size[0] / size[1], 2.5)
                night = hour == 23 or face == "night"
                self.assertEqual(page.locator("#ambient").get_attribute("data-night"), str(night).lower())
                if night:
                    self.assertEqual(page.locator("#ambient").evaluate("e=>getComputedStyle(e).backgroundColor"), "rgb(0, 0, 0)")
                else:
                    contrasts = page.evaluate("""() => {
                      const luma = rgb => rgb.match(/[\\d.]+/g).slice(0,3).map(Number).map(v=>v/255)
                        .map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
                        .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
                      const bg=luma(getComputedStyle(document.querySelector('#ambient')).backgroundColor);
                      return [...document.querySelectorAll('#ambient .cf-time, #ambient .cf-sub, #ambient .cf-day, #ambient .cf-weekday, #ambient .cf-phrase, #ambient .ambient-activity')]
                        .map(e=>(luma(getComputedStyle(e).color)+.05)/(bg+.05));
                    }""")
                    self.assertTrue(all(c >= 4.5 for c in contrasts), contrasts)
                self.assertEqual(page.locator("#ambient-face").evaluate("e=>getComputedStyle(e).transitionDuration"), "0s")

    def test_idle_updates_retain_nodes_and_only_use_visible_devices(self):
        self.state({"online": True, "activity": "cleaning", "battery": 100})
        self.ambient()
        page = self.page
        self.assertIn("Cleaning...", page.locator(".ambient-activity").inner_text())
        stable = page.evaluate("""async () => {
          const {renderAmbient}=await import('/js/clockfaces.js'), time=document.querySelector('#ambient .cf-time');
          for(let second=0;second<60;second+=10) renderAmbient(new Date(2026,10,11,13,45,second));
          return time === document.querySelector('#ambient .cf-time');
        }""")
        self.assertTrue(stable)
        self.state({"online": True, "activity": "paused", "battery": 100})
        self.assertIn("Paused", page.locator(".ambient-activity").inner_text())
        page.evaluate("""async () => {
          const {store,applySnapshot}=await import('/js/store.js');
          applySnapshot({devices:[],rooms:[],scenes:[],settings:store.settings,adapters:[],me:{id:'another'}});
        }""")
        self.assertTrue(page.locator(".ambient-activity").is_hidden())
        self.assertNotIn("vacuum", page.locator("#ambient").inner_text().lower())

    def test_resting_overlay_covers_classic_scrollbar_gutter_without_shifting_center(self):
        browser=self.pw.chromium.launch(ignore_default_args=["--hide-scrollbars"],
                                        args=["--disable-features=OverlayScrollbar"])
        try:
            page=browser.new_page(viewport={"width":1280,"height":720},reduced_motion="reduce")
            page.clock.set_fixed_time(datetime(2026,11,15,13))
            page.goto(self.server.url);page.wait_for_selector(".widget,.tile")
            page.add_style_tag(content="html{overflow-y:scroll}::-webkit-scrollbar{width:15px}")
            for width,height in ((1280,720),(720,1280),(390,844)):
                with self.subTest(width=width):
                    page.set_viewport_size({"width":width,"height":height})
                    page.evaluate("""async()=>{
                      document.querySelector('#ambient').hidden=false;
                      (await import('/js/clockfaces.js')).renderAmbient();
                    }""")
                    metrics=page.evaluate("""()=>{
                      const r=document.querySelector('#ambient').getBoundingClientRect();
                      const g=document.querySelector('#ambient-content').getBoundingClientRect();
                      return {gutter:innerWidth-document.documentElement.clientWidth,left:r.left,width:r.width,height:r.height,
                        dx:g.x+g.width/2-innerWidth/2,dy:g.y+g.height/2-innerHeight/2};
                    }""")
                    self.assertEqual(metrics["gutter"],15)
                    self.assertEqual((metrics["left"],metrics["width"],metrics["height"]),(0,width,height))
                    self.assertLessEqual(max(abs(metrics["dx"]),abs(metrics["dy"])),9)
        finally:
            browser.close()

    def test_idle_and_home_share_one_weather_request(self):
        requests = []
        def weather(route):
            requests.append(route.request.url)
            route.fulfill(json={"available": True, "temperature": 15, "high": 18, "low": 12,
                                "condition": "cloudy", "label": "Cloudy", "is_day": True})
        page = self.page
        page.route("**/api/v1/weather", weather)
        page.evaluate("""async () => {
          const {store,emit}=await import('/js/store.js');
          Object.assign(store.settings,{weather_enabled:true,latitude:47,longitude:-122,place_name:'Test city'});
          emit('all');
        }""")
        self.ambient()
        page.wait_for_selector("#ambient .cf-temp")
        for _ in range(5):
            page.evaluate("async ()=>(await import('/js/clockfaces.js')).renderAmbient()")
        self.assertEqual(len(requests), 1)
        self.assertIn("15°", page.locator("#ambient").inner_text())

    def test_photo_idle_keeps_the_existing_night_clock_preference(self):
        page = self.page
        page.clock.install(time=datetime(2026, 11, 11, 13))
        page.reload()
        page.wait_for_selector(".tile, .widget")
        page.evaluate("""async () => {
          const {store,emit}=await import('/js/store.js');
          Object.assign(store.settings,{dim_after_seconds:1,idle_screen:'photos',frame_night_clock:true,clock_face:'date'});
          emit('all');
        }""")
        page.clock.fast_forward(6000)
        page.wait_for_selector("#frame:not([hidden])")
        page.evaluate("async ()=>(await import('/js/photoframe.js')).closeFrame()")
        page.clock.set_system_time(datetime(2026, 11, 11, 23))
        page.clock.fast_forward(6000)
        page.wait_for_selector('#ambient[data-face="date"][data-night="true"]:not([hidden])')
        self.assertTrue(page.locator("#frame").is_hidden())
        page.locator("#ambient").click()
        page.evaluate("""async () => {
          const {store}=await import('/js/store.js'); store.settings.frame_night_clock=false;
        }""")
        page.clock.fast_forward(6000)
        page.wait_for_selector("#frame:not([hidden])")
        self.assertTrue(page.locator("#ambient").is_hidden())

    def test_wake_touch_and_keyboard_do_not_activate_the_control_beneath(self):
        page = self.page
        page.evaluate("async () => (await import('/js/store.js')).setView('rooms')")
        quick = page.locator('.tile[data-id="lr-vacuum"] .tile-quick').first
        quick.scroll_into_view_if_needed()
        box = quick.bounding_box()
        self.ambient()
        page.touchscreen.tap(box["x"] + 20, box["y"] + 20)
        self.assertTrue(page.locator("#ambient").is_hidden())
        self.assertEqual(self.commands, [])
        quick.focus()
        self.ambient()
        page.keyboard.press("Space")
        self.assertTrue(page.locator("#ambient").is_hidden())
        self.assertEqual(self.commands, [])

    def test_progress_transitions_never_use_battery_or_historical_stats(self):
        page = self.page
        page.evaluate("async () => (await import('/js/sheet.js')).openDevice('lr-vacuum')")
        for theme, (width, height) in itertools.product(("dark", "light"), ((390, 844), (720, 1280), (1280, 720))):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("""async theme => {
              const {store,emit}=await import('/js/store.js'); store.settings.tile_style=theme; store.settings.font_size='large'; emit('all');
            }""", theme)
            for activity in ("cleaning", "paused", "returning"):
                state = {"online": True, "activity": activity, "battery": 100, "last_clean": {"area_m2": 34, "minutes": 104}}
                self.state(state)
                progress = page.locator(".vac-progress")
                self.assertEqual(progress.get_attribute("role"), "progressbar")
                self.assertIsNone(progress.get_attribute("aria-valuenow"))
                self.assertIn("Completion not reported", progress.get_attribute("aria-valuetext"))
                self.assertEqual(page.locator(".vac-run-stats").count(), 0)
                self.assertIn("Battery 100%", page.locator(".vac-batt").inner_text())
                self.assertIn("Last clean 34 m² in 104 min", page.locator(".vac-status-card").inner_text())
                self.state({**state, "cleaning": {"run_id": "job1", "status": activity, "area_m2": 5, "elapsed_seconds": 360}})
                self.assertIn("Current run · 6 min reported · 5 m² cleaned", page.locator(".vac-run-stats").inner_text())
                self.assertEqual(page.locator(".vac-progress-track").evaluate("e=>getComputedStyle(e).animationName"), "none")
                self.assertTrue(page.locator("#sheet").evaluate("e=>e.scrollWidth<=e.clientWidth"))
            for activity, job, problem, expected in (
                    ("docked", None, "", "Docked"),
                    ("idle", {"status": "stopped"}, "", "Cleaning stopped"),
                    ("docked", {"run_id": "job1", "status": "completed"}, "", "Clean complete"),
                    ("docked", {"run_id": "job1", "status": "completed"}, "Tank full", "Needs attention"),
                    (None, None, "", "Status not reported")):
                self.state({"online": True, "activity": activity, "battery": 100, "cleaning": job, "problem": problem})
                self.assertIn(expected, page.locator(".vac-state").inner_text())
                self.assertEqual(page.locator(".vac-progress").count(), 0)
            self.state({"online": False, "activity": "cleaning", "cleaning": {"run_id": "old", "status": "cleaning", "area_m2": 50}})
            self.assertIn("Offline", page.locator("#sheet").inner_text())
            self.assertEqual(page.locator(".vac-progress, .vac-run-stats").count(), 0)
