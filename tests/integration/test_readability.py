"""Wallpaper readability at the extremes, using generated pictures, never user data."""
import io
import itertools
import os
import shutil
import tempfile
import unittest

from PIL import Image, ImageDraw

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    if os.environ.get("REQUIRE_UI_TESTS"):
        raise
    sync_playwright = None

from tests.helpers import DemoServer


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class ReadabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir).start()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:
            cls.pw.stop()
            cls.server.stop()
            shutil.rmtree(cls.dir, ignore_errors=True)
            if os.environ.get("REQUIRE_UI_TESTS"):
                raise
            raise unittest.SkipTest(f"chromium not available: {e}")
        cls.walls = {}
        request = cls.pw.request.new_context(base_url=cls.server.url)
        try:
            for tone, base, accent in [("light", "#ffffff", "#e8ecf8"), ("dark", "#000000", "#182448")]:
                img = Image.new("RGB", (640, 480), base)
                draw = ImageDraw.Draw(img)
                for x, y in itertools.product(range(0, 640, 80), range(0, 480, 80)):
                    draw.rectangle((x, y, x + 39, y + 39), fill=accent)
                out = io.BytesIO()
                img.save(out, "PNG")
                response = request.post("/api/v1/wallpapers?name=test.png", data=out.getvalue(),
                                        headers={"Content-Type": "image/png"})
                assert response.ok
                cls.walls[tone] = response.json()["id"]
        finally:
            request.dispose()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.errors = []
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 720}, reduced_motion="reduce")
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.add_init_script("localStorage.setItem('view', JSON.stringify('rooms'))")
        self.page.goto(self.server.url)
        self.page.wait_for_selector('.tile')

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def settings(self, **values):
        response = self.page.request.put(self.server.url + "/api/v1/settings", data=values)
        self.assertTrue(response.ok, response.text())
        self.page.evaluate("async () => {const {reload} = await import('/js/store.js'); await reload();}")

    def surface(self, selector):
        """Compute a base-surface contrast bound against black and white wallpapers.

        Includes nested button backgrounds and text opacity. Gradients/pictures
        aren't used to make a weak base color pass; they remain decorative.
        """
        return self.page.locator(selector).first.evaluate("""e => {
            const rgba = value => value.match(/[\\d.]+/g).map(Number);
            const blend = (fg, bg, opacity = 1) => fg.slice(0, 3).map((v, i) => {
                const alpha = (fg[3] ?? 1) * opacity;
                return v * alpha + bg[i] * (1 - alpha);
            });
            const luma = rgb => rgb.map(v => v / 255).map(v =>
                v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
                .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
            const root = e.closest('.tile, .widget, .rail, .topbar-clock, .btn-alloff, .room-off');
            const layers = [];
            let node = e, opacity = 1;
            while (node) {
                const style = getComputedStyle(node);
                layers.unshift(rgba(style.backgroundColor));
                opacity *= Number(style.opacity);
                if (node === root) break;
                node = node.parentElement;
            }
            const text = rgba(getComputedStyle(e).color);
            const contrast = [0, 255].map(extreme => {
                let bg = [extreme, extreme, extreme];
                for (const layer of layers) bg = blend(layer, bg);
                const values = [luma(blend(text, bg, opacity)), luma(bg)].sort((a, b) => a - b);
                return (values[1] + .05) / (values[0] + .05);
            });
            const backing = rgba(getComputedStyle(root).backgroundColor);
            return {alpha: backing[3] ?? 1, opacity: Number(getComputedStyle(root).opacity),
                    contrast: Math.min(...contrast)};
        }""")

    def test_tiles_widgets_and_rail_stay_readable_at_transparency_extremes(self):
        page = self.page
        for tone in ("light", "dark"):
            wid = self.walls[tone]
            self.settings(background="wallpaper", wallpaper=wid, wallpaper_dim=0, tile_style="auto")
            page.wait_for_function("tone => document.documentElement.dataset.tone === tone", arg=tone)
            page.wait_for_function("id => document.querySelector('.wp.show').style.backgroundImage.includes(id)", arg=wid)
            for style, transparency, blur, size in itertools.product(
                    ("auto", "light", "dark"), (0, 100), (False, True), ((393, 852), (1280, 720))):
                with self.subTest(tone=tone, style=style, transparency=transparency, blur=blur, size=size):
                    page.set_viewport_size({"width": size[0], "height": size[1]})
                    self.settings(tile_style=style, glass_transparency=transparency, glass_effect=blur)
                    expected = style if style != "auto" else "dark" if tone == "light" else "light"
                    page.wait_for_function("s => document.documentElement.dataset.tiles === s", arg=expected)
                    page.evaluate("""async () => {
                        const {store, setView, upsertDevice} = await import('/js/store.js');
                        setView('rooms');
                        const d = structuredClone(store.devices.get('kt-kettle'));
                        d.state.online = false;
                        upsertDevice(d);
                    }""")
                    for selector in ('.tile[data-id="lr-tv"] .tile-name', '.tile[data-id="lr-tv"] .tile-status',
                                     '.tile[data-id="kt-kettle"] .tile-name', '.tile[data-id="kt-kettle"] .tile-status',
                                     '#clock-time', '.room-off'):
                        state = self.surface(selector)
                        self.assertGreaterEqual(state["contrast"], 4.5, (selector, state))
                        self.assertEqual(state["opacity"], 1, selector)
                        self.assertGreaterEqual(state["alpha"], .72 if expected == "light" else .8, selector)
                    if size[0] >= 768:
                        for selector in ('#rail .rail-head', '#rail .rail-label'):
                            self.assertGreaterEqual(self.surface(selector)["contrast"], 4.5, selector)
                    page.evaluate("async () => (await import('/js/store.js')).setView('home')")
                    for selector in ('.w-zone .w-label', '.w-zone .w-sub', '.w-room > span',
                                     '.w-scenes .scene.add', '.w-weather.off .btn'):
                        state = self.surface(selector)
                        self.assertGreaterEqual(state["contrast"], 4.5, (selector, state))
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), size[0])

    def test_display_preview_keeps_guardrails_and_does_not_save_until_submitted(self):
        page = self.page
        self.settings(background="wallpaper", wallpaper=self.walls["light"], wallpaper_dim=0,
                      tile_style="dark", glass_transparency=100, glass_effect=False)
        page.wait_for_function("document.documentElement.dataset.tone === 'light'")
        page.click('#rail [data-open-settings]')
        page.click('[data-go="display"]')
        page.click('.seg-choice:has(input[value="light"])')
        page.wait_for_function("document.documentElement.dataset.tiles === 'light'")
        self.assertGreaterEqual(self.surface('.tile .tile-name')["alpha"], .72)
        # Preview changes the surface, not the saved setting.
        saved = page.request.get(self.server.url + '/api/v1/state').json()['settings']
        self.assertEqual(saved['tile_style'], 'dark')
        page.evaluate("async () => (await import('/js/settings.js')).closeSettings()")
        page.wait_for_function("document.documentElement.dataset.tiles === 'dark'")
        self.assertGreaterEqual(self.surface('.tile .tile-name')["alpha"], .8)
