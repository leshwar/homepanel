"""Weather tile scenes and animation lifecycle without a browser or network."""
import base64
import shutil
import subprocess
import unittest
from pathlib import Path

from app.core.weather import CONDITIONS

NODE = shutil.which("node")
SOURCE = Path(__file__).resolve().parents[2] / "web/js/weather-effects.js"


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class WeatherEffectsTests(unittest.TestCase):
    def run_js(self, script):
        module = "data:text/javascript;base64," + base64.b64encode(SOURCE.read_bytes()).decode()
        result = subprocess.run(
            [NODE, "--input-type=module", "-e",
             'import assert from "node:assert/strict";\n'
             'const {weatherScene, weatherBackdrop, watchWeatherEffects} = await import(process.argv[1]);\n' + script, module],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_conditions_have_bounded_scene_layers_and_day_night_sun(self):
        import json
        self.run_js("""
            for (const condition of """ + json.dumps(CONDITIONS) + """) {
                const markup = weatherBackdrop({available:true, condition, is_day:true});
                assert.ok(weatherScene({condition}));
                assert.match(markup, /aria-hidden="true"/);
                assert.match(markup, /data-active="false"/);
                assert.ok((markup.match(/<span /g) || []).length <= 3);
            }
            assert.match(weatherBackdrop({available:true, condition:'clear'}), /w-fx-sun/);
            const night = weatherBackdrop({available:true, condition:'clear', is_day:false});
            assert.match(night, /w-fx-moon/);
            assert.match(night, /w-fx-stars/);
            assert.doesNotMatch(night, /w-fx-sun/);
            for (const condition of ['rain', 'drizzle', 'storm']) {
                assert.match(weatherBackdrop({available:true, condition}), /w-fx-rain/);
            }
        """)

    def test_no_fake_scene_for_missing_unavailable_or_unknown_weather(self):
        self.run_js("""
            for (const weather of [null, {}, {available:false,condition:'rain'},
              {available:true,condition:'unknown'}, {available:true,condition:'toString'},
              {available:true,condition:'<img onerror=alert(1)>'}]) {
                assert.equal(weatherBackdrop(weather), '');
            }
        """)

    def test_offscreen_background_tabs_and_removed_tiles_stop_work(self):
        self.run_js("""
            let notify, visibilityChanged, elements = [], observed = [], unobserved = [];
            globalThis.document = {hidden:false, addEventListener(name, callback) {
                assert.equal(name, 'visibilitychange'); visibilityChanged = callback;
            }};
            globalThis.IntersectionObserver = class {
                constructor(callback) {notify = callback;}
                observe(el) {observed.push(el);}
                unobserve(el) {unobserved.push(el);}
            };
            const sync = watchWeatherEffects({querySelectorAll: () => elements});
            const tile = {dataset:{}};
            elements = [tile]; sync();
            assert.equal(tile.dataset.active, 'false');
            notify([{target:tile,isIntersecting:true}]);
            assert.equal(tile.dataset.active, 'true');
            document.hidden = true; visibilityChanged();
            assert.equal(tile.dataset.active, 'false');
            document.hidden = false; visibilityChanged();
            assert.equal(tile.dataset.active, 'true');
            notify([{target:tile,isIntersecting:false}]);
            assert.equal(tile.dataset.active, 'false');
            elements = []; sync();
            assert.deepEqual(unobserved, [tile]);
            notify([{target:tile,isIntersecting:true}]);
            assert.equal(tile.dataset.active, 'false');
            sync();
            assert.deepEqual(observed, [tile]);
        """)
