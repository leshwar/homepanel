"""Profiles and sign-in: hashing, rate limits, sessions, migration, who sees which
device, and the API's auth middleware. No network: the middleware is called directly."""
import asyncio
import json
import os
import shutil
import stat
import tempfile
import types
import unittest

from app.api.auth import COOKIE, AuthMiddleware
from app.core.profiles import (ADMIN, MEMBER, AuthError, ProfileError, Profiles, RateLimited, RateLimiter,
                               Sessions, Viewer, current_viewer, hash_secret, verify_secret)
from app.core.service import HomeService
from app.core.store import Store


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class HashingTests(unittest.TestCase):
    def test_round_trip_and_wrong_secret(self):
        h = hash_secret("2468")
        self.assertTrue(h.startswith("scrypt$"))
        self.assertNotIn("2468", h)
        self.assertTrue(verify_secret("2468", h))
        self.assertFalse(verify_secret("2469", h))

    def test_salted(self):
        self.assertNotEqual(hash_secret("same password"), hash_secret("same password"))

    def test_bad_stored_values_never_match(self):
        for stored in (None, "", "plain", "scrypt$1$2$3$x$y", "md5$a$b$c$d$e"):
            self.assertFalse(verify_secret("x", stored))


class RateLimitTests(unittest.TestCase):
    def test_blocks_after_too_many_failures_then_recovers(self):
        clock = FakeClock()
        rl = RateLimiter(max_failures=3, window=600, clock=clock)
        for _ in range(3):
            rl.check("ip:1")
            rl.failure("ip:1")
        with self.assertRaises(RateLimited) as e:
            rl.check("ip:1")
        self.assertIn("Wait 10 minutes", str(e.exception))
        rl.check("ip:2")                       # other keys are unaffected
        clock.t += 601
        rl.check("ip:1")                       # the window has passed

    def test_success_clears(self):
        rl = RateLimiter(max_failures=2, window=600, clock=FakeClock())
        rl.failure("profile:a")
        rl.success("profile:a")
        rl.failure("profile:a")
        rl.check("profile:a")


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "sessions.json")
        self.clock = FakeClock()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_create_get_and_saved_without_the_token(self):
        s = Sessions(self.path, clock=self.clock)
        token, sess = s.create("p1")
        self.assertEqual(s.get(token).profile_id, "p1")
        self.assertIsNone(s.get("not-a-token"))
        self.assertIsNone(s.get(None))
        with open(self.path) as f:
            text = f.read()
        self.assertNotIn(token, text)              # only a hash is stored
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        again = Sessions(self.path, clock=self.clock)   # survives a restart
        self.assertEqual(again.get(token).id, sess.id)

    def test_browser_sessions_expire_panel_sessions_last(self):
        s = Sessions(self.path, clock=self.clock)
        browser, _ = s.create("p1")
        panel, _ = s.create("p1", panel=True)
        self.clock.t += 31 * 86400
        self.assertIsNone(s.get(browser))
        self.assertIsNotNone(s.get(panel))

    def test_use_extends_a_session(self):
        s = Sessions(self.path, clock=self.clock)
        token, sess = s.create("p1")
        self.clock.t += 20 * 86400
        self.assertIsNotNone(s.get(token))         # used: another 30 days from now
        self.clock.t += 20 * 86400
        self.assertIsNotNone(s.get(token))

    def test_delete_for_profile(self):
        s = Sessions(self.path, clock=self.clock)
        a, _ = s.create("p1")
        b, _ = s.create("p2")
        s.delete_for_profile("p1")
        self.assertIsNone(s.get(a))
        self.assertIsNotNone(s.get(b))


