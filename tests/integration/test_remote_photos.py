"""Read-only photo APIs and tile lifecycle with isolated fake servers/images."""
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

from tests.helpers import DemoServer
from tests.integration.test_auth import Client
from tests.unit.test_remote_photos import ALBUM, PHOTO, OTHER

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
                    result = [{"id": ALBUM, "albumName": "Wall display"}] if not path.query or source.membership else []
                elif path.path == "/api/search/random":
                    result = source.assets
                elif path.path == "/api/search/metadata":
                    result = {"assets": {"items": [p for p in source.assets if p["id"] == body["id"]]}}
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

    def test_tile_rotation_waits_for_decode_and_pauses_hidden_requests(self):
        page = self.browser.new_page(viewport={"width": 720, "height": 1280})
        pending, calls = [], []
        source = {"ready": True, "configured": True, "permitted": True, "generation": "fixture", "seconds": 30}
        def state(route):
            payload = route.fetch().json()
            payload["settings"]["photo_library"] = source
            payload["settings"]["home_layout"] = {"version": 3, "widgets": [
                {"id": "photos", "type": "photos", "size": "2x2", "options": {}}]}
            route.fulfill(json=payload)
        def image(route):
            calls.append(route)
            if len(calls) == 1:
                route.fulfill(body=self.remote.image, content_type="image/jpeg",
                              headers={"X-Photo-Token": "first", "X-Photo-Generation": source["generation"]})
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
            pending.pop().fulfill(body=self.remote.image, content_type="image/jpeg",
                                  headers={"X-Photo-Token": "second", "X-Photo-Generation": "fixture"})
            page.wait_for_function("(old) => document.querySelector('.photo-layer.visible').src !== old", arg=first)
            page.click('#dock [data-nav="rooms"]')
            page.clock.fast_forward(120000)
            self.assertEqual(len(calls), 2)
            page.click("#ambient")
            page.click('#dock [data-nav="home"]')
            page.wait_for_timeout(50)
            self.assertEqual(len(calls), 3)
            source.update(ready=False, permitted=False, generation="")
            page.evaluate("async () => (await import('/js/store.js')).reload()")
            page.wait_for_function("document.querySelectorAll('.photo-layer[src]').length === 0")
            self.assertGreaterEqual(page.evaluate("window.revokedPhotos.length"), 1)
            self.assertEqual(page.locator(".photo-layer.visible").count(), 0)
        finally:
            page.close()
