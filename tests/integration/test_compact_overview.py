"""Compact room geometry, safe controls and Home attention against isolated devices."""
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
class CompactOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir).start()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as error:
            cls.pw.stop(); cls.server.stop(); shutil.rmtree(cls.dir,ignore_errors=True)
            if os.environ.get("REQUIRE_UI_TESTS"): raise
            raise unittest.SkipTest(str(error))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.server.stop(); shutil.rmtree(cls.dir,ignore_errors=True)

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width":390,"height":844},has_touch=True,reduced_motion="reduce")
        self.errors,self.commands = [],[]
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.on("request",lambda r:self.commands.append(r.post_data_json) if r.url.endswith("/command") else None)
        self.page.goto(self.server.url)
        self.page.wait_for_selector(".widget,.tile")
        self.page.evaluate("""async()=>{
          const {store,setView,emit}=await import('/js/store.js');
          Object.assign(store.settings,{room_view:'compact',home_view:'overview'});emit('all');setView('rooms');
        }""")

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors,[])

    def test_compact_geometry_last_control_clears_dock_all_sizes_fonts_and_themes(self):
        from tests.integration.test_readability import ReadabilityTests
        page=self.page
        for theme,font,(w,h) in itertools.product(("dark","light"),("small","medium","large"),((390,844),(720,1280),(1280,720),(390,480))):
            with self.subTest(theme=theme,font=font,w=w,h=h):
                page.set_viewport_size({"width":w,"height":h})
                page.evaluate("""async p=>{const{store,emit}=await import('/js/store.js');Object.assign(store.settings,p);emit('all');}""",
                              {"tile_style":theme,"font_size":font})
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"),w)
                self.assertTrue(page.locator(".compact-card").count()>0)
                for selector in ('.compact-card .tile-name','.compact-card .tile-status','.compact-card .card-range > span',
                                 '.compact-card .card-range output','.compact-card .card-mute'):
                    if page.locator(selector).count():
                        self.assertGreaterEqual(ReadabilityTests.surface(self,selector)["contrast"],4.5,selector)
                for card in page.locator(".compact-card").all():
                    self.assertLess(card.bounding_box()["height"],290)
                    for target in card.locator("button,input").all():
                        if target.is_visible():
                            box=target.bounding_box()
                            self.assertGreaterEqual(min(box["width"],box["height"]),48)
                page.evaluate("window.scrollTo(0,document.documentElement.scrollHeight)")
                page.wait_for_timeout(30)
                geometry=page.evaluate("""()=>{
                  const cards=[...document.querySelectorAll('#grid .compact-card')],last=cards.at(-1),
                    dock=document.querySelector('#dock').getBoundingClientRect(),r=last.getBoundingClientRect();
                  const button=last.querySelector('[data-more]'),b=button.getBoundingClientRect();
                  return {bottom:r.bottom,limit:dock.height?dock.top:innerHeight,
                    hit:button.contains(document.elementFromPoint(b.x+b.width/2,b.y+b.height/2))};
                }""")
                self.assertLessEqual(geometry["bottom"],geometry["limit"]-12)
                self.assertTrue(geometry["hit"])
        self.assertEqual(self.commands,[])

    def test_free_positions_and_home_widgets_survive_switching_and_reload(self):
        page=self.page
        original=page.request.get(self.server.url+"/api/v1/state").json()["settings"]
        free={"version":3,"widgets":[{"id":"lr-tv","size":"2x2","positions":{"2":{"x":0,"y":3,"size":"2x2"}}}]}
        page.evaluate("async layout=>(await import('/js/api.js')).api.saveRoomLayout('Living room',layout)",free)
        page.evaluate("async()=>(await import('/js/store.js')).reload()")
        saved=page.request.get(self.server.url+"/api/v1/state").json()["settings"]["room_layouts"]
        page.click('[data-layout-view="room_view"][data-layout-value="free"]')
        page.wait_for_selector(".tiles.layout-grid")
        self.assertIn("grid-row: 4",page.locator('.room-tile[data-wid="lr-tv"]').get_attribute("style").replace("grid-row:","grid-row: "))
        page.reload();page.wait_for_selector(".tiles.layout-grid")
        page.click('[data-layout-view="room_view"][data-layout-value="compact"]')
        page.wait_for_selector(".compact-rooms")
        state=page.request.get(self.server.url+"/api/v1/state").json()["settings"]
        self.assertEqual(state["room_layouts"],saved)
        self.assertEqual(state["home_layout"],original["home_layout"])
        page.evaluate("async()=>(await import('/js/store.js')).setView('home')")
        page.wait_for_selector(".home-overview")
        self.assertEqual(page.locator(".home-grid .t-clock").count(),0)
        page.click('[data-layout-view="home_view"][data-layout-value="free"]')
        page.wait_for_selector(".home-grid .t-clock")
        self.assertEqual(page.locator(".home-overview").count(),0)
        page.click('[data-layout-view="home_view"][data-layout-value="overview"]')
        page.wait_for_selector(".home-overview")
        self.assertEqual(page.request.get(self.server.url+"/api/v1/state").json()["settings"]["home_layout"],original["home_layout"])
        self.assertEqual(self.commands,[])

    def test_inline_sliders_tap_cancel_resize_snapshot_and_release_safety(self):
        page=self.page
        page.evaluate("""async()=>{const{store,upsertDevice}=await import('/js/store.js'),d=store.devices.get('lr-lamp');
          upsertDevice({...d,state:{...d.state,online:true,on:true,brightness:45}});}""")
        range_=page.locator('.tile[data-id="lr-lamp"] [data-card-range]')
        range_.scroll_into_view_if_needed()
        range_.click(position={"x":20,"y":24})
        self.assertEqual(self.commands,[])
        for cancel in ("pointercancel","resize","Escape"):
            range_.scroll_into_view_if_needed();box=range_.bounding_box();x,y=box["x"]+50,box["y"]+24
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+50,y,steps=4)
            page.evaluate("""async()=>{window.heldCard=document.querySelector('.tile[data-id="lr-lamp"] input');
              await(await import('/js/store.js')).reload();}""")
            self.assertTrue(range_.evaluate("e=>e===window.heldCard"))
            self.assertEqual(self.commands,[])
            if cancel=="resize":page.set_viewport_size({"width":400,"height":844})
            elif cancel=="Escape":page.keyboard.press("Escape")
            else:range_.dispatch_event("pointercancel",{"pointerId":1})
            page.mouse.up()
            page.wait_for_timeout(60)
            self.assertEqual(self.commands,[])
        range_.scroll_into_view_if_needed();box=range_.bounding_box();x,y=box["x"]+50,box["y"]+24
        page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+40,y,steps=4)
        self.assertEqual(self.commands,[])
        with page.expect_request(lambda r:r.url.endswith("/command")):page.mouse.up()
        self.assertEqual(len(self.commands),1)
        self.assertEqual(self.commands[0]["action"],"brightness")
        page.wait_for_selector('.tile[data-id="lr-lamp"][aria-busy=false]')
        self.assertTrue(page.locator("#sheet").is_hidden())
        range_.focus()
        with page.expect_request(lambda r:r.url.endswith("/command")):range_.press("ArrowRight")
        self.assertEqual(len(self.commands),2)

    def test_touch_volume_mute_errors_and_unavailable_capabilities(self):
        page=self.page
        page.evaluate("""async()=>{const{store,upsertDevice}=await import('/js/store.js'),d=store.devices.get('lr-soundbar');
          upsertDevice({...d,state:{...d.state,online:true,on:true,volume:12,muted:false}});}""")
        slider=page.locator('.tile[data-id="lr-soundbar"] [data-card-range="volume"]')
        slider.scroll_into_view_if_needed();box=slider.bounding_box();x,y=box["x"]+50,box["y"]+24
        cdp=page.context.new_cdp_session(page)
        cdp.send("Input.dispatchTouchEvent",{"type":"touchStart","touchPoints":[{"x":x,"y":y}]})
        cdp.send("Input.dispatchTouchEvent",{"type":"touchEnd","touchPoints":[]})
        self.assertEqual(slider.input_value(),"12")
        self.assertEqual(self.commands,[])
        cdp.send("Input.dispatchTouchEvent",{"type":"touchStart","touchPoints":[{"x":x,"y":y}]})
        cdp.send("Input.dispatchTouchEvent",{"type":"touchMove","touchPoints":[{"x":x+4,"y":y+60}]})
        cdp.send("Input.dispatchTouchEvent",{"type":"touchEnd","touchPoints":[]})
        self.assertEqual(self.commands,[])
        pending=[]
        page.route("**/devices/lr-soundbar/command",lambda route:pending.append(route))
        slider.scroll_into_view_if_needed();box=slider.bounding_box();x,y=box["x"]+50,box["y"]+24
        cdp.send("Input.dispatchTouchEvent",{"type":"touchStart","touchPoints":[{"x":x,"y":y}]})
        cdp.send("Input.dispatchTouchEvent",{"type":"touchMove","touchPoints":[{"x":x+40,"y":y}]})
        self.assertEqual(self.commands,[])
        with page.expect_request(lambda r:r.url.endswith("/command")):
            cdp.send("Input.dispatchTouchEvent",{"type":"touchEnd","touchPoints":[]})
        self.assertEqual(self.commands[0]["action"],"volume")
        page.wait_for_selector('.tile[data-id="lr-soundbar"][aria-busy=true]')
        self.assertTrue(slider.is_disabled())
        pending.pop().fulfill(status=400,json={"error":"The speaker is busy. Try again."})
        page.wait_for_selector("text=The speaker is busy. Try again.")
        page.wait_for_function("document.querySelector('.tile[data-id=\"lr-soundbar\"] input').value==='12'")
        mute=page.locator('.tile[data-id="lr-soundbar"] [data-act="mute"]')
        mute.focus()
        with page.expect_request(lambda r:r.url.endswith("/command")):mute.press(" ")
        self.assertEqual(self.commands[-1],{"action":"mute","value":True})
        pending.pop().fulfill(status=400,json={"error":"Try later."})
        page.wait_for_selector('.tile[data-id="lr-soundbar"][aria-busy=false]')
        self.assertTrue(page.locator("#sheet").is_hidden())
        page.evaluate("""async()=>{const{store,upsertDevice}=await import('/js/store.js'),d=store.devices.get('lr-soundbar');
          upsertDevice({...d,state:{online:false,on:true,volume:99,muted:false}});}""")
        self.assertTrue(slider.is_disabled());self.assertTrue(mute.is_disabled())
        page.evaluate("""async()=>{const{store,upsertDevice}=await import('/js/store.js'),d=store.devices.get('lr-soundbar');
          upsertDevice({...d,caps:['power'],state:{online:true,on:true}});}""")
        self.assertEqual(page.locator('.tile[data-id="lr-soundbar"] [data-card-range], .tile[data-id="lr-soundbar"] [data-act]').count(),0)

    def test_member_view_preferences_are_scoped_and_do_not_reset_geometry(self):
        page=self.page
        owner=page.request.get(self.server.url+"/api/v1/state").json()["settings"]
        response=page.request.post(self.server.url+"/api/v1/auth/sign-in",data={"profile_id":"sam"})
        self.assertTrue(response.ok)
        page.reload();page.wait_for_selector(".tile,.widget")
        response=page.request.patch(self.server.url+"/api/v1/profiles/me",data={"room_view":"free","home_view":"free","role":"admin"})
        self.assertTrue(response.ok)
        sam=page.request.get(self.server.url+"/api/v1/state").json()
        self.assertEqual(sam["me"]["role"],"member")
        self.assertEqual(sam["settings"]["room_view"],"free")
        self.assertNotIn("lr-lamp",[d["id"] for d in sam["devices"]])
        self.assertEqual(page.request.patch(self.server.url+"/api/v1/profiles/me",data={"room_view":"bad"}).status,400)
        page.request.post(self.server.url+"/api/v1/auth/sign-in",data={"profile_id":"owner","password":"homepanel"})
        again=page.request.get(self.server.url+"/api/v1/state").json()["settings"]
        for key in ("room_view","home_view","home_layout","room_layouts"):
            self.assertEqual(again[key],owner[key])
        self.assertEqual(self.commands,[])

    def test_home_clock_attention_layout_updates_and_safe_activation(self):
        page=self.page
        page.evaluate("""async()=>{const{store,setView,upsertDevice}=await import('/js/store.js');
          const d=store.devices.get('lr-vacuum');upsertDevice({...d,state:{online:true,activity:'docked',battery:100,problem:'Empty the tank'}});
          setView('home');}""")
        for w,h in ((390,844),(720,1280),(1280,720)):
            page.set_viewport_size({"width":w,"height":h})
            page.evaluate("()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
            left,right=page.evaluate("()=>['.overview-clock','.home-attention'].map(s=>document.querySelector(s).getBoundingClientRect().toJSON())")
            if w>=720:self.assertLessEqual(left["x"]+left["width"],right["x"])
            else:self.assertLessEqual(left["y"]+left["height"],right["y"])
        alert=page.locator('[data-attention="lr-vacuum"]')
        alert.focus()
        alert.evaluate("e=>{window.originalAlert=e;}")
        page.evaluate("""async()=>{const{store,upsertDevice}=await import('/js/store.js'),d=store.devices.get('lr-vacuum');
          upsertDevice({...d,state:{...d.state,battery:99}});}""")
        self.assertTrue(alert.evaluate("e=>e===window.originalAlert && e===document.activeElement"))
        alert.press("Enter")
        page.wait_for_selector('#sheet[data-device-id="lr-vacuum"]:not([hidden])')
        self.assertEqual(self.commands,[])
        page.keyboard.press("Escape")
        page.evaluate("""async()=>{const{store,upsertDevice}=await import('/js/store.js'),d=store.devices.get('lr-vacuum');
          upsertDevice({...d,state:{online:true,activity:'docked',battery:100,problem:''}});}""")
        self.assertEqual(page.locator('[data-attention="lr-vacuum"]').count(),0)
        page.evaluate("""async()=>{const{store,applySnapshot}=await import('/js/store.js');
          applySnapshot({devices:[],rooms:[],scenes:[],settings:store.settings,adapters:[],me:{id:'member'}});}""")
        self.assertEqual(page.locator("[data-attention]").count(),0)
        self.assertTrue(page.locator(".attention-clear").is_visible())
        self.assertEqual(self.commands,[])
