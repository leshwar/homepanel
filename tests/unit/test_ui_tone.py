"""Adaptive tile logic without a browser; Node supplies fake DOM and store objects."""
import base64
import json
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
WEB = Path(__file__).resolve().parents[2] / "web/js"


def module_url(source):
    return "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class ToneTests(unittest.TestCase):
    def run_js(self, script):
        store = module_url('export const store = {settings: {}};')
        tone = module_url((WEB / "tone.js").read_text().replace('"./store.js"', json.dumps(store)))
        glass = module_url((WEB / "glass.js").read_text())
        result = subprocess.run(
            [NODE, "--input-type=module", "-e",
             'import assert from "node:assert/strict";\n'
             'globalThis.document = {documentElement: {dataset: {}, style: {\n'
             '  setProperty(key, value) {this[key] = value;}\n'
             '}}};\n'
             'const {store} = await import(process.argv[1]);\n'
             'const tone = await import(process.argv[2]);\n'
             'const {applyTransparency} = await import(process.argv[3]);\n' + script, store, tone, glass],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_auto_manual_and_dimming_keep_tile_and_heading_tones_separate(self):
        self.run_js("""
            store.settings = {background: 'wallpaper', tile_style: 'auto', wallpaper_dim: 0};
            tone.setWallpaperLuma({all: .9, top: .1});
            assert.equal(tone.tilesFor(), 'dark');
            assert.equal(document.documentElement.dataset.tone, 'dark');
            tone.setWallpaperLuma({all: .1, top: .9});
            assert.equal(tone.tilesFor(), 'light');
            assert.equal(document.documentElement.dataset.tone, 'light');
            tone.setWallpaperLuma({all: 1, top: 1});
            for (const style of ['light', 'dark']) {
                store.settings.tile_style = style;
                assert.equal(tone.tilesFor(), style);
            }
            store.settings.tile_style = 'auto';
            store.settings.wallpaper_dim = 80;
            assert.equal(tone.tilesFor(), 'light');
            tone.applyTiles();
            assert.equal(document.documentElement.dataset.tone, 'dark');
            for (const bg of ['sky', 'ocean', 'aurora', 'night']) {
                assert.equal(tone.tilesFor({background: bg}), 'light');
            }
        """)

    def test_preview_can_be_cancelled_and_missing_luma_falls_back_safely(self):
        self.run_js("""
            store.settings = {background: 'wallpaper', tile_style: 'auto', wallpaper_dim: 0};
            tone.setWallpaperLuma({all: 1, top: 1});
            tone.previewTiles({wallpaper_dim: 80, tile_style: 'light'});
            assert.deepEqual(document.documentElement.dataset, {tiles: 'light', tone: 'dark'});
            assert.equal(store.settings.wallpaper_dim, 0);
            tone.previewTiles(null);
            assert.deepEqual(document.documentElement.dataset, {tiles: 'dark', tone: 'light'});
            tone.setWallpaperLuma(null);
            assert.deepEqual(document.documentElement.dataset, {tiles: 'light', tone: 'dark'});
            document.createElement = () => {throw new Error('canvas unavailable');};
            assert.equal(tone.measureLuma({}), null);
        """)

    def test_transparency_extremes_are_clamped_without_changing_the_tile_choice(self):
        self.run_js("""
            store.settings = {background: 'wallpaper', tile_style: 'dark'};
            tone.setWallpaperLuma({all: 1, top: 1});
            for (const [input, expected] of [[-10, '.920'], [0, '.920'], [100, '.070'], [200, '.070']]) {
                applyTransparency(input);
                assert.equal(Number(document.documentElement.style['--glass-alpha']), Number(expected));
                assert.equal(tone.tilesFor(), 'dark');
            }
        """)