def make_profiles(dir_):
    store = Store(os.path.join(dir_, "homepanel.json"))
    return store, Profiles(store, Sessions(os.path.join(dir_, "sessions.json")),
                           RateLimiter(max_failures=3, window=600, clock=FakeClock()))


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store, self.p = make_profiles(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_migration_creates_an_owner_and_asks_for_setup(self):
        layout = {"version": 1, "widgets": [{"id": "clock", "type": "clock", "size": "2x2", "hidden": False, "options": {}}]}
        self.assertTrue(self.p.migrate({"home_layout": layout}))
        self.assertFalse(self.p.migrate({}))                       # only once
        (owner,) = self.store.profiles
        self.assertEqual((owner["name"], owner["role"], owner["devices"]), ("Owner", ADMIN, "all"))
        self.assertEqual(owner["home_layout"], layout)              # today's Home page moves into the profile
        self.assertTrue(self.p.needs_setup)
        reloaded = Store(self.store.path)                           # saved
        self.assertEqual(reloaded.profiles[0]["id"], owner["id"])

    def test_setup_sets_a_pin_once(self):
        self.p.migrate({})
        with self.assertRaises(ProfileError):
            self.p.setup({"pin": "12"})
        self.p.setup({"pin": "1234", "name": "Asha"})
        self.assertFalse(self.p.needs_setup)
        self.assertEqual(self.store.profiles[0]["name"], "Asha")
        with self.assertRaises(ProfileError):
            self.p.setup({"pin": "9999"})

    def test_create_rules(self):
        self.p.migrate({})
        self.p.setup({"pin": "1234"})
        with self.assertRaises(ProfileError):
            self.p.create({"name": "Kid"})                          # needs a PIN or password
        with self.assertRaises(ProfileError):
            self.p.create({"name": "Kid", "pin": "12ab"})
        with self.assertRaises(ProfileError):
            self.p.create({"name": "Kid", "password": "long enough"})   # a password needs an email
        with self.assertRaises(ProfileError):
            self.p.create({"name": "Owner", "pin": "1111"})         # names are unique
        kid = self.p.create({"name": "Kid", "pin": "5555", "devices": ["b", "a", "a"]})
        self.assertEqual((kid["role"], kid["devices"]), (MEMBER, ["a", "b"]))
        with self.assertRaises(ProfileError):
            self.p.create({"name": "Kid 2", "email": "nope", "password": "long enough"})

    def test_public_never_has_hashes(self):
        self.p.migrate({})
        self.p.setup({"email": "me@example.com", "password": "correct horse"})
        for full in (True, False):
            out = json.dumps(self.p.public(self.store.profiles[0], full=full))
            self.assertNotIn("hash", out)
            self.assertNotIn("scrypt", out)
        self.assertNotIn("email", self.p.picker()[0])

    def test_last_admin_stays(self):
        self.p.migrate({})
        self.p.setup({"pin": "1234"})
        owner = self.store.profiles[0]
        with self.assertRaises(ProfileError):
            self.p.update(owner["id"], {"role": MEMBER})
        with self.assertRaises(ProfileError):
            self.p.delete(owner["id"])
        second = self.p.create({"name": "Second", "pin": "4321", "role": ADMIN})
        self.p.update(owner["id"], {"role": MEMBER})                # fine now: another admin exists
        with self.assertRaises(ProfileError):
            self.p.delete(second["id"])

    def test_sign_in_with_pin_email_and_rate_limit(self):
        self.p.migrate({})
        self.p.setup({"pin": "1234", "email": "Me@Example.com", "password": "correct horse"})
        pid = self.store.profiles[0]["id"]
        self.assertEqual(self.p.check_credentials({"profile_id": pid, "pin": "1234"}, "ip1")["id"], pid)
        self.assertEqual(self.p.check_credentials({"email": "me@example.com", "password": "correct horse"}, "ip1")["id"], pid)
        with self.assertRaises(AuthError):
            self.p.check_credentials({"email": "other@example.com", "password": "correct horse"}, "ip1")
        with self.assertRaises(AuthError):
            self.p.check_credentials({"profile_id": pid}, "ip1")
        for _ in range(3):
            with self.assertRaises(AuthError):
                self.p.check_credentials({"profile_id": pid, "pin": "0000"}, "ip2")
        with self.assertRaises(RateLimited):          # this profile is now locked for a while, from anywhere
            self.p.check_credentials({"profile_id": pid, "pin": "1234"}, "ip3")

    def test_viewer_sees(self):
        member = Viewer(profile={"id": "m", "role": MEMBER, "devices": ["a"]})
        self.assertTrue(member.sees("a"))
        self.assertFalse(member.sees("b"))
        self.assertTrue(Viewer(profile={"id": "m", "role": MEMBER, "devices": "all"}).sees("b"))
        self.assertTrue(Viewer(profile={"id": "x", "role": ADMIN, "devices": ["a"]}).sees("b"))


class AccessFilterTests(unittest.IsolatedAsyncioTestCase):
    """The service hides devices from members: snapshot, commands, all-off, scenes, events, layouts."""

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()
        self.sam = Viewer(profile=self.svc.profiles.get("sam"))
        self.token = current_viewer.set(self.sam)

    async def asyncTearDown(self):
        current_viewer.reset(self.token)
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_snapshot_only_has_visible_devices(self):
        snap = self.svc.snapshot()
        self.assertEqual(sorted(d["id"] for d in snap["devices"]), ["bd-fan", "bd-lamp", "bd-tv", "kt-pendant"])
        self.assertEqual(snap["scenes"], [])                 # every demo scene has a living-room device
        self.assertEqual((snap["adapters"], snap["automations"], snap["profiles"]), ([], [], []))
        self.assertNotIn("presence", snap["settings"])
        self.assertEqual(snap["me"]["name"], "Sam")
        widgets = snap["settings"]["home_layout"]["widgets"]
        shown = {w["options"]["device_id"] for w in widgets if w["type"] == "device"}
        self.assertTrue(shown <= {"bd-fan", "bd-lamp", "bd-tv", "kt-pendant"})

    async def test_hidden_device_commands_look_missing(self):
        with self.assertRaises(KeyError):
            await self.svc.command("lr-lamp", "toggle")
        await self.svc.command("bd-lamp", "power", True)
        with self.assertRaises(KeyError):
            await self.svc.run_scene("movie")

    async def test_all_off_only_touches_visible_devices(self):
        current_viewer.set(None)                            # the panel itself turns two lamps on
        await self.svc.command("lr-lamp", "power", True)
        await self.svc.command("bd-lamp", "power", True)
        current_viewer.set(self.sam)
        await self.svc.all_off()
        self.assertTrue(self.svc.get("lr-lamp").state["on"])
        self.assertFalse(self.svc.get("bd-lamp").state["on"])

    async def test_events_are_filtered_per_viewer(self):
        dev = lambda i: {"type": "device", "device": {"id": i}}   # noqa: E731
        self.assertTrue(self.svc.event_visible(self.sam, dev("bd-tv")))
        self.assertFalse(self.svc.event_visible(self.sam, dev("lr-tv")))
        self.assertFalse(self.svc.event_visible(self.sam, {"type": "automation", "name": "x"}))
        self.assertTrue(self.svc.event_visible(self.sam, {"type": "layout"}))
        seen = []
        q = self.svc.subscribe(lambda ev: self.svc.event_visible(self.sam, ev))
        self.svc.publish(dev("lr-tv"))
        self.svc.publish(dev("bd-tv"))
        while not q.empty():
            seen.append(q.get_nowait()["device"]["id"])
        self.assertEqual(seen, ["bd-tv"])

    async def test_layouts_are_per_profile(self):
        mine = {"widgets": [{"id": "clock", "type": "clock", "size": "1x1"},
                            {"id": "dev-lr-tv", "type": "device", "size": "1x1", "options": {"device_id": "lr-tv"}}]}
        saved = self.svc.save_my_layout(mine)["home_layout"]
        self.assertEqual([w["id"] for w in saved["widgets"]], ["clock"])   # a hidden device's widget is left out
        self.assertEqual(self.svc.profiles.get("sam")["home_layout"]["widgets"][0]["size"], "1x1")
        current_viewer.set(Viewer(profile=self.svc.profiles.get("owner")))
        self.assertEqual(self.svc.settings()["home_layout"]["widgets"][0]["size"], "2x2")   # Owner keeps the default

    async def test_removing_a_device_removes_it_from_profiles(self):
        current_viewer.set(None)
        await self.svc.remove_device("bd-fan")
        self.assertNotIn("bd-fan", self.svc.profiles.get("sam")["devices"])

    async def test_settings_lock_after(self):
        current_viewer.set(None)
        self.assertEqual(self.svc.update_settings({"lock_after_minutes": "999"})["lock_after_minutes"], 240)


# ---------------------------------------------------------------------------
# The auth middleware, called like the server would
# ---------------------------------------------------------------------------

class MiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store, self.p = make_profiles(self.dir)
        self.p.migrate({})
        self.p.setup({"pin": "1234"})
        self.member = self.p.create({"name": "Kid", "pin": "5555", "devices": ["bd-lamp"]})
        self.service = types.SimpleNamespace(profiles=self.p)
        self.seen = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    async def _app(self, scope, receive, send):
        self.seen.append(current_viewer.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    def call(self, method, path, token=None, sign_in=True):
        headers = [(b"cookie", f"{COOKIE}={token}".encode())] if token else []
        scope = {"type": "http", "method": method, "path": path, "headers": headers, "client": ("10.0.0.5", 1),
                 "app": types.SimpleNamespace(state=types.SimpleNamespace(service=self.service))}
        out = {}

        async def send(msg):
            if msg["type"] == "http.response.start":
                out["status"] = msg["status"]
            else:
                out["body"] = json.loads(msg.get("body") or b"null")

        async def receive():
            return {"type": "http.request"}

        asyncio.run(AuthMiddleware(self._app, sign_in=sign_in)(scope, receive, send))
        return out["status"], out["body"]

    def token_for(self, profile_id, **kw):
        token, s = self.p.sessions.create(profile_id, **kw)
        return token, s

    def test_no_session_only_sign_in_and_health(self):
        self.assertEqual(self.call("GET", "/api/v1/state")[0], 401)
        self.assertEqual(self.call("GET", "/api/v1/events")[0], 401)
        self.assertTrue(self.call("POST", "/api/v1/devices/x/command")[1]["signin"])
        for path in ("/api/v1/health", "/api/v1/auth/session", "/api/v1/auth/sign-in"):
            self.assertEqual(self.call("GET" if "session" in path or "health" in path else "POST", path)[0], 200)
        self.assertEqual(self.call("GET", "/index.html")[0], 200)        # the UI's files are public

    def test_setup_flag_before_anyone_has_a_pin(self):
        store, p = make_profiles(tempfile.mkdtemp(dir=self.dir))
        p.migrate({})
        self.service = types.SimpleNamespace(profiles=p)
        status, body = self.call("GET", "/api/v1/state")
        self.assertEqual((status, body["setup"]), (401, True))

    def test_member_rules(self):
        token, _ = self.token_for(self.member["id"])
        self.assertEqual(self.call("GET", "/api/v1/state", token)[0], 200)
        self.assertEqual(self.seen[-1].id, self.member["id"])
        self.assertEqual(self.call("POST", "/api/v1/devices/bd-lamp/command", token)[0], 200)
        self.assertEqual(self.call("POST", "/api/v1/devices/lr-tv/command", token)[0], 404)   # hidden: "not found"
        self.assertEqual(self.call("GET", "/api/v1/devices/lr-tv/energy", token)[0], 404)
        for method, path in (("PUT", "/api/v1/settings"), ("POST", "/api/v1/devices"), ("GET", "/api/v1/logs"),
                             ("GET", "/api/v1/profiles"), ("PATCH", "/api/v1/profiles/x"), ("PUT", "/api/v1/rooms"),
                             ("POST", "/api/v1/auth/panel"), ("GET", "/api/v1/automations")):
            self.assertEqual(self.call(method, path, token)[0], 403, path)
        self.assertEqual(self.call("PUT", "/api/v1/profiles/me/layout", token)[0], 200)

    def test_admin_can_do_everything(self):
        token, _ = self.token_for(self.store.profiles[0]["id"])
        for method, path in (("PUT", "/api/v1/settings"), ("GET", "/api/v1/profiles"), ("POST", "/api/v1/devices/lr-tv/command")):
            self.assertEqual(self.call(method, path, token)[0], 200)

    def test_locked_panel_keeps_only_the_clock_and_photos(self):
        token, s = self.token_for(self.store.profiles[0]["id"], panel=True)
        self.p.sessions.update(s, locked=True)
        status, body = self.call("GET", "/api/v1/state", token)
        self.assertEqual((status, body["locked"]), (401, True))
        for path in ("/api/v1/weather", "/api/v1/photos", "/api/v1/photos/abc/image"):
            self.assertEqual(self.call("GET", path, token)[0], 200, path)

    def test_demo_without_sign_in_acts_as_the_owner(self):
        self.assertEqual(self.call("GET", "/api/v1/state", sign_in=False)[0], 200)
        self.assertTrue(self.seen[-1].auto and self.seen[-1].is_admin)
        token, _ = self.token_for(self.member["id"])                 # signing in still switches profile
        self.assertEqual(self.call("POST", "/api/v1/devices/lr-tv/command", token, sign_in=False)[0], 404)

    def test_deleted_profile_signs_out(self):
        token, _ = self.token_for(self.member["id"])
        self.p.delete(self.member["id"])
        self.assertEqual(self.call("GET", "/api/v1/state", token)[0], 401)


if __name__ == "__main__":
    unittest.main()
