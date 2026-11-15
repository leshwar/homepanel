"""Read-only photo APIs and tile lifecycle with isolated fake servers/images."""
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw

from tests.helpers import DemoServer
from tests.integration.test_auth import Client
from tests.unit.test_remote_photos import ALBUM, SECOND_ALBUM, PHOTO, OTHER

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    if os.environ.get("REQUIRE_UI_TESTS"):
        raise
    sync_playwright = None


class FakePhotoServer:
    def __init__(self):
        self.requests = []
        self.major = 2
        self.failure = None
        self.membership = True
        self.album_assets = None
        self.assets = [{"id": p, "type": "IMAGE", "visibility": "timeline",
                        "isTrashed": False, "isOffline": False, "updatedAt": "one"} for p in (PHOTO, OTHER)]
        image = io.BytesIO(); Image.new("RGB", (80, 60), "teal").save(image, "JPEG")
        self.image = image.getvalue()
        source = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.respond(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)))))

            def do_GET(self):
                self.respond(None)

            def respond(self, body):
                path = urllib.parse.urlsplit(self.path)
                source.requests.append((self.command, self.path, body, self.headers.get("x-api-key")))
                if source.failure:
                    code, headers = source.failure
                    self.send_response(code)
                    for name, value in headers.items():
                        self.send_header(name, value)
                    self.end_headers(); self.wfile.write(b"fixture-key must not escape in errors")
                    return
                content_type = "application/json"
                if path.path == "/api/server/version":
                    result = {"major": source.major, "minor": 0, "patch": 0}
                elif path.path == "/api/albums":
                    albums = source.album_assets or {ALBUM: {PHOTO, OTHER}}
                    query = urllib.parse.parse_qs(path.query)
                    selected_photo = query.get("assetId", [None])[0]
                    result = [{"id": a, "albumName": "Wall display"} for a, ids in albums.items()
                              if not selected_photo or source.membership and selected_photo in ids]
                elif path.path == "/api/search/random":
                    albums = source.album_assets or {ALBUM: {PHOTO, OTHER}}
                    result = [p for p in source.assets if all(p["id"] in albums.get(a, set()) for a in body["albumIds"])]
                elif path.path == "/api/search/metadata":
                    albums = source.album_assets or {ALBUM: {PHOTO, OTHER}}
                    result = {"assets": {"items": [p for p in source.assets if p["id"] == body["id"]
                                                  and all(p["id"] in albums.get(a, set()) for a in body["albumIds"])]}}
                elif path.path.endswith("/thumbnail"):
                    result = source.image; content_type = "image/jpeg"
                else:
                    self.send_error(404); return
                raw = result if isinstance(result, bytes) else json.dumps(result).encode()
                self.send_response(200); self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()


class RemotePhotoApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir, sign_in=True).start()
        cls.remote = FakePhotoServer()

    @classmethod
    def tearDownClass(cls):
        cls.remote.stop(); cls.server.stop(); shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.owner = Client(self.server.url); self.owner.sign_in(profile_id="owner", password="homepanel")
        self.remote.failure = None; self.remote.major = 2; self.remote.membership = True
        self.remote.album_assets = None
        self.remote.assets = [{"id": p, "type": "IMAGE", "visibility": "timeline",
                               "isTrashed": False, "isOffline": False, "updatedAt": "one"} for p in (PHOTO, OTHER)]
        self.owner.call("DELETE", "/photo-library")

    def configure(self, profiles=None):
        status, data, _ = self.owner.call("PUT", "/photo-library", {"url": self.remote.url, "key": "fixture-key"})
        self.assertEqual(status, 200, data)
        self.assertNotIn("fixture-key", json.dumps(data))
        status, data, _ = self.owner.call("PUT", "/photo-library/source",
                                        {"albums": [ALBUM], "profiles": profiles or ["owner"], "seconds": 30})
        self.assertEqual(status, 200, data)

    def image(self, client):
        req = urllib.request.Request(self.server.url + "/api/v1/photo-library/next")
        try:
            with client.opener.open(req, timeout=10) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def test_private_proxy_filters_membership_permissions_and_no_key_in_snapshots(self):
        self.configure()
        status, data, _ = self.owner.call("GET", "/state")
        self.assertEqual(status, 200)
        self.assertNotIn("fixture-key", json.dumps(data))
        self.assertNotIn(self.remote.url, json.dumps(data))
        status, image, headers = self.image(self.owner)
        self.assertEqual(status, 200)
        self.assertTrue(image.startswith(b"\xff\xd8"))
        self.assertEqual(headers["Cache-Control"], "private, no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn(headers["X-Photo-Link"],[f"{self.remote.url}/photos/{p}" for p in (PHOTO,OTHER)])
        self.assertNotIn("fixture-key",headers["X-Photo-Link"])
        requested = len(self.remote.requests)
        self.assertEqual(self.image(self.owner)[0], 400)
        self.assertEqual(len(self.remote.requests), requested)
        searches = [body for method, path, body, key in self.remote.requests if path == "/api/search/random"]
        self.assertEqual(searches[-1]["albumIds"], [ALBUM])
        self.assertEqual(searches[-1]["visibility"], "timeline")
        self.assertEqual(searches[-1]["type"], "IMAGE")
        self.assertFalse(searches[-1]["withDeleted"])
        self.assertFalse(searches[-1]["withExif"])
        self.assertFalse(searches[-1]["withPeople"])
        self.assertTrue(any("assetId=" in path for _, path, _, _ in self.remote.requests))
        self.assertTrue(any(path.endswith("thumbnail?size=preview") for _, path, _, _ in self.remote.requests))
        self.assertTrue(all(key is None for _, path, _, key in self.remote.requests if path == "/api/server/version"))
        member = Client(self.server.url); member.sign_in(profile_id="sam")
        self.assertEqual(self.image(member)[0], 404)
        self.assertEqual(member.call("GET", "/photo-library")[0], 403)
        self.configure(["owner", "sam"])
        self.assertEqual(self.image(member)[0], 200)
        self.owner.call("DELETE", "/photo-library")
        self.assertEqual(self.image(member)[0], 404)

    def test_empty_source_removed_membership_and_upstream_errors_are_safe(self):
        self.owner.call("PUT", "/photo-library", {"url": self.remote.url, "key": "fixture-key"})
        self.assertEqual(self.image(self.owner)[0], 400)
        self.configure()
        self.remote.membership = False
        self.assertEqual(self.image(self.owner)[0], 400)
        for code in (401, 403, 429, 503):
            self.remote.failure = (code, {})
            status, data, _ = self.owner.call("GET", "/photo-library/albums")
            self.assertEqual(status, 400)
            self.assertNotIn("fixture-key", json.dumps(data))
        self.remote.failure = None; self.remote.major = 1
        status, data, _ = self.owner.call("PUT", "/photo-library", {"url": self.remote.url, "key": "fixture-key"})
        self.assertEqual(status, 400); self.assertIn("2.x", data["error"])

    def test_redirect_is_never_followed_or_sent_the_key(self):
        other = FakePhotoServer()
        try:
            self.configure()
            self.remote.failure = (302, {"Location": other.url + "/api/albums"})
            status, data, _ = self.owner.call("GET", "/photo-library/albums")
            self.assertEqual(status, 400)
            self.assertIn("redirect", data["error"].lower())
            self.assertEqual(other.requests, [])
        finally:
            other.stop()

    def test_ineligible_assets_never_reach_the_preview_proxy(self):
        self.configure()
        for changes in ({"visibility": "archive"}, {"visibility": "hidden"}, {"visibility": "locked"},
                        {"isTrashed": True}, {"type": "VIDEO"}, {"isArchived": True}, {"isOffline": True}):
            with self.subTest(changes=changes):
                self.remote.assets = [{"id": PHOTO, "type": "IMAGE", "visibility": "timeline",
                                       "isTrashed": False, "isOffline": False, "updatedAt": "one", **changes}]
                self.server.app.state.service.photo_library._attempt.clear()
                before = len([r for r in self.remote.requests if "/thumbnail" in r[1]])
                self.assertEqual(self.image(self.owner)[0], 400)
                self.assertEqual(len([r for r in self.remote.requests if "/thumbnail" in r[1]]), before)

    def test_disjoint_selected_albums_deliver_photos_without_expanding_scope(self):
        self.remote.major = 3
        self.remote.album_assets = {ALBUM: {PHOTO}, SECOND_ALBUM: {OTHER}}
        self.configure()
        status, _, _ = self.owner.call("PUT", "/photo-library/source",
                                      {"albums": [ALBUM, SECOND_ALBUM], "profiles": ["owner"], "seconds": 30})
        self.assertEqual(status, 200)
        before = len(self.remote.requests)
        status, image, _ = self.image(self.owner)
        self.assertEqual(status, 200)
        with Image.open(io.BytesIO(image)) as decoded:
            self.assertEqual(decoded.size, (80, 60))
        queries = [body for _, path, body, _ in self.remote.requests[before:] if path.startswith("/api/search/")]
        self.assertTrue(all(len(q["albumIds"]) == 1 and q["albumIds"][0] in (ALBUM, SECOND_ALBUM) for q in queries))
        self.assertTrue(any("assetId=" in path for _, path, _, _ in self.remote.requests[before:]))
        self.remote.membership = False
        self.server.app.state.service.photo_library._attempt.clear()
        previews = len([r for r in self.remote.requests if "/thumbnail" in r[1]])
        self.assertEqual(self.image(self.owner)[0], 400)
        self.assertEqual(len([r for r in self.remote.requests if "/thumbnail" in r[1]]), previews)


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class RemotePhotoBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(); cls.server = DemoServer(cls.dir).start(); cls.remote = FakePhotoServer()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as error:
            cls.pw.stop(); cls.remote.stop(); cls.server.stop(); shutil.rmtree(cls.dir, ignore_errors=True)
            if os.environ.get("REQUIRE_UI_TESTS"):
                raise
            raise unittest.SkipTest(f"chromium not available: {error}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.remote.stop(); cls.server.stop(); shutil.rmtree(cls.dir, ignore_errors=True)

    def test_secure_setup_add_resize_and_private_tile_lifecycle(self):
        self.remote.major = 3
        self.remote.album_assets = {ALBUM: {PHOTO}, SECOND_ALBUM: {OTHER}}
        page = self.browser.new_page(viewport={"width": 720, "height": 1280}, reduced_motion="reduce")
        errors = []; page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            page.goto(self.server.url); page.wait_for_selector(".widget")
            page.click("#open-settings"); page.click('[data-go="photo-library"]')
            page.wait_for_selector("[data-photo-connect]")
            page.fill('[data-photo-connect] [name=url]', self.remote.url)
            page.fill('[data-photo-connect] [name=key]', "fixture-key")
            page.click('[data-photo-connect] button[type=submit]')
            page.wait_for_selector("[data-photo-source]")
            self.assertEqual(page.input_value('[data-photo-connect] [name=key]'), "")
            self.assertEqual(page.locator("[name=key]").get_attribute("type"), "password")
            page.check(f'[name=album][value="{ALBUM}"]')
            page.check(f'[name=album][value="{SECOND_ALBUM}"]')
            page.click('[data-photo-source] button[type=submit]')
            page.wait_for_function("async () => (await import('/js/store.js')).store.settings.photo_library.ready")
            page.click("#settings [data-back]"); page.click("#settings [data-back]")
            page.click("#edit-home"); page.click("[data-add-widget]"); page.click("[data-add-photos]")
            page.click("[data-edit-done]")
            page.wait_for_selector(".home:not(.editing) .photo-layer.visible")
            self.assertTrue(page.locator(".photo-layer.visible").evaluate("img => img.complete && img.naturalWidth > 0"))
            self.assertTrue(page.locator(".photo-layer.visible").get_attribute("src").startswith("blob:"))
            self.assertEqual(page.locator(".photo-layer.visible").evaluate("e => getComputedStyle(e).transitionDuration"), "0s")
            for width, height in ((393, 852), (1280, 720)):
                page.set_viewport_size({"width": width, "height": height})
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            before = len([r for r in self.remote.requests if r[1] == "/api/search/random"])
            page.click("#edit-home")
            page.wait_for_timeout(100)
            self.assertEqual(len([r for r in self.remote.requests if r[1] == "/api/search/random"]), before)
            page.click("[data-edit-cancel]")
            page.request.delete(self.server.url + "/api/v1/photo-library")
            page.wait_for_function("document.querySelectorAll('.photo-layer[src]').length === 0")
            self.assertIn("Connect", page.locator(".photo-placeholder").inner_text())
            self.assertEqual(errors, [])
        finally:
            page.close()
            self.remote.album_assets = None

    def test_tile_rotation_waits_for_decode_and_pauses_hidden_requests(self):
        page = self.browser.new_page(viewport={"width": 720, "height": 1280})
        pending, calls = [], []
        source = {"ready": True, "configured": True, "permitted": True, "generation": "fixture", "seconds": 30}
        def state(route):
            payload = route.fetch().json()
            payload["settings"]["dim_after_seconds"] = 0
            payload["settings"]["photo_library"] = source
            payload["settings"]["home_layout"] = {"version": 4, "widgets": [
                {"id": "photos", "type": "photos", "size": "2x6", "options": {}}]}
            route.fulfill(json=payload)
        def image(route):
            calls.append(route)
            if len(calls) == 1:
                route.fulfill(body=self.remote.image, content_type="image/jpeg",
                              headers={"X-Photo-Token": "first", "X-Photo-Generation": source["generation"],
                                       "X-Photo-Link":f"https://photos.example/photos/{PHOTO}"})
            else:
                pending.append(route)
        try:
            page.clock.install()
            page.add_init_script("""window.revokedPhotos=[];const original=URL.revokeObjectURL;
                URL.revokeObjectURL=url=>{window.revokedPhotos.push(url);original.call(URL,url);};""")
            page.route("**/api/v1/state", state)
            page.route("**/api/v1/photo-library/next", image)
            page.goto(self.server.url)
            page.wait_for_selector(".photo-layer.visible")
            first = page.locator(".photo-layer.visible").get_attribute("src")
            page.clock.fast_forward(31000)
            page.wait_for_timeout(50)
            self.assertEqual(len(calls), 2)
            self.assertEqual(page.locator(".photo-layer.visible").get_attribute("src"), first)
            page.clock.pause_at(page.evaluate("Date.now()+1"))
            pending.pop().fulfill(body=self.remote.image, content_type="image/jpeg",
                                  headers={"X-Photo-Token": "second", "X-Photo-Generation": "fixture",
                                           "X-Photo-Link":f"https://photos.example/photos/{OTHER}"})
            page.wait_for_function("(old) => document.querySelector('.photo-layer.visible').src !== old", arg=first)
            self.assertIsNone(page.locator("[data-photo-link]").get_attribute("href"))
            page.clock.fast_forward(800)
            self.assertTrue(page.locator("[data-photo-link]").get_attribute("href").endswith(OTHER))
            page.click('#dock [data-nav="rooms"]')
            page.clock.fast_forward(120000)
            self.assertEqual(len(calls), 2)
            with page.expect_request(lambda request: request.url.endswith("/photo-library/next")):
                page.click('#dock [data-nav="home"]')
            source.update(ready=False, permitted=False, generation="")
            page.evaluate("async () => (await import('/js/store.js')).reload()")
            page.wait_for_function("document.querySelectorAll('.photo-layer[src]').length === 0")
            self.assertGreaterEqual(page.evaluate("window.revokedPhotos.length"), 1)
            self.assertEqual(page.locator(".photo-layer.visible").count(), 0)
        finally:
            page.close()

    def test_displayed_photo_link_freezes_for_gestures_and_clears_on_errors_or_revocation(self):
        page=self.browser.new_page(viewport={"width":720,"height":1280},has_touch=True)
        source={"ready":True,"configured":True,"permitted":True,"generation":"links","seconds":30}
        calls, opened, failures=[],[],[]
        def state(route):
            payload=route.fetch().json()
            payload["settings"].update(photo_library=source,dim_after_seconds=0,
                home_layout={"version":4,"widgets":[{"id":"photo","type":"photos","size":"2x6"}]})
            route.fulfill(json=payload)
        def image(route):
            calls.append(route)
            if failures:
                route.fulfill(status=400,json={"error":"Photo unavailable"})
                return
            photo=(PHOTO,OTHER)[(len(calls)-1)%2]
            route.fulfill(body=self.remote.image,content_type="image/jpeg",
                          headers={"X-Photo-Token":str(len(calls)),"X-Photo-Generation":"links",
                                   "X-Photo-Link":f"https://photos.example/immich/photos/{photo}"})
        def external(route):
            opened.append((route.request.url,route.request.headers))
            route.fulfill(content_type="text/html",body="<title>Photo fixture</title>")
        try:
            page.clock.install(time=datetime(2026,11,15,13))
            page.route("**/api/v1/state",state)
            page.route("**/api/v1/photo-library/next",image)
            page.context.route("https://photos.example/**",external)
            page.goto(self.server.url);page.wait_for_selector("[data-photo-link][href]")
            anchor=page.locator("[data-photo-link]")
            first=anchor.get_attribute("href")
            self.assertTrue(first.endswith(PHOTO))
            box=anchor.bounding_box()
            page.mouse.move(box["x"]+30,box["y"]+30);page.mouse.down()
            page.clock.fast_forward(31000)
            self.assertEqual(len(calls),1)
            self.assertEqual(anchor.get_attribute("href"),first)
            with page.expect_popup() as popup:
                page.mouse.up()
            popup.value.wait_for_load_state()
            self.assertEqual(popup.value.url,first)
            self.assertTrue(popup.value.evaluate("window.opener===null"))
            popup.value.close()
            page.wait_for_function("first=>{const a=document.querySelector('[data-photo-link][href]');return a&&a.href!==first;}",arg=first)
            current=anchor.get_attribute("href")
            with page.expect_popup() as popup:
                anchor.focus();anchor.press("Enter")
            popup.value.wait_for_load_state()
            self.assertEqual(popup.value.url,current);popup.value.close()
            self.assertTrue(all("referer" not in headers and "x-api-key" not in headers for _,headers in opened))
            before=len(opened)
            box=anchor.bounding_box()
            page.mouse.move(box["x"]+20,box["y"]+20);page.mouse.down()
            page.mouse.move(box["x"]+60,box["y"]+25,steps=4);page.mouse.up()
            page.clock.fast_forward(400)
            self.assertEqual(len(opened),before)
            page.click("#edit-home")
            self.assertIsNone(page.locator("[data-photo-link]").get_attribute("href"))
            page.click("[data-edit-cancel]")
            page.wait_for_selector("[data-photo-link][href]")
            failures.append(True);page.clock.fast_forward(31000)
            page.wait_for_selector("text=Photo unavailable")
            self.assertEqual(page.locator("[data-photo-link][href],.photo-layer[src]").count(),0)
            source.update(ready=False,permitted=False,generation="")
            page.evaluate("async()=>(await import('/js/store.js')).reload()")
            self.assertEqual(page.locator("[data-photo-link][href],.photo-layer[src],.ambient-photo-layer[src]").count(),0)
        finally:
            page.unroute_all(behavior="wait")
            page.close()

    def test_idle_reuses_photo_stream_centers_all_faces_and_stays_dark_at_night(self):
        page=self.browser.new_page(viewport={"width":720,"height":1280},has_touch=True,reduced_motion="reduce")
        source={"ready":True,"configured":True,"permitted":True,"generation":"idle","seconds":30}
        out=io.BytesIO();Image.new("RGB",(160,100),"white").save(out,"JPEG")
        calls, popups=[],[]
        page.on("popup",lambda popup:popups.append(popup))
        def state(route):
            payload=route.fetch().json()
            payload["settings"].update(photo_library=source,dim_after_seconds=0,frame_night_clock=True,
                home_layout={"version":4,"widgets":[{"id":"photo","type":"photos","size":"2x6"}]})
            route.fulfill(json=payload)
        def image(route):
            calls.append(route)
            route.fulfill(body=out.getvalue(),content_type="image/jpeg",headers={
                "X-Photo-Token":str(len(calls)),"X-Photo-Generation":"idle","X-Photo-Link":f"https://photos.example/photos/{PHOTO}"})
        try:
            page.clock.install(time=datetime(2026,11,15,13))
            page.route("**/api/v1/state",state);page.route("**/api/v1/photo-library/next",image)
            page.goto(self.server.url);page.wait_for_selector(".photo-layer.visible")
            initial=page.locator(".photo-layer.visible").get_attribute("src")
            for width,height,font in ((390,844,"small"),(720,1280,"medium"),(1280,720,"large"),(390,480,"large")):
                page.set_viewport_size({"width":width,"height":height})
                for face in ("digital","analog","words","date","night"):
                    with self.subTest(width=width,face=face):
                        page.evaluate("""async p=>{
                          const s=await import('/js/store.js');Object.assign(s.store.settings,{font_size:p.font,clock_face:p.face});
                          s.emit('all');document.querySelector('#ambient').hidden=false;
                          (await import('/js/clockfaces.js')).renderAmbient();
                        }""",{"font":font,"face":face})
                        group=page.locator("#ambient-content").bounding_box()
                        self.assertLessEqual(abs(group["x"]+group["width"]/2-width/2),9)
                        self.assertLessEqual(abs(group["y"]+group["height"]/2-height/2),9)
                        self.assertGreaterEqual(group["x"],0);self.assertGreaterEqual(group["y"],0)
                        self.assertLessEqual(group["x"]+group["width"],width+1)
                        self.assertLessEqual(group["y"]+group["height"],height+1)
                        if face=="night":
                            self.assertTrue(page.locator(".ambient-photos").is_hidden())
                            continue
                        idle=page.locator(".ambient-photo-layer.visible")
                        self.assertEqual(idle.get_attribute("src"),initial)
                        self.assertEqual(idle.evaluate("e=>getComputedStyle(e).objectFit"),"cover")
                        self.assertEqual(page.locator(".photo-layer.visible").evaluate("e=>getComputedStyle(e).objectFit"),"contain")
                        self.assertEqual(idle.bounding_box(),{"x":0,"y":0,"width":width,"height":height})
                        for text in page.locator("#ambient .cf-time,#ambient .cf-phrase").all():
                            self.assertGreaterEqual(int(text.evaluate("e=>getComputedStyle(e).fontWeight")),400)
                        pixel=Image.open(io.BytesIO(page.screenshot())).convert("RGB").getpixel((2,2))
                        self.assertGreater(min(pixel),160)  # photo away from the clock is visibly brighter
                        self.assertLess(max(pixel),210)
                        self.assertEqual(len(calls),1)
            page.clock.set_system_time(datetime(2026,11,15,23))
            page.evaluate("""async()=>{
              (await import('/js/store.js')).store.settings.clock_face='date';
              (await import('/js/clockfaces.js')).renderAmbient();
            }""")
            page.clock.fast_forward(61000)
            self.assertTrue(page.locator(".ambient-photos").is_hidden())
            self.assertEqual(len(calls),1)
            page.touchscreen.tap(150,250)
            self.assertTrue(page.locator("#ambient").is_hidden());self.assertEqual(popups,[])
            source.update(ready=False,permitted=False,generation="")
            page.evaluate("async()=>(await import('/js/store.js')).reload()")
            self.assertEqual(page.locator(".photo-layer[src],.ambient-photo-layer[src],[data-photo-link][href]").count(),0)
        finally:
            page.unroute_all(behavior="wait")
            page.close()

    def test_idle_photo_visibility_increases_without_losing_text_contrast(self):
        page=self.browser.new_page(viewport={"width":1280,"height":720},reduced_motion="reduce")
        fixtures=[]
        for color in ("white",(48,48,48),"mixed"):
            image=Image.new("RGB",(180,120),"white" if color=="mixed" else color)
            if color=="mixed":
                draw=ImageDraw.Draw(image)
                draw.rectangle((0,0,59,119),fill=(40,70,100))
                draw.rectangle((120,0,179,119),fill=(230,170,90))
            out=io.BytesIO();image.save(out,"PNG");fixtures.append(out.getvalue())
        active=[fixtures[0]]
        def state(route):
            payload=route.fetch().json()
            payload["settings"].update(photo_library={"ready":True,"configured":True,"permitted":True,"generation":"brightness","seconds":300},
                                       dim_after_seconds=0)
            route.fulfill(json=payload)
        def photo(route):
            route.fulfill(body=active[0],content_type="image/png",
                          headers={"X-Photo-Token":"brightness","X-Photo-Generation":"brightness"})
        def luma(rgb):
            linear=[v/255/12.92 if v/255<=.04045 else ((v/255+.055)/1.055)**2.4 for v in rgb]
            return sum(v*w for v,w in zip(linear,(.2126,.7152,.0722),strict=True))
        try:
            page.clock.install(time=datetime(2026,11,15,13))
            page.route("**/api/v1/state",state);page.route("**/api/v1/photo-library/next",photo)
            for index,fixture in enumerate(fixtures):
                active[0]=fixture
                page.goto(self.server.url);page.wait_for_selector(".widget")
                page.evaluate("async()=>{document.querySelector('#ambient').hidden=false;(await import('/js/clockfaces.js')).renderAmbient();}")
                page.wait_for_selector("#ambient[data-photos=true] .ambient-photo-layer.visible")
                for width,height,font in ((1280,720,"large"),(720,1280,"medium"),(390,844,"small")):
                    page.set_viewport_size({"width":width,"height":height})
                    for face in ("digital","date","analog","words"):
                        with self.subTest(fixture=index,width=width,face=face):
                            page.evaluate("""async p=>{
                              const s=await import('/js/store.js');Object.assign(s.store.settings,{clock_face:p.face,font_size:p.font});
                              s.emit('all');(await import('/js/clockfaces.js')).renderAmbient();
                            }""",{"font":font,"face":face})
                            # Both renders use the same decoded fixture and geometry.
                            hidden="#ambient-face {visibility:hidden!important}"
                            before=Image.open(io.BytesIO(page.screenshot(style=hidden+
                                ".ambient-photo-scrim{background:rgb(0 0 0 / .72)!important}#ambient-content::before{content:none!important}"))).convert("RGB")
                            after=Image.open(io.BytesIO(page.screenshot(style=hidden))).convert("RGB")
                            points=[(x,y) for x in (2,width//2,width-3) for y in (2,height-3)]
                            old=sum(sum(before.getpixel(p)) for p in points)
                            new=sum(sum(after.getpixel(p)) for p in points)
                            self.assertGreater(new,old*1.8)
                            regions=page.locator("#ambient-face").evaluate("""root=>{
                              const selectors='.cf-time,.cf-meridiem,.cf-phrase,.cf-lead,.cf-sub,.cf-day,.cf-weekday,.cf-kicker,.ambient-activity';
                              return [...root.querySelectorAll(selectors)].filter(e=>e.getClientRects().length).map(e=>{
                                const range=document.createRange();range.selectNodeContents(e);
                                return {color:getComputedStyle(e).color.match(/[\\d.]+/g).slice(0,3).map(Number),
                                  rects:[...range.getClientRects()].map(r=>({x:r.x,y:r.y,w:r.width,h:r.height}))};
                              });
                            }""")
                            for region in regions:
                                for r in region["rects"]:
                                    for x in (r["x"]+1,r["x"]+r["w"]/2,r["x"]+r["w"]-1):
                                        for y in (r["y"]+1,r["y"]+r["h"]/2,r["y"]+r["h"]-1):
                                            background=after.getpixel((max(0,min(width-1,round(x))),max(0,min(height-1,round(y)))))
                                            self.assertGreaterEqual((luma(region["color"])+.05)/(luma(background)+.05),4.5,(region,r,background))
                page.evaluate("async()=>{(await import('/js/clockfaces.js')).renderAmbient(new Date(2026,10,15,23));}")
                self.assertTrue(page.locator(".ambient-photos").is_hidden())
                self.assertEqual(page.locator("#ambient-content").evaluate("e=>getComputedStyle(e,'::before').content"),"none")
        finally:
            page.unroute_all(behavior="wait")
            page.close()

    def test_full_frame_fits_after_transitions_resizes_and_responsive_changes(self):
        page=self.browser.new_page(viewport={"width":720,"height":1280},reduced_motion="reduce")
        original=None
        colors=((230,30,40),(30,200,40),(30,50,230),(230,210,30))
        images=[]
        for width,height in ((120,360),(360,120),(240,240)):
            image=Image.new("RGB",(width,height),(180,180,180))
            draw=ImageDraw.Draw(image)
            for color,(x,y) in zip(colors,((0,0),(.8,0),(0,.8),(.8,.8)),strict=True):
                draw.rectangle((int(x*width),int(y*height),int((x+.2)*width)-1,int((y+.2)*height)-1),fill=color)
            out=io.BytesIO();image.save(out,"PNG");images.append(out.getvalue())
        calls=[]
        def state(route):
            payload=route.fetch().json()
            payload["settings"]["photo_library"]={"ready":True,"configured":True,"permitted":True,"generation":"fit","seconds":30}
            route.fulfill(json=payload)
        def image(route):
            index=len(calls)%len(images);calls.append(index)
            route.fulfill(body=images[index],content_type="image/png",
                          headers={"X-Photo-Token":str(len(calls)),"X-Photo-Generation":"fit"})
        def assert_frame():
            photo=page.locator(".photo-layer.visible")
            metrics=photo.evaluate("""e=>{
              const r=e.getBoundingClientRect(),tile=e.closest('.widget').getBoundingClientRect();
              return {width:r.width,height:r.height,nw:e.naturalWidth,nh:e.naturalHeight,
                inside:r.x>=tile.x&&r.right<=tile.right&&r.y>=tile.y+56&&r.bottom<=tile.bottom-44};
            }""")
            self.assertTrue(metrics["inside"])
            screenshot=Image.open(io.BytesIO(photo.screenshot())).convert("RGB")
            scale=min(metrics["width"]/metrics["nw"],metrics["height"]/metrics["nh"])
            width,height=metrics["nw"]*scale,metrics["nh"]*scale
            left,top=(metrics["width"]-width)/2,(metrics["height"]-height)/2
            # Edge markers must all survive at their aspect-preserving locations.
            # cover or fill would crop or displace these actual rendered pixels.
            for expected,(x,y) in zip(colors,((.1,.1),(.9,.1),(.1,.9),(.9,.9)),strict=True):
                sx=min(screenshot.width-1,round(left+x*width))
                sy=min(screenshot.height-1,round(top+y*height))
                actual=screenshot.getpixel((sx,sy))
                self.assertLess(max(abs(a-b) for a,b in zip(actual,expected,strict=True)),70,(metrics,actual,expected))
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"),page.viewport_size["width"])
        try:
            page.clock.install()
            page.route("**/api/v1/state",state)
            page.route("**/api/v1/photo-library/next",image)
            page.goto(self.server.url);page.wait_for_selector(".widget")
            original=page.request.get(self.server.url+"/api/v1/state").json()["settings"]
            page.evaluate("""async()=>{
              const a=(await import('/js/api.js')).api;
              await a.saveSettings({dim_after_seconds:0});
              await a.saveLayout({version:4,widgets:[{id:'fit-photo',type:'photos',size:'2x6'}]});
              const s=await import('/js/store.js');await s.reload();s.setView('home');
            }""")
            page.wait_for_selector(".photo-layer.visible")
            for viewport,font in (({"width":390,"height":844},"small"),({"width":720,"height":1280},"medium"),
                                  ({"width":1280,"height":720},"large")):
                page.set_viewport_size(viewport)
                for size in ("2x3","4x3","2x8"):
                    with self.subTest(viewport=viewport,font=font,size=size):
                        page.evaluate("""async p=>{
                          const a=(await import('/js/api.js')).api;
                          await a.saveSettings({font_size:p.font});
                          await a.saveLayout({version:4,widgets:[{id:'fit-photo',type:'photos',size:p.size}]});
                          await (await import('/js/store.js')).reload();
                        }""",{"font":font,"size":size})
                        for _ in range(3):
                            assert_frame()
                            previous=page.locator(".photo-layer.visible").get_attribute("src")
                            page.clock.fast_forward(31000)
                            page.wait_for_function("old=>document.querySelector('.photo-layer.visible')?.src!==old",arg=previous)
            page.evaluate("async()=>(await import('/js/home.js')).startEditing()")
            page.locator("[data-resize]").press("ArrowDown")
            assert_frame()
            bounds=page.locator(".widget").bounding_box()
            page.click("[data-edit-done]");page.wait_for_selector(".editbar",state="hidden")
            self.assertEqual(page.locator(".widget").bounding_box(),bounds)
            assert_frame()
            page.click("#edit-home");self.assertEqual(page.locator(".widget").bounding_box(),bounds)
            page.click("[data-edit-cancel]");assert_frame()
        finally:
            page.unroute_all(behavior="wait")
            if original is not None:
                page.request.put(self.server.url+"/api/v1/settings",
                                 data={k:original[k] for k in ("font_size","dim_after_seconds")})
                page.request.put(self.server.url+"/api/v1/profiles/me/layout",data={"home_layout":original["home_layout"]})
            page.close()
