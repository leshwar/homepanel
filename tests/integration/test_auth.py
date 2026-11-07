"""Sign-in end to end: the real server in demo mode with sign-in turned on, called over
HTTP like a phone would, and the sign-in screens in a real browser.

Demo profiles: Owner (admin, owner@example.com / homepanel) and Sam
(one-tap member, sees bd-fan, bd-lamp, bd-tv, kt-pendant).
"""
import http.cookiejar
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from tests.helpers import DemoServer

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    if os.environ.get("REQUIRE_UI_TESTS"):
        raise
    sync_playwright = None

SAM_SEES = ["bd-fan", "bd-lamp", "bd-tv", "kt-pendant"]


class Client:
    """One browser: its own cookie jar."""

    def __init__(self, url):
        self.url = url
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"{self.url}/api/v1{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"null"), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null"), e.headers

    def sign_in(self, **body):
        status, data, headers = self.call("POST", "/auth/sign-in", body)
        assert status == 200, data
        return headers


class SignInApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir, sign_in=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def client(self):
        return Client(self.server.url)

    def test_api_refuses_without_a_session(self):
        c = self.client()
        for method, path in (("GET", "/state"), ("GET", "/events"), ("POST", "/devices/lr-lamp/command"),
                             ("GET", "/logs"), ("PUT", "/settings"), ("GET", "/profiles"), ("GET", "/photos")):
            status, data, _ = c.call(method, path, {} if method != "GET" else None)
            self.assertEqual(status, 401, path)
            self.assertTrue(data["signin"])
        status, health, _ = c.call("GET", "/health")
        self.assertEqual((status, set(health)), (200, {"ok", "time", "sign_in"}))   # nothing about the home
        _, s, _ = c.call("GET", "/auth/session")
        self.assertFalse(s["signed_in"])
        self.assertEqual([p["name"] for p in s["profiles"]], ["Owner", "Sam"])
        self.assertNotIn("email", s["profiles"][0])
        self.assertNotIn("latitude", s["display"])

    def test_sign_in_sets_a_safe_cookie(self):
        c = self.client()
        status, err, _ = c.call("POST", "/auth/sign-in", {"profile_id": "sam", "pin": "1111"})
        self.assertEqual(status, 401)
        self.assertIn("no longer used", err["error"])
        headers = c.sign_in(profile_id="sam")
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn("Max-Age=", cookie)
        self.assertNotIn("Secure", cookie)            # plain http on the home network
        _, s, _ = c.call("GET", "/auth/session")
        self.assertEqual((s["signed_in"], s["me"]["name"]), (True, "Sam"))
        c.call("POST", "/auth/sign-out", {})
        self.assertEqual(c.call("GET", "/state")[0], 401)

    def test_email_and_password(self):
        c = self.client()
        status, err, _ = c.call("POST", "/auth/sign-in", {"email": "owner@example.com", "password": "wrong-password"})
        self.assertEqual(status, 401)
        c.sign_in(email="Owner@Example.com", password="homepanel")
        _, state, _ = c.call("GET", "/state")
        self.assertEqual(len(state["devices"]), 13)
        self.assertEqual(state["me"]["role"], "admin")
        self.assertNotIn("hash", json.dumps(state))

    def test_member_cannot_control_a_hidden_device(self):
        sam = self.client()
        sam.sign_in(profile_id="sam")
        _, state, _ = sam.call("GET", "/state")
        self.assertEqual(sorted(d["id"] for d in state["devices"]), SAM_SEES)
        status, err, _ = sam.call("POST", "/devices/lr-tv/command", {"action": "power", "value": True})
        self.assertEqual((status, err["error"]), (404, "Not found"))
        self.assertEqual(sam.call("POST", "/devices/lr-tv/refresh", {})[0], 404)
        status, d, _ = sam.call("POST", "/devices/bd-lamp/command", {"action": "brightness", "value": 33})
        self.assertEqual((status, d["state"]["brightness"]), (200, 33))
        status, err, _ = sam.call("PATCH", "/devices/bd-lamp", {"name": "Mine now"})
        self.assertEqual(status, 403)
        self.assertIn("admin", err["error"])
        self.assertEqual(sam.call("POST", "/scenes/movie/run", {})[0], 404)

    def test_members_cannot_create_reorder_or_see_empty_and_hidden_rooms(self):
        owner, sam = self.client(), self.client()
        owner.sign_in(profile_id="owner", password="homepanel")
        sam.sign_in(profile_id="sam")
        original = owner.call("GET", "/state")[1]["rooms"]
        try:
            owner.call("PUT", "/rooms", {"rooms": ["Empty office", *original]})
            self.assertEqual(sam.call("GET", "/state")[1]["rooms"], ["Bedroom", "Kitchen"])
            self.assertEqual(sam.call("PUT", "/rooms", {"rooms": ["Mine"]})[0], 403)
            self.assertEqual(sam.call("PUT", "/rooms", {"rooms": ["Study", "Kitchen"],
                                                       "rename": {"from": "Bedroom", "to": "Study"}})[0], 403)
            self.assertEqual(owner.call("GET", "/state")[1]["rooms"], ["Empty office", *original])
        finally:
            owner.call("PUT", "/rooms", {"rooms": original})

    def test_members_see_wallpapers_and_pictures_but_cant_change_them(self):
        sam = self.client()
        sam.sign_in(profile_id="sam")
        status, walls, _ = sam.call("GET", "/wallpapers")
        self.assertEqual(status, 200)
        self.assertTrue(walls["wallpapers"])
        req = urllib.request.Request(f"{self.server.url}/api/v1{walls['wallpapers'][0]['url'][7:]}")
        with sam.opener.open(req, timeout=10) as r:
            self.assertTrue(r.headers["Content-Type"].startswith("image/"))
        self.assertEqual(sam.call("POST", "/wallpapers", {})[0], 403)
        self.assertEqual(sam.call("DELETE", f"/wallpapers/{walls['wallpapers'][0]['id']}")[0], 403)
        self.assertEqual(sam.call("DELETE", "/devices/bd-lamp/picture")[0], 403)
        self.assertEqual(sam.call("GET", "/devices/lr-tv/picture")[0], 404)       # hidden from Sam: not even a hint
        self.assertEqual(self.client().call("GET", "/wallpapers")[0], 401)       # nobody signed in

    def test_events_stream_never_sends_hidden_devices(self):
        sam, owner = self.client(), self.client()
        sam.sign_in(profile_id="sam")
        owner.sign_in(profile_id="owner", password="homepanel")
        got: list[str] = []
        stream = sam.opener.open(f"{self.server.url}/api/v1/events", timeout=10)

        def read():
            try:
                for line in stream:
                    if line.startswith(b"data: "):
                        ev = json.loads(line[6:])
                        if ev.get("type") == "device":
                            got.append(ev["device"]["id"])
            except Exception:
                pass
        threading.Thread(target=read, daemon=True).start()
        time.sleep(0.3)
        owner.call("POST", "/devices/lr-lamp/command", {"action": "toggle"})
        owner.call("POST", "/devices/bd-fan/command", {"action": "toggle"})
        for _ in range(50):
            if "bd-fan" in got:
                break
            time.sleep(0.1)
        stream.close()
        self.assertIn("bd-fan", got)
        self.assertTrue(set(got) <= set(SAM_SEES), got)

    def test_each_profile_has_its_own_home_layout(self):
        sam, owner = self.client(), self.client()
        sam.sign_in(profile_id="sam")
        owner.sign_in(profile_id="owner", password="homepanel")
        _, before, _ = owner.call("GET", "/state")
        try:
            mine = {"widgets": [{"id": "weather", "type": "weather", "size": "2x2"},
                                {"id": "dev-bd-tv", "type": "device", "size": "2x2", "options": {"device_id": "bd-tv"}}]}
            status, saved, _ = sam.call("PUT", "/profiles/me/layout", {"home_layout": mine})
            self.assertEqual((status, saved["home_layout"]["widgets"][0]["size"]), (200, "2x2"))
            _, s, _ = sam.call("GET", "/state")
            self.assertEqual([w["id"] for w in s["settings"]["home_layout"]["widgets"]], ["weather"])   # no devices on Home
            _, o, _ = owner.call("GET", "/state")
            self.assertEqual(o["settings"]["home_layout"], before["settings"]["home_layout"])
        finally:
            sam.call("PUT", "/profiles/me/layout", {"home_layout": None})

    def test_admin_manages_profiles(self):
        owner = self.client()
        owner.sign_in(profile_id="owner", password="homepanel")
        status, kid, _ = owner.call("POST", "/profiles", {"name": "Kid", "devices": ["bd-lamp", "nope"]})
        self.assertEqual((status, kid["devices"], kid["has_password"]), (200, ["bd-lamp"], False))
        self.assertNotIn("pin_hash", kid)
        status, err, _ = owner.call("POST", "/profiles", {"name": "Kid 2", "pin": "1234"})
        self.assertEqual(status, 400)
        self.assertIn("no longer used", err["error"])
        k = self.client()
        k.sign_in(profile_id=kid["id"])
        self.assertEqual([d["id"] for d in k.call("GET", "/state")[1]["devices"]], ["bd-lamp"])
        owner.call("PATCH", f"/profiles/{kid['id']}", {"devices": "all"})
        self.assertEqual(len(k.call("GET", "/state")[1]["devices"]), 13)
        self.assertEqual(owner.call("DELETE", f"/profiles/{kid['id']}")[0], 200)
        self.assertEqual(k.call("GET", "/state")[0], 401)                # their sessions end with the profile
        status, err, _ = owner.call("DELETE", "/profiles/owner")
        self.assertEqual(status, 400)

    def test_room_layout_positions_are_private_and_validated(self):
        sam, owner = self.client(), self.client()
        sam.sign_in(profile_id="sam")
        owner.sign_in(profile_id="owner", password="homepanel")
        layout = {"widgets": [{"id": "bd-lamp", "positions": {"4": {"x": 2, "y": 3, "size": "2x2"}}}]}
        try:
            status, saved, _ = sam.call("PUT", "/profiles/me/rooms/layout", {"room": "Bedroom", "layout": layout})
            self.assertEqual(status, 200)
            self.assertEqual(saved["room_layouts"]["Bedroom"]["widgets"][0]["positions"], layout["widgets"][0]["positions"])
            self.assertEqual(owner.call("GET", "/state")[1]["settings"]["room_layouts"], {})
            bad = {"widgets": [*layout["widgets"], {"id": "bd-fan", "positions": {"4": {"x": 3, "y": 3, "size": "1x1"}}}]}
            self.assertEqual(sam.call("PUT", "/profiles/me/rooms/layout", {"room": "Bedroom", "layout": bad})[0], 400)
            self.assertEqual(sam.call("GET", "/state")[1]["settings"]["room_layouts"], saved["room_layouts"])
            for did in ("lr-tv", "kt-pendant", "missing"):
                self.assertEqual(sam.call("PUT", "/profiles/me/rooms/layout",
                                         {"room": "Bedroom", "layout": {"widgets": [{"id": did}]}})[0], 400)
        finally:
            sam.call("PUT", "/profiles/me/rooms/layout", {"room": "Bedroom", "layout": None})

    def test_wall_panel_keeps_session_until_explicit_sign_out(self):
        panel = self.client()
        panel.sign_in(profile_id="owner", password="homepanel", panel=True)
        _, s, _ = panel.call("GET", "/auth/session")
        self.assertTrue(s["panel"])
        self.assertNotIn("locked", s)
        self.assertNotIn("lock_after_minutes", s["display"])
        self.assertEqual(panel.call("GET", "/state")[0], 200)
        panel.sign_in(profile_id="sam")
        _, s, _ = panel.call("GET", "/auth/session")
        self.assertEqual((s["me"]["name"], s["panel"]), ("Sam", True))   # still the wall panel
        panel.call("POST", "/auth/sign-out", {})
        _, s, _ = panel.call("GET", "/auth/session")
        self.assertFalse(s["signed_in"])
        self.assertEqual(panel.call("GET", "/state")[0], 401)



