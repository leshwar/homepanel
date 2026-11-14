"""Local gallery and bounded paired-TV startup, using isolated data and fake TV clients."""
import asyncio
import io
import itertools
import os
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image

from app.adapters import lg_tv
from app.core.adapter import AdapterError, Device, Kind
from app.core.service import HomeService
from tests.helpers import DemoServer

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    if os.environ.get("REQUIRE_UI_TESTS"):
        raise
    sync_playwright = None


class LGWakeThroughService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir)
        self.adapter = lg_tv.LGTVAdapter({}, self.dir)
        self.svc.adapters = {"lg_tv": self.adapter}
        self.device = Device(id="tv", adapter="lg_tv", name="Fixture TV", kind=Kind.TV, caps=list(lg_tv.CAPS),
                             state={"online": True, "on": False}, power_on_screen="home",
                             config={"ip": "192.0.2.10", "mac": "AA:BB:CC:DD:EE:01", "client_key": "test-key"})
        self.svc.store.devices["tv"] = self.device
        self.calls = []
        self.booting, self.ready = asyncio.Event(), asyncio.Event()
        async def home(name): self.calls.append(name)
        async def set_input(value): self.calls.append(("input", value))
        async def launch_app(value): self.calls.append(("app", value))
        async def power_off(): self.calls.append("off")
        self.client = SimpleNamespace(button=home, set_input=set_input, launch_app=launch_app, power_off=power_off,
                                      disconnect=AsyncMock(), is_connected=lambda: True,
                                      get_power_state=AsyncMock(return_value={"state":"Active"}))
        self.adapter._client = AsyncMock(return_value=self.client)
        async def ready(_):
            if not self.booting.is_set():
                return None
            await self.ready.wait()
            return self.client
        self.adapter._ready = ready
        async def wake(*args): self.booting.set()
        self.patch = patch.object(lg_tv, "wake_on_lan", wake)
        self.patch.start()

    async def asyncTearDown(self):
        await self.svc.stop()
        self.patch.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_ready_wake_home_and_repeated_on_keep_current_input(self):
        task = asyncio.create_task(self.svc.command("tv", "power", True))
        await self.booting.wait()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.device.state["on"])
        self.ready.set()
        state = await task
        self.assertTrue(state["state"]["on"])
        self.assertEqual(self.calls, ["HOME"])
        await self.svc.command("tv", "power", True)
        self.assertEqual(self.calls, ["HOME"])

    async def test_new_input_app_or_power_off_supersedes_active_and_queued_wakes(self):
        for action, value, expected in (("set_input", "HDMI_2", ("input", "HDMI_2")),
                                        ("launch_app", "netflix", ("app", "netflix")), ("power", False, "off")):
            self.device.state["on"] = False
            self.booting.clear()
            self.calls.clear()
            first = asyncio.create_task(self.svc.command("tv", "power", True))
            await self.booting.wait()
            queued = asyncio.create_task(self.svc.command("tv", "power", True))
            await asyncio.sleep(0)
            await self.svc.command("tv", action, value)
            results = await asyncio.gather(first, queued, return_exceptions=True)
            self.assertTrue(all(isinstance(result, AdapterError) for result in results))
            self.assertEqual(self.calls, [expected])
            self.assertEqual(self.svc._pending_wakes, {})

    async def test_timeout_and_shutdown_leave_no_delayed_home_action(self):
        self.adapter.wake_timeout = .01
        with self.assertRaisesRegex(AdapterError, "didn't respond"):
            await self.svc.command("tv", "power", True)
        self.assertFalse(self.device.state["on"])
        self.assertEqual(self.calls, [])
        self.booting.clear()
        self.adapter.wake_timeout = 35
        task = asyncio.create_task(self.svc.command("tv", "power", True))
        await self.booting.wait()
        await self.svc.stop()
        result = await asyncio.gather(task, return_exceptions=True)
        self.assertIsInstance(result[0], AdapterError)
        self.ready.set()
        await asyncio.sleep(0)
        self.assertEqual(self.calls, [])


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class BackgroundStartupBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir, sign_in=True).start()
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
        svc = cls.server.app.state.service
        svc.store.devices["test-tv"] = Device(id="test-tv", adapter="lg_tv", name="Fixture TV", kind="tv", caps=list(lg_tv.CAPS),
                                              state={"on": False, "online": True}, config={"client_key": "not-public"})

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 720, "height": 1280}, reduced_motion="reduce")
        self.errors, self.commands, self.external = [], [], []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("request", lambda r: self.commands.append(r.url) if r.url.endswith("/command") else None)
        self.page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.server.url)
                        else (self.external.append(route.request.url), route.abort()))
        self.page.goto(self.server.url)
        self.page.request.post(self.server.url + "/api/v1/auth/sign-in", data={"profile_id": "owner", "password": "homepanel"})
        self.page.reload()
        self.page.wait_for_selector(".widget, .tile")

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.commands, [])
        self.assertEqual(self.external, [])

    def settings(self, screen, argument=None):
        self.page.wait_for_selector(".widget, .tile")
        self.page.evaluate("async ([s,a])=>(await import('/js/settings.js')).openSettings(s,a)", [screen, argument])

    def test_gallery_protection_upload_deletion_and_member_access(self):
        page = self.page
        walls = page.request.get(self.server.url + "/api/v1/wallpapers").json()["wallpapers"]
        built = [w for w in walls if w.get("builtin")]
        self.assertEqual(len(built), 5)
        for w in built:
            response = page.request.get(self.server.url + w["url"])
            self.assertEqual(response.headers["content-type"], "image/webp")
            self.assertEqual(page.request.get(self.server.url + w["thumbnail_url"]).status, 200)
            self.assertEqual(page.request.delete(self.server.url + "/api/v1/wallpapers/" + w["id"]).status, 400)
        png = io.BytesIO()
        Image.new("RGB", (20, 40), "white").save(png, "PNG")
        uploaded = page.request.post(self.server.url + "/api/v1/wallpapers", data=png.getvalue(),
                                     headers={"Content-Type": "image/png"}).json()
        self.settings("display")
        page.click("[data-browse-wallpapers]")
        self.assertEqual(page.locator('[data-builtin="true"] [data-del-wall]').count(), 0)
        self.assertEqual(page.locator('[data-included-wallpapers] [data-builtin="false"]').count(), 0)
        self.assertEqual(page.locator('[data-included-wallpapers] [data-builtin="true"]').count(), 5)
        self.assertEqual(page.locator(f'[data-del-wall="{uploaded["id"]}"]').count(), 1)
        self.assertEqual(page.request.delete(self.server.url + "/api/v1/wallpapers/" + uploaded["id"]).status, 200)
        page.request.post(self.server.url + "/api/v1/auth/sign-in", data={"profile_id": "sam"})
        self.assertEqual(page.request.get(self.server.url + built[0]["url"]).status, 200)
        self.assertEqual(page.request.delete(self.server.url + "/api/v1/wallpapers/" + built[0]["id"]).status, 403)
        self.assertEqual(page.request.put(self.server.url + "/api/v1/settings", data={"wallpaper": built[0]["id"]}).status, 403)

    def test_gallery_preview_cancel_save_shuffle_and_failed_load(self):
        page = self.page
        page.request.put(self.server.url + "/api/v1/settings", data={"background": "night", "wallpaper": "shuffle"})
        page.reload()
        self.settings("display")
        page.click("[data-browse-wallpapers]")
        self.assertEqual(page.locator("html").get_attribute("data-bg"), "night")
        page.click('.bg-choice:has(input[value="wallpaper"])')
        page.click('.wall-choice:has(input[value="builtin-alpine-dusk.webp"])')
        page.wait_for_function("document.querySelector('.wp.show')?.style.backgroundImage.includes('builtin-alpine-dusk')")
        self.assertEqual(page.request.get(self.server.url + "/api/v1/state").json()["settings"]["background"], "night")
        page.evaluate("async ()=>(await import('/js/settings.js')).closeSettings()")
        self.assertEqual(page.locator("html").get_attribute("data-bg"), "night")
        self.settings("display")
        page.click('.bg-choice:has(input[value="wallpaper"])')
        page.click('.wall-choice:has(input[value="builtin-cedar-mist.webp"])')
        page.click("[data-display] button[type=submit]")
        page.wait_for_selector("[data-go=display]")
        page.reload()
        page.wait_for_function("document.querySelector('.wp.show')?.style.backgroundImage.includes('builtin-cedar-mist')")
        saved = page.request.get(self.server.url + "/api/v1/state").json()["settings"]
        self.assertEqual(saved["wallpaper"], "builtin-cedar-mist.webp")
        picks = page.evaluate("""async () => {
          const {api}=await import('/js/api.js'), {pickWallpaper}=await import('/js/wallpaper.js');
          const all=(await api.wallpapers()).wallpapers;
          return Array.from({length:25},(_,i)=>pickWallpaper(all,{wallpaper:'shuffle',wallpaper_every:15},i*15*60000).id);
        }""")
        self.assertEqual(len(set(picks)), 5)
        page.route("**/wallpapers/builtin-desert-glow.webp/image", lambda route: route.fulfill(status=503, body="Unavailable"))
        self.settings("display")
        page.click('.wall-choice:has(input[value="builtin-desert-glow.webp"])')
        page.wait_for_selector("text=Couldn't load that wallpaper.")
        self.assertIn("builtin-cedar-mist", page.locator(".wp.show").get_attribute("style"))
        page.evaluate("async ()=>(await import('/js/settings.js')).closeSettings()")
        page.request.put(self.server.url + "/api/v1/settings", data={"background": "night", "wallpaper": "shuffle"})

    def test_gallery_fits_all_fonts_and_orientations_without_changing_background(self):
        page = self.page
        for theme, font, (w, h) in itertools.product(("dark", "light"), ("small", "medium", "large"),
                                                    ((390, 844), (720, 1280), (1280, 720))):
            page.set_viewport_size({"width": w, "height": h})
            page.evaluate("""async prefs => {
              const {store,emit}=await import('/js/store.js'); Object.assign(store.settings,prefs); emit('all');
            }""", {"tile_style": theme, "font_size": font, "background": "night"})
            self.settings("display")
            page.click("[data-browse-wallpapers]")
            page.wait_for_selector('[data-builtin="true"]')
            self.assertEqual(page.locator("html").get_attribute("data-bg"), "night")
            self.assertEqual(page.locator('[data-builtin="true"]').count(), 5)
            self.assertTrue(page.locator("#settings").evaluate("e=>e.scrollWidth<=e.clientWidth"))
            for thumb in page.locator('[data-builtin="true"] .wall-thumb').all():
                box = thumb.bounding_box()
                self.assertGreaterEqual(min(box["width"], box["height"]), 48)

    def test_slow_wallpaper_preview_cannot_overwrite_a_newer_choice(self):
        page = self.page
        page.request.put(self.server.url + "/api/v1/settings", data={"background": "night", "wallpaper": "shuffle"})
        page.reload()
        old_image = page.request.get(self.server.url + "/api/v1/wallpapers/builtin-starlit-ridge.webp/image").body()
        pending = []
        page.route("**/wallpapers/builtin-starlit-ridge.webp/image", lambda route: pending.append(route))
        self.settings("display")
        page.click('.bg-choice:has(input[value="wallpaper"])')
        with page.expect_request(lambda request: request.url.endswith("builtin-starlit-ridge.webp/image")):
            page.click('.wall-choice:has(input[value="builtin-starlit-ridge.webp"])')
        page.click('.wall-choice:has(input[value="builtin-quiet-coast.webp"])')
        page.wait_for_function("document.querySelector('.wp.show')?.style.backgroundImage.includes('builtin-quiet-coast')")
        for route in pending:
            route.fulfill(status=200, body=old_image, content_type="image/webp")
        page.wait_for_timeout(900)
        self.assertIn("builtin-quiet-coast", page.locator(".wp.show").get_attribute("style"))
        page.evaluate("async ()=>(await import('/js/settings.js')).closeSettings()")
        self.assertEqual(page.locator("html").get_attribute("data-bg"), "night")

    def test_startup_choice_is_explicit_responsive_and_saves_without_commands(self):
        page = self.page
        for theme, font, (w, h) in itertools.product(("dark", "light"), ("small", "medium", "large"),
                                                    ((390, 844), (720, 1280), (1280, 720))):
            page.set_viewport_size({"width": w, "height": h})
            page.evaluate("""async prefs => {
              const {store,emit}=await import('/js/store.js'); Object.assign(store.settings,prefs); emit('all');
            }""", {"tile_style": theme, "font_size": font})
            self.settings("device", "test-tv")
            self.assertEqual(page.locator("#d-startup").input_value(), "previous")
            self.assertEqual(page.locator("#d-startup option").all_text_contents(), ["Previous input (TV default)", "TV Home"])
            self.assertTrue(page.locator("#settings").evaluate("e=>e.scrollWidth<=e.clientWidth"))
            self.assertGreaterEqual(page.locator("#d-startup").bounding_box()["height"], 48)
        page.select_option("#d-startup", "home")
        page.click('[data-save-device="test-tv"]')
        page.wait_for_selector("text=Saved", state="visible")
        page.reload()
        self.settings("device", "test-tv")
        self.assertEqual(page.locator("#d-startup").input_value(), "home")
        state = page.request.get(self.server.url + "/api/v1/state").text()
        self.assertNotIn("not-public", state)
        page.select_option("#d-startup", "previous")
        page.click('[data-save-device="test-tv"]')
        page.wait_for_selector("text=Saved", state="visible")
