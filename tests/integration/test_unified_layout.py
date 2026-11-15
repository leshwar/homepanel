"""The same compact spatial grid before, during and after editing; isolated devices."""
import itertools
import os
import shutil
import tempfile
import unittest

from app.core.layout import default_layout
from tests.helpers import DemoServer

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    if os.environ.get("REQUIRE_UI_TESTS"):
        raise
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class UnifiedGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.mkdtemp()
        cls.server=DemoServer(cls.folder).start()
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop();cls.server.stop();shutil.rmtree(cls.folder)

    def setUp(self):
        self.page=self.browser.new_page(viewport={"width":1280,"height":720},has_touch=True,reduced_motion="reduce")
        self.errors,self.commands=[],[]
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.on("request",lambda r:self.commands.append(r.url) if r.method=="POST" and (r.url.endswith("/command") or "/scenes/" in r.url) else None)
        self.page.goto(self.server.url);self.page.wait_for_selector(".widget,.tile")
        self.page.request.post(self.server.url+"/api/v1/auth/sign-in",data={"profile_id":"owner","password":"homepanel"})
        layout=default_layout()
        layout["widgets"] += [{"id":"photos","type":"photos","size":"2x6","hidden":False,"options":{}},
                              {"id":"favs","type":"favourites","size":"2x6","hidden":False,"options":{"devices":["lr-tv"]}}]
        self.seed("home",layout)
        self.page.evaluate("async()=>{const s=await import('/js/store.js');s.setRoom('Living room');s.setView('home');}")

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors,[])
        self.assertEqual(self.commands,[])

    def seed(self,where,layout):
        self.page.evaluate("""async({where,layout})=>{
          const a=(await import('/js/api.js')).api;
          if(where==='home') await a.saveLayout(layout);
          else await a.saveRoomLayout('Living room',layout);
          await (await import('/js/store.js')).reload();
        }""",{"where":where,"layout":layout})

    def show(self,where):
        self.page.evaluate("async where=>{const s=await import('/js/store.js');s.setRoom('Living room');s.setView(where);}",where)
        self.page.evaluate("document.fonts.ready")
        self.page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")

    def edit(self,where):
        self.page.evaluate("""async where=>{
          if(where==='home')(await import('/js/home.js')).startEditing();
          else (await import('/js/room-layout.js')).startRoomEditing('Living room');
        }""",where)
        self.page.wait_for_selector(".editbar")

    def cancel(self,where):
        self.page.locator("[data-edit-cancel]" if where=="home" else "[data-room-cancel]").click()
        self.page.wait_for_selector(".editbar",state="hidden")

    def done(self,where):
        self.page.locator("[data-edit-done]" if where=="home" else "[data-room-done]").click()
        self.page.wait_for_selector(".editbar",state="hidden")

    def geometry(self,where):
        return self.page.evaluate("""where=>[...document.querySelectorAll((where==='home'?'#home':'#grid')+' .layout-item')].map(e=>{
          const r=e.getBoundingClientRect();return {id:e.dataset.wid,box:[r.x+scrollX,r.y+scrollY,r.width,r.height].map(Math.round),
            content:[...e.querySelectorAll('.w-fill,.card-header,.card-controls')].map(c=>{
              const b=c.getBoundingClientRect();return [Math.round(b.width),Math.round(b.height)];
            })};
        })""",where)

    def test_normal_edit_cancel_geometry_and_safe_controls_all_sizes_themes_fonts(self):
        page=self.page
        for where,theme,font,(width,height) in itertools.product(("home","rooms"),("dark","light"),("small","medium","large"),
                                                                 ((390,844),(720,1280),(1280,720),(390,480))):
            with self.subTest(where=where,theme=theme,font=font,width=width):
                page.set_viewport_size({"width":width,"height":height})
                page.evaluate("async p=>{const s=await import('/js/store.js');Object.assign(s.store.settings,p);s.emit('all');}",
                              {"font_size":font,"tile_style":theme})
                self.show(where);before=self.geometry(where)
                self.edit(where)
                self.assertEqual(self.geometry(where),before)
                root=page.locator("#home" if where=="home" else "#grid")
                count=root.locator(".layout-item").count()
                self.assertEqual(root.locator("[data-grip]").count(),count)
                self.assertEqual(root.locator("[data-resize]").count(),count)
                self.assertEqual(page.locator("[data-layout-view],.home-overview,.compact-rooms").count(),0)
                for handle in root.locator("[data-grip],[data-resize]").all():
                    box=handle.bounding_box()
                    self.assertGreaterEqual(min(box["width"],box["height"]),48)
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"),width)
                self.assertLessEqual(page.locator(".editbar").bounding_box()["height"],90)
                page.evaluate("""()=>{
                  for(const b of document.querySelectorAll('#home .w-fill button,#home [data-ambient],#grid .tile button,#all-off,[data-room-off]'))b.click();
                  for(const input of document.querySelectorAll('#grid .tile input')){
                    input.value=70;input.dispatchEvent(new Event('change',{bubbles:true}));
                  }
                }""")
                self.assertTrue(page.locator("#sheet").is_hidden())
                self.assertTrue(page.locator("#settings").is_hidden())
                self.cancel(where)
                self.assertEqual(self.geometry(where),before)

    def test_every_home_type_moves_and_resizes_with_persistent_exact_geometry(self):
        page=self.page
        for kind in ("clock","notifications","zone","weather","photos","scenes","rooms","favourites"):
            with self.subTest(kind=kind):
                layout={"version":4,"widgets":[
                    {"id":"subject","type":kind,"size":"2x3","positions":{"6":{"x":0,"y":0,"size":"2x3"}}},
                    {"id":"neighbor","type":"zone","size":"1x3","positions":{"6":{"x":5,"y":0,"size":"1x3"}}},
                ]}
                self.seed("home",layout);self.show("home");before=self.geometry("home")
                self.edit("home");self.assertEqual(self.geometry("home"),before)
                tile=page.locator('[data-wid="subject"]')
                handle=tile.locator("[data-grip]");handle.focus();handle.press("ArrowDown")
                self.assertTrue(handle.evaluate("e=>e===document.activeElement"))
                corner=tile.locator("[data-resize]");corner.focus();corner.press("ArrowDown");corner.press("ArrowRight")
                edited=self.geometry("home")
                self.assertNotEqual(edited[0]["box"],before[0]["box"])
                self.assertEqual(edited[1],before[1])
                self.done("home");self.assertEqual(self.geometry("home"),edited)
                page.reload();page.wait_for_selector('[data-wid="subject"]')
                self.assertEqual(self.geometry("home"),edited)
                saved=page.request.get(self.server.url+"/api/v1/state").json()["settings"]["home_layout"]["widgets"][0]
                self.assertEqual(saved["positions"]["6"],{"x":0,"y":1,"size":"3x4"})

    def test_every_room_card_moves_and_resizes_without_neighbor_jumps(self):
        page=self.page
        ids=[d["id"] for d in page.request.get(self.server.url+"/api/v1/state").json()["devices"] if d["room"]=="Living room"]
        self.seed("rooms",{"version":4,"widgets":[{"id":wid,"size":"2x3","positions":{"6":{"x":0,"y":index*6,"size":"2x3"}}}
                                                  for index,wid in enumerate(ids)]})
        self.show("rooms");self.edit("rooms")
        for wid in ids:
            before={x["id"]:x for x in self.geometry("rooms")}
            tile=page.locator(f'.room-tile[data-wid="{wid}"]')
            tile.locator("[data-grip]").press("ArrowDown")
            tile.locator("[data-resize]").press("ArrowDown")
            after={x["id"]:x for x in self.geometry("rooms")}
            self.assertNotEqual(after.pop(wid),before.pop(wid))
            self.assertEqual(after,before)
        edited=self.geometry("rooms")
        self.done("rooms");self.assertEqual(self.geometry("rooms"),edited)
        page.reload();page.wait_for_selector(".room-tile")
        self.assertEqual(self.geometry("rooms"),edited)
        self.edit("rooms");page.locator("[data-resize]").first.press("ArrowDown")
        self.cancel("rooms");self.assertEqual(self.geometry("rooms"),edited)

    def test_pointer_touch_snapshot_and_breakpoint_cancel_use_one_editor(self):
        page=self.page
        page.set_viewport_size({"width":720,"height":1280})
        self.seed("home",{"version":4,"widgets":[
            {"id":"clock","type":"clock","size":"2x4","positions":{"4":{"x":0,"y":0,"size":"2x4"}}},
            {"id":"notifications","type":"notifications","size":"2x4","positions":{"4":{"x":2,"y":0,"size":"2x4"}}},
        ]})
        self.show("home");before=self.geometry("home");self.edit("home")
        handle=page.locator('[data-wid="clock"] [data-grip]');a=handle.bounding_box()
        page.mouse.move(a["x"]+24,a["y"]+24);page.mouse.down();page.mouse.move(a["x"]+24,a["y"]+24+270,steps=10)
        page.evaluate("async()=>(await import('/js/store.js')).reload()")
        page.mouse.up()
        self.assertEqual(self.geometry("home")[0]["box"][1],before[0]["box"][1]+270)
        cdp=page.context.new_cdp_session(page)
        a=page.locator('[data-wid="notifications"] [data-grip]').bounding_box();x,y=a["x"]+24,a["y"]+24
        cdp.send("Input.dispatchTouchEvent",{"type":"touchStart","touchPoints":[{"x":x,"y":y}]})
        for step in range(1,7):
            cdp.send("Input.dispatchTouchEvent",{"type":"touchMove","touchPoints":[{"x":x,"y":y+270*step/6}]})
        cdp.send("Input.dispatchTouchEvent",{"type":"touchEnd","touchPoints":[]})
        self.assertEqual(self.geometry("home")[1]["box"][1],before[1]["box"][1]+270)
        a=handle.bounding_box()
        page.mouse.move(a["x"]+24,a["y"]+24);page.mouse.down();page.mouse.move(a["x"]+24,a["y"]+150,steps=4)
        page.set_viewport_size({"width":390,"height":844});page.mouse.up()
        self.assertIsNone(page.locator("#home").get_attribute("data-grid-gesture"))
        self.cancel("home")
        page.set_viewport_size({"width":720,"height":1280});self.show("home")
        self.assertEqual(self.geometry("home"),before)

    def test_save_error_concurrent_edit_and_profile_change_keep_data_scoped(self):
        page=self.page;self.show("home")
        entry=page.request.get(self.server.url+"/api/v1/state").json()["settings"]["home_layout"]
        self.edit("home")
        page.locator('[data-wid="clock"] [data-grip]').press("ArrowDown")  # collision is refused, no neighbor moves
        page.route("**/profiles/me/layout",lambda route:route.fulfill(status=409,json={"error":"Layout changed on another screen"}))
        page.locator("[data-edit-done]").click();page.wait_for_selector("text=Layout changed on another screen")
        self.assertTrue(page.locator(".editbar").is_visible())
        self.cancel("home")
        self.assertEqual(page.request.get(self.server.url+"/api/v1/state").json()["settings"]["home_layout"],entry)
        page.unroute("**/profiles/me/layout")
        self.edit("home")
        page.request.post(self.server.url+"/api/v1/auth/sign-in",data={"profile_id":"sam"})
        page.evaluate("async()=>(await import('/js/store.js')).reload()")
        page.wait_for_selector(".editbar",state="hidden")
        state=page.request.get(self.server.url+"/api/v1/state").json()
        self.assertNotIn("lr-tv",[d["id"] for d in state["devices"]])
        self.assertEqual(page.locator('[data-attention="lr-tv"]').count(),0)

    def test_edit_from_all_rooms_keeps_other_room_geometry(self):
        self.show("rooms")
        self.page.evaluate("async()=>(await import('/js/store.js')).setRoom('all')")
        before=self.geometry("rooms")
        self.page.click('[data-edit-room="Living room"]')
        self.assertEqual(self.page.inner_text("#title"),"All rooms")
        self.assertEqual(self.geometry("rooms"),before)
        self.assertEqual(self.page.locator(".layout-grid.editing").count(),1)
        self.cancel("rooms")
        self.assertEqual(self.geometry("rooms"),before)

    def test_selected_legacy_views_migrate_into_real_editable_tiles(self):
        svc=self.server.app.state.service
        for home_view,room_view,hidden in (("overview","compact",False),("free","free",False),("overview","compact",True)):
            with self.subTest(home=home_view,room=room_view,hidden=hidden):
                owner=svc.profiles.get("owner")
                owner.update(home_view=home_view,room_view=room_view,
                    home_layout={"version":3,"widgets":[
                        {"id":"clock","type":"clock","size":"2x2","hidden":hidden},
                        {"id":"weather","type":"weather","size":"2x1",
                         "positions":{"6":{"x":0,"y":5,"size":"2x1"}},
                         "overview_positions":{"6":{"x":2,"y":2,"size":"2x1"}}},
                    ]},
                    room_layouts={"Living room":{"version":3,"widgets":[
                        {"id":"lr-tv","size":"2x2","positions":{"6":{"x":0,"y":4,"size":"2x2"}}},
                        {"id":"lr-soundbar","size":"2x1"},
                    ]}})
                svc._migrate_layouts()
                self.page.reload();self.page.wait_for_selector(".widget,.tile")
                state=self.page.request.get(self.server.url+"/api/v1/state").json()["settings"]
                for where in ("home","rooms"):
                    self.show(where);before=self.geometry(where)
                    self.edit(where);self.assertEqual(self.geometry(where),before)
                    self.cancel(where);self.assertEqual(self.geometry(where),before)
                self.show("home")
                self.assertEqual(self.page.locator(".home-grid > .t-clock").count(),int(not hidden))
                self.assertEqual(self.page.locator(".home-grid > .t-notifications").count(),1)
                expected=next(w for w in state["home_layout"]["widgets"] if w["id"]=="weather")["positions"]["6"]
                self.assertEqual(self.page.locator('[data-wid="weather"]').evaluate("e=>e.style.gridRowStart"),str(expected["y"]+1))