class RateLimitTests(unittest.TestCase):
    """Its own server: the failed tries here would lock out the other tests' address."""

    def test_sign_in_is_rate_limited(self):
        d = tempfile.mkdtemp()
        server = DemoServer(d, sign_in=True).start()
        self.addCleanup(shutil.rmtree, d, True)
        self.addCleanup(server.stop)
        c = Client(server.url)
        codes = [c.call("POST", "/auth/sign-in", {"email": "nobody@example.com", "password": f"guess-{i}"})[0]
                 for i in range(9)]
        self.assertEqual(codes[:8], [401] * 8)
        self.assertEqual(codes[8], 429)
        status, err, headers = c.call("POST", "/auth/sign-in", {"email": "nobody@example.com", "password": "x"})
        self.assertEqual(status, 429)
        self.assertIn("Too many tries", err["error"])
        self.assertTrue(headers["Retry-After"])


class MigrationTests(unittest.TestCase):
    """A panel from before profiles: keep devices and choose the new Owner with one tap."""

    def test_old_pin_profiles_keep_layouts_devices_and_passwords(self):
        from app.core.profiles import hash_secret
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        password_hash = hash_secret("existing password")
        layout = {"version": 2, "widgets": [{"id": "weather", "type": "weather", "size": "1x1"}]}
        with open(os.path.join(d, "demo.json"), "w") as f:
            json.dump({
                "devices": [{"id": "kt-kettle", "adapter": "demo", "name": "Kettle", "kind": "plug",
                             "room": "Kitchen", "config": {"_uid": "kt-kettle"}, "caps": ["power"]}],
                "rooms": ["Kitchen"], "settings": {"lock_after_minutes": 2},
                "profiles": [
                    {"id": "old-owner", "name": "Owner", "role": "admin", "email": "",
                     "devices": "all", "pin_hash": hash_secret("1234"), "home_layout": layout},
                    {"id": "password", "name": "Password", "role": "member", "email": "me@example.com",
                     "devices": ["kt-kettle"], "pin_hash": hash_secret("5678"), "password_hash": password_hash},
                ],
            }, f)
        server = DemoServer(d, sign_in=True).start()
        self.addCleanup(server.stop)
        c = Client(server.url)
        c.sign_in(profile_id="old-owner")
        state = c.call("GET", "/state")[1]
        self.assertEqual(state["settings"]["home_layout"]["widgets"], layout["widgets"])
        self.assertEqual([x["id"] for x in state["devices"]], ["kt-kettle"])
        other = Client(server.url)
        self.assertEqual(other.call("POST", "/auth/sign-in", {"profile_id": "password"})[0], 401)
        other.sign_in(profile_id="password", password="existing password")
        with open(os.path.join(d, "demo.json")) as f:
            saved = json.load(f)
        self.assertTrue(all("pin_hash" not in p for p in saved["profiles"]))
        self.assertEqual(saved["profiles"][1]["password_hash"], password_hash)
        self.assertNotIn("lock_after_minutes", saved["settings"])

    def test_first_open_after_upgrading(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "demo.json"), "w") as f:
                json.dump({"version": 1, "rooms": ["Kitchen"], "settings": {"home_name": "Our flat"},
                           "devices": [{"id": "kt-kettle", "adapter": "demo", "name": "Kettle", "kind": "plug",
                                        "room": "Kitchen", "config": {"_uid": "kt-kettle"}, "caps": ["power"]}]}, f)
            server = DemoServer(d, sign_in=True).start()
            try:
                c = Client(server.url)
                status, err, _ = c.call("GET", "/state")
                self.assertEqual((status, err["signin"]), (401, True))
                _, s, _ = c.call("GET", "/auth/session")
                self.assertEqual([p["name"] for p in s["profiles"]], ["Owner"])
                self.assertNotIn("setup", s)
                self.assertEqual(s["display"]["home_name"], "Our flat")
                status, s, _ = c.call("POST", "/auth/sign-in", {"profile_id": s["profiles"][0]["id"], "panel": True})
                self.assertEqual((status, s["me"]["name"], s["panel"]), (200, "Owner", True))
                _, state, _ = c.call("GET", "/state")
                self.assertEqual([x["id"] for x in state["devices"]], ["kt-kettle"])
                with open(os.path.join(d, "demo.json")) as f:
                    saved = f.read()
                self.assertNotIn("pin_hash", saved)
            finally:
                server.stop()
        finally:
            shutil.rmtree(d, ignore_errors=True)


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class SignInUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir, sign_in=True).start()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:  # browser binaries not downloaded
            cls.pw.stop()
            cls.server.stop()
            if os.environ.get("REQUIRE_UI_TESTS"):
                raise
            raise unittest.SkipTest(f"chromium not available: {e}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.errors = []

    def open(self, width=393, height=852):
        ctx = self.browser.new_context(viewport={"width": width, "height": height}, has_touch=True, reduced_motion="reduce")
        page = ctx.new_page()
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(self.server.url + "/")
        self.addCleanup(ctx.close)
        return page

    def test_one_tap_profile_and_password_profile_switch(self):
        page = self.open()
        page.wait_for_selector('.avatar-choice[data-pick="sam"]')
        self.assertFalse(page.locator("#app").is_visible())               # nothing of the home before sign-in
        box = page.locator('[data-pick="sam"]').bounding_box()
        self.assertGreaterEqual(box["height"], 48)
        page.click('[data-pick="sam"]')
        page.wait_for_selector("#signin", state="hidden")
        page.wait_for_selector("#profile-btn:not([hidden])")
        self.assertEqual(page.inner_text("#profile-btn"), "S")
        page.wait_for_selector('.widget[data-wid="rooms"] [data-go-room]')
        rooms = page.eval_on_selector_all('.widget[data-wid="rooms"] [data-go-room]', "els => els.map(e => e.dataset.goRoom)")
        self.assertEqual(rooms, ["Bedroom", "Kitchen"])                   # Living room: only hidden devices
        self.assertEqual(page.locator('.tile[data-id="lr-tv"]').count(), 0)
        page.click('[data-nav="rooms"]')
        page.wait_for_selector("#grid .tile")
        ids = sorted(page.eval_on_selector_all("#grid .tile[data-id]", "els => [...new Set(els.map(e => e.dataset.id))]"))
        self.assertEqual(ids, SAM_SEES)
        self.assertFalse(page.locator(".dock-add").is_visible())          # members don't add devices
        self.assertEqual(page.locator("#rail [data-add-room], [data-room-grip], [data-edit-rooms]").count(), 0)
        self.assertTrue(page.locator("#room-tools [data-room-picker]").is_visible())

        page.click("#profile-btn")                                        # switch to Owner
        page.click('[data-pm="switch"]')
        page.click('[data-pick="owner"]')
        page.fill("[data-signin-password] input[name=password]", "wrong")
        page.click("[data-signin-password] button[type=submit]")
        page.wait_for_selector("#signin-error:text('That password isn')")
        page.fill("[data-signin-password] input[name=password]", "homepanel")
        page.click("[data-signin-password] button[type=submit]")
        page.wait_for_function("document.querySelector('#profile-btn')?.textContent.trim() === 'O'")
        page.wait_for_selector('#grid .tile[data-id="lr-tv"]')

        page.click("#profile-btn")                                        # sign out: back to the picker
        page.click('[data-pm="signout"]')
        page.wait_for_selector('.avatar-choice[data-pick="owner"]')
        self.assertEqual(page.locator(".tile").count(), 0)                # the last profile's devices are gone
        self.assertEqual(self.errors, [])

    def test_email_sign_in_and_profiles_settings(self):
        page = self.open(1280, 720)
        page.click("text=Sign in with email")
        page.fill("input[name=email]", "owner@example.com")
        page.fill("input[name=password]", "homepanel")
        page.click("button[type=submit]")
        page.wait_for_selector("#profile-btn:not([hidden])")
        page.click("#profile-btn")
        page.click('[data-pm="profiles"]')
        page.wait_for_selector("[data-profile-list]")
        self.assertIn("Sam", page.inner_text("[data-profile-list]"))
        page.click('[data-go="profile"]:has-text("Add a profile")')
        page.fill("[data-profile-form] input[name=name]", "Guest")
        self.assertEqual(page.locator("[data-profile-form] input[name=pin]").count(), 0)
        page.check("[data-profile-form] input[name=access][value=some]")
        page.check('[data-profile-form] input[name=device][value="kt-pendant"]')
        page.click("[data-profile-form] button[type=submit]")
        page.wait_for_selector("text=Guest's profile is ready")
        page.wait_for_selector("[data-profile-list]:has-text('Guest')")
        self.assertIn("Member, 1 device", page.inner_text("[data-profile-list]"))
        self.assertEqual(self.errors, [])

    def test_wall_panel_has_no_lock_controls_and_keeps_profile_on_reload(self):
        page = self.open(1280, 720)
        page.click('[data-pick="owner"]')
        page.fill("[data-signin-password] input[name=password]", "homepanel")
        page.click("[data-signin-password] button[type=submit]")
        page.wait_for_selector("#profile-btn:not([hidden])")
        page.click("#profile-btn")                                        # Settings → Profiles → This screen
        page.click('[data-pm="profiles"]')
        page.check("[data-this-screen] input[name=panel]")
        self.assertEqual(page.locator("[name=lock_after_minutes]").count(), 0)
        page.click("[data-this-screen] button[type=submit]")
        page.wait_for_selector("text=Saved")
        page.keyboard.press("Escape")
        page.keyboard.press("Escape")
        page.wait_for_selector("#settings", state="hidden")
        page.click("#profile-btn")
        self.assertEqual(page.locator('[data-pm="lock"]').count(), 0)
        page.reload()
        page.wait_for_selector("#signin", state="hidden")
        page.click("#profile-btn")
        page.click('[data-pm="switch"]')
        page.click('[data-pick="sam"]')
        page.wait_for_function("document.querySelector('#profile-btn')?.textContent.trim() === 'S'")
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
