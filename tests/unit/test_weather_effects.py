"""Weather tile scenes and animation lifecycle without a browser or network."""
import base64
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from app.core.weather import CONDITIONS

NODE = shutil.which("node")
SOURCE = Path(__file__).resolve().parents[2] / "web/js/weather-effects.js"


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class WeatherEffectsTests(unittest.TestCase):
    def test_night_clouds_have_distinct_artwork_and_visible_continuous_drift(self):
        css = (SOURCE.parents[1] / "shell.css").read_text()
        rule = re.search(r'\.w-weather-fx\[data-weather-period="night"\] \.w-fx-clouds \{([^}]+)\}', css).group(1)
        self.assertIn("opacity: .85", rule)
        self.assertIn("animation-duration: 28s", rule)
        self.assertIn("background-image:", rule)
        self.assertIn("stdDeviation='4'", rule)
        self.assertIn("prefers-reduced-motion: reduce", css)

    def test_existing_scene_keeps_moving_during_refresh_and_stale_replies_are_ignored(self):
        source = SOURCE.with_name("sky.js").read_text()
        source = "\n".join(line for line in source.splitlines() if not line.startswith("import "))
        source = "const {api, store, applyTiles, weatherScene} = globalThis.fakeSky;\n" + source
        module = "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()
        script = """
            import assert from 'node:assert/strict';
            const pending = [], settings = {weather_enabled:true, latitude:0, longitude:0, temperature_unit:'F'};
            globalThis.document = {documentElement:{dataset:{}}};
            globalThis.fakeSky = {store:{settings}, applyTiles:() => {}, weatherScene:w => w?.condition,
              api:{weather:() => new Promise((resolve,reject) => pending.push({resolve,reject}))}};
            const sky = await import(process.argv[1]);
            let changes = 0;
            sky.onWeather(() => changes++);
            const settle = () => new Promise(resolve => setImmediate(resolve));
            sky.refreshWeather();
            assert.equal(sky.weatherStatus(), 'loading');
            pending.shift().resolve({available:true,condition:'clear'});
            await settle();
            assert.equal(sky.weatherStatus(), 'ready');
            assert.equal(changes, 2);
            sky.refreshWeather(true);
            assert.equal(sky.weatherStatus(), 'updating');
            assert.equal(changes, 2); // no teardown/loading flash for a known scene
            pending.shift().resolve({available:true,condition:'rain'});
            await settle();
            assert.equal(sky.currentWeather().condition, 'rain');
            sky.refreshWeather(true);
            pending.shift().reject(new Error('offline'));
            await settle();
            assert.equal(sky.weatherStatus(), 'unavailable');
            assert.equal(sky.currentWeather().condition, 'rain'); // page sky retains its last reading
            sky.refreshWeather(true);
            settings.weather_enabled = false;
            sky.refreshWeather();
            pending.shift().resolve({available:true,condition:'snow'});
            await settle();
            assert.equal(sky.weatherStatus(), 'off');
            assert.equal(sky.currentWeather(), null);
        """
        result = subprocess.run([NODE, "--input-type=module", "-e", script, module],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
