"""Edit the presentation on screen, using isolated layouts and no household devices."""
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
class EditParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.server = DemoServer(cls.folder).start()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as error:
            cls.pw.stop(); cls.server.stop(); shutil.rmtree(cls.folder)
            if os.environ.get("REQUIRE_UI_TESTS"): raise
            raise unittest.SkipTest(str(error))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.server.stop(); shutil.rmtree(cls.folder)

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width":1280,"height":720},has_touch=True,reduced_motion="reduce")
        self.page.clock.set_fixed_time(datetime(2026,11,14,14,0))
        self.errors, self.commands = [], []
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.on("request",lambda r:self.commands.append(r.url) if r.method=="POST" and (r.url.endswith("/command") or "/scenes/" in r.url) else None)
        self.page.goto(self.server.url);self.page.wait_for_selector(".widget,.tile")
        self.page.request.post(self.server.url+"/api/v1/auth/sign-in",data={"profile_id":"owner","password":"homepanel"})
        self.page.request.patch(self.server.url+"/api/v1/profiles/me",data={"home_view":"overview","room_view":"compact"})
        self.page.evaluate("async()=>(await import('/js/store.js')).reload()")

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors,[])
        self.assertEqual(self.commands,[])

    def show(self, where, mode, font="medium"):
        self.page.evaluate("""async({where,mode,font})=>{
          const s=await import('/js/store.js');
          Object.assign(s.store.settings,{[where==='home'?'home_view':'room_view']:mode,font_size:font});
          s.setRoom('Living room');s.setView(where);s.emit('all');
        }""",{"where":where,"mode":mode,"font":font})
        self.page.evaluate("document.fonts.ready")
        self.page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")

    def edit(self, where):
        if where=="home":
            self.page.evaluate("async()=>(await import('/js/home.js')).startEditing()")
        else:
            self.page.evaluate("async()=>(await import('/js/room-layout.js')).startRoomEditing('Living room')")
        self.page.wait_for_selector(".editbar")

    def cancel(self, where):
        self.page.locator("[data-edit-cancel]" if where=="home" else "[data-room-cancel]").click()
        self.page.wait_for_selector(".editbar",state="hidden")

    def geometry(self, where):
        return self.page.evaluate("""where=>{
          const root=document.querySelector(where==='home'?'#home':'#grid');
          const boxes=[...root.querySelectorAll(where==='home'?'.home-overview,.overview-clock,.home-attention,.widget':'.room-card,.room-tile')];
          return boxes.map(e=>{const r=e.getBoundingClientRect();return {
            id:e.dataset.wid||e.className,
            box:[r.x+scrollX,r.y+scrollY,r.width,r.height].map(v=>Math.round(v*10)/10),
            controls:[...e.querySelectorAll('input,button')].filter(b=>!b.matches('[data-resize],[data-room-options],[data-card-grip]'))
              .map(b=>{const q=b.getBoundingClientRect();return [b.getAttribute('data-more')??b.getAttribute('data-act')??b.getAttribute('data-card-range'),
                Math.round(q.width),Math.round(q.height)];})
          };});
        }""",where)

    def assert_geometry(self, actual, expected):
        self.assertEqual([x["id"] for x in actual],[x["id"] for x in expected])
        for a,b in zip(actual,expected,strict=True):
            for av,bv in zip(a["box"],b["box"],strict=True):
                self.assertAlmostEqual(av,bv,delta=1,msg=(a["id"],a["box"],b["box"]))
            self.assertEqual(a["controls"],b["controls"],a["id"])

    def test_selected_view_and_geometry_stay_identical_enter_cancel_at_all_sizes(self):
        page=self.page
        for where,modes in (("home",("overview","free")),("rooms",("compact","free"))):
            for mode,font,(width,height) in itertools.product(modes,("small","medium","large"),((390,844),(720,1280),(1280,720),(390,480))):
                with self.subTest(where=where,mode=mode,font=font,width=width,height=height):
                    page.set_viewport_size({"width":width,"height":height})
                    self.show(where,mode,font);page.evaluate("window.scrollTo(0,0)")
                    before=self.geometry(where)
                    selected=page.locator(f'[data-layout-view="{ "home_view" if where=="home" else "room_view"}"][aria-pressed=true]')
                    self.assertEqual(selected.get_attribute("data-layout-value"),mode)
                    self.edit(where)
                    self.assertTrue(selected.is_visible());self.assertTrue(selected.is_disabled())
                    self.assert_geometry(self.geometry(where),before)
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"),width)
                    toolbar=page.locator(".editbar").bounding_box()
                    self.assertLessEqual(toolbar["height"],90)
                    self.assertGreaterEqual(toolbar["x"],0)
                    self.assertLessEqual(toolbar["x"]+toolbar["width"],width)
                    self.assertLessEqual(toolbar["y"]+toolbar["height"],height)
                    for button in page.locator(".editbar button").all():
                        box=button.bounding_box()
                        self.assertGreaterEqual(min(box["width"],box["height"]),48)
                    if where=="home":
                        self.assertEqual(page.locator(".home-overview").count(),int(mode=="overview"))
                        self.assertEqual(page.locator(".home-grid .t-clock").count(),int(mode=="free"))
                        self.assertEqual(page.locator(".w-hide,.home .w-menu").count(),0)
                    if where=="rooms" and mode=="compact":
                        self.assertGreater(page.locator("[data-card-grip]").count(),0)
                        self.assertEqual(page.locator("#grid [data-resize]").count(),0)
                    page.evaluate("""()=>{
                      for(const button of document.querySelectorAll('#home .w-fill button,#home [data-ambient],#home [data-attention],#grid .tile button,#all-off,[data-room-off]')) button.click();
                      for(const input of document.querySelectorAll('#grid .tile input')) {
                        input.value=70;input.dispatchEvent(new Event('change',{bubbles:true}));
                      }
                    }""")
                    self.assertTrue(page.locator("#sheet").is_hidden())
                    self.assertTrue(page.locator("#settings").is_hidden())
                    self.cancel(where)
                    self.assert_geometry(self.geometry(where),before)
                    self.assertEqual(self.commands,[])

    def test_compact_keyboard_and_pointer_reorder_persist_without_free_geometry_changes(self):
        page=self.page
        saved={"version":3,"widgets":[
            {"id":"lr-tv","size":"1x1","positions":{"2":{"x":0,"y":0,"size":"1x1"},"6":{"x":0,"y":0,"size":"1x1"}}},
            {"id":"lr-lamp","size":"1x1","positions":{"2":{"x":1,"y":0,"size":"1x1"},"6":{"x":4,"y":3,"size":"1x1"}}},
            {"id":"lr-soundbar","size":"2x1","positions":{"2":{"x":0,"y":2,"size":"2x1"},"6":{"x":1,"y":1,"size":"2x1"}}},
        ]}
        page.evaluate("async layout=>(await import('/js/api.js')).api.saveRoomLayout('Living room',layout)",saved)
        page.evaluate("async()=>(await import('/js/store.js')).reload()")
        self.show("rooms","compact")
        initial={w["id"]:w for w in page.request.get(self.server.url+"/api/v1/state").json()["settings"]["room_layouts"]["Living room"]["widgets"]}
        order=lambda:page.locator(".compact-rooms > .room-card").evaluate_all("els=>els.map(e=>e.dataset.wid)")
        before=order()
        self.edit("rooms")
        handle=page.locator('[data-card-grip="lr-tv"]')
        handle.focus();handle.press("ArrowDown")
        self.assertEqual(order()[:2],[before[1],before[0]])
        self.assertTrue(handle.evaluate("e=>e===document.activeElement"))
        page.evaluate("async()=>(await import('/js/store.js')).reload()")
        self.assertEqual(order()[:2],[before[1],before[0]])
        handle.scroll_into_view_if_needed()
        keyboard_order=order()
        target=page.locator(".compact-rooms > .room-card").nth(2)
        start,end=handle.bounding_box(),target.bounding_box()
        page.mouse.move(start["x"]+24,start["y"]+24);page.mouse.down()
        page.mouse.move(end["x"]+end["width"]/2,end["y"]+end["height"]*.8,steps=12)
        page.mouse.up();page.wait_for_timeout(100)
        final=order()
        self.assertNotEqual(final,before)
        self.assertNotEqual(final,keyboard_order)
        page.click("[data-room-done]");page.wait_for_selector(".editbar",state="hidden")
        self.assertEqual(order(),final)
        page.reload();page.wait_for_selector(".compact-rooms")
        self.assertEqual(order(),final)
        actual=page.request.get(self.server.url+"/api/v1/state").json()["settings"]["room_layouts"]["Living room"]["widgets"]
        self.assertEqual([w["id"] for w in actual],final)
        for w in actual:
            if w["id"] in initial:self.assertEqual(w,initial[w["id"]])
        self.edit("rooms")
        page.locator("[data-card-grip]").first.press("ArrowDown")
        self.cancel("rooms");self.assertEqual(order(),final)

    def test_edit_from_all_rooms_does_not_change_route_or_other_room_geometry(self):
        page=self.page
        self.show("rooms","compact")
        page.evaluate("async()=>(await import('/js/store.js')).setRoom('all')")
        before=self.geometry("rooms")
        page.click('[data-edit-room="Living room"]')
        self.assertEqual(page.inner_text("#title"),"All rooms")
        self.assert_geometry(self.geometry("rooms"),before)
        self.assertEqual(page.locator(".compact-rooms.editing").count(),1)
        self.cancel("rooms");self.assert_geometry(self.geometry("rooms"),before)

    def test_compact_touch_reorder_and_resize_cancel_keep_visible_cards(self):
        page=self.page
        page.set_viewport_size({"width":390,"height":844})
        self.show("rooms","compact");self.edit("rooms")
        order=lambda:page.locator(".compact-rooms > .room-card").evaluate_all("els=>els.map(e=>e.dataset.wid)")
        before=order()
        grip=page.locator("[data-card-grip]").first
        grip.scroll_into_view_if_needed();a=grip.bounding_box()
        target=page.locator(".compact-rooms > .room-card").nth(1).bounding_box()
        cdp=page.context.new_cdp_session(page)
        x,y=a["x"]+24,a["y"]+24
        cdp.send("Input.dispatchTouchEvent",{"type":"touchStart","touchPoints":[{"x":x,"y":y}]})
        page.wait_for_timeout(160)
        for step in range(1,9):
            cdp.send("Input.dispatchTouchEvent",{"type":"touchMove","touchPoints":[{"x":x+10,"y":y+(target["y"]+target["height"]*.85-y)*step/8}]})
        page.evaluate("async()=>(await import('/js/store.js')).reload()")
        cdp.send("Input.dispatchTouchEvent",{"type":"touchEnd","touchPoints":[]})
        page.wait_for_timeout(100)
        self.assertNotEqual(order(),before)
        touched=order()
        first=page.locator("[data-card-grip]").first
        first.scroll_into_view_if_needed();a=first.bounding_box()
        page.mouse.move(a["x"]+24,a["y"]+24);page.mouse.down()
        page.mouse.move(a["x"]+35,a["y"]+150,steps=8)
        page.set_viewport_size({"width":720,"height":1280})
        page.mouse.up()
        self.assertEqual(order(),touched)
        self.cancel("rooms")
        self.assertEqual(order(),before)

    def test_free_resize_done_reload_and_profile_switch_keep_editor_scope(self):
        page=self.page
        page.evaluate("async()=>(await import('/js/api.js')).api.updateMe({room_view:'free'})")
        page.evaluate("async()=>(await import('/js/api.js')).api.saveRoomLayout('Living room',{version:3,widgets:[]})")
        page.evaluate("async()=>(await import('/js/store.js')).reload()")
        self.show("rooms","free")
        before=self.geometry("rooms")
        self.edit("rooms");self.assert_geometry(self.geometry("rooms"),before)
        tile=page.locator('.room-tile[data-wid="lr-tv"]')
        tile.locator("[data-room-options]").click()
        page.click('[data-room-size="1x1"]')
        page.click("[data-room-options-close].btn")
        expected=self.geometry("rooms")
        page.click("[data-room-done]");page.wait_for_selector(".editbar",state="hidden")
        self.assert_geometry(self.geometry("rooms"),expected)
        page.reload();page.wait_for_selector(".room-tile");self.assert_geometry(self.geometry("rooms"),expected)
        self.edit("rooms")
        page.evaluate("""async()=>{
          await(await import('/js/api.js')).api.signIn({profile_id:'sam'});
          await(await import('/js/store.js')).reload();
        }""")
        self.assertEqual(page.locator(".editbar").count(),0)
        self.assertEqual(page.locator('#grid [data-wid="lr-tv"]').count(),0)

    def test_overview_edits_visible_widgets_not_invisible_clock_and_keeps_free_positions(self):
        page=self.page
        layout={"version":3,"widgets":[
            {"id":"clock","type":"clock","size":"2x1","positions":{"6":{"x":0,"y":0,"size":"2x1"}}},
            {"id":"weather","type":"weather","size":"1x1","positions":{"6":{"x":2,"y":0,"size":"1x1"}}},
            {"id":"zone","type":"zone","size":"1x1","options":{"tz":"Asia/Kolkata","label":"India"},"positions":{"6":{"x":3,"y":0,"size":"1x1"}}},
            {"id":"hidden-clock","type":"clock","hidden":True,"size":"1x1"}]}
        page.evaluate("async layout=>(await import('/js/api.js')).api.saveLayout(layout)",layout)
        page.evaluate("async()=>(await import('/js/store.js')).reload()")
        self.show("home","overview")
        baseline=page.request.get(self.server.url+"/api/v1/state").json()["settings"]["home_layout"]
        self.edit("home")
        widget=page.locator('.widget[data-wid="weather"]')
        widget.focus();widget.press("ArrowLeft");widget.press("ArrowLeft")
        self.assertEqual(widget.evaluate("e=>getComputedStyle(e).gridColumnStart"),"1")
        widget.press("Enter");page.click('[data-size-pick="2x1"]');page.click(".wmenu [data-menu-close]")
        expected=self.geometry("home")
        page.click("[data-edit-done]");page.wait_for_selector(".editbar",state="hidden")
        self.assert_geometry(self.geometry("home"),expected)
        page.reload();page.wait_for_selector(".home-overview")
        self.assert_geometry(self.geometry("home"),expected)
        saved=page.request.get(self.server.url+"/api/v1/state").json()["settings"]["home_layout"]
        for w in saved["widgets"]:
            before=next(x for x in baseline["widgets"] if x["id"]==w["id"])
            self.assertEqual(w.get("positions"),before.get("positions"))
            if w["type"]=="clock":self.assertEqual(w,before)
        self.assertEqual(next(w for w in saved["widgets"] if w["id"]=="weather")["overview_positions"]["6"],{"x":0,"y":0,"size":"2x1"})
        self.show("home","free")
        self.assertEqual(page.locator('.widget[data-wid="weather"]').evaluate("e=>getComputedStyle(e).gridColumnStart"),"3")

    def test_save_failure_keeps_mode_draft_and_cancel_restores_entry(self):
        page=self.page
        for where,mode in (("rooms","compact"),("home","overview")):
            self.show(where,mode);before=self.geometry(where)
            self.edit(where)
            if where=="rooms":page.locator("[data-card-grip]").first.press("ArrowDown")
            else:
                page.locator(".widget").first.focus();page.keyboard.press("ArrowDown")
            draft=self.geometry(where)
            page.route("**/api/v1/profiles/me/**",lambda route:route.fulfill(status=400,json={"error":"Layout could not be saved."}))
            page.click("[data-room-done]" if where=="rooms" else "[data-edit-done]")
            page.wait_for_selector("text=Layout could not be saved.")
            self.assert_geometry(self.geometry(where),draft)
            self.assertTrue(page.locator(".editbar").is_visible())
            self.cancel(where);self.assert_geometry(self.geometry(where),before)
            page.unroute("**/api/v1/profiles/me/**")
