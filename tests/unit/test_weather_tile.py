"""The Home page's weather tile: what it says about now and the coming hours.

Plain JS run in Node with tiny stand-ins for the modules it imports: no browser, no internet.
"""
import base64
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
SOURCE = Path(__file__).resolve().parents[2] / "web" / "js" / "weather-tile.js"

STUBS = r"""
const esc = s => String(s ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const weatherIcon = (condition, isDay) => `<svg data-wx="${condition}" data-day="${isDay}"></svg>`;
const weatherBackdrop = wx => `<fx data-scene="${wx.condition}"></fx>`;
"""

SETUP = r"""
import assert from 'node:assert/strict';
const count = (html, re) => (html.match(re) || []).length;
const {hourLabel, outlook, feelsLike, curve, weatherTile} = await import(process.argv[1]);
// Twelve coming hours from 9 PM: `wet` hours rain (80%), the rest are dry with `chance`% of rain.
const hours = ({wet = [], chance = 5, n = 12, kind = 'rain', label = 'Rain'} = {}) => Array.from({length: n}, (_, i) => ({
  at: 2e9 + i * 3600, hour: (21 + i) % 24, temperature: 70 - i, rain: wet.includes(i) ? 80 : chance,
  condition: wet.includes(i) ? kind : 'cloudy', label: wet.includes(i) ? label : 'Cloudy', is_day: false}));
const now = (extra = {}) => ({available: true, temperature: 72, feels_like: 72, high: 76, low: 61, unit: 'F',
  condition: 'clear', label: 'Clear', is_day: true, hours: hours(), ...extra});
"""


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class WeatherTileTests(unittest.TestCase):
    def run_js(self, script):
        source = "\n".join(line for line in SOURCE.read_text().splitlines() if not line.startswith("import "))
        module = "data:text/javascript;base64," + base64.b64encode((STUBS + source).encode()).decode()
        result = subprocess.run([NODE, "--input-type=module", "-e", SETUP + script, module],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_hours_are_named_the_way_the_clock_is_set(self):
        self.run_js(r"""
          assert.deepEqual([0, 1, 11, 12, 13, 23].map(h => hourLabel(h)), ['12 AM', '1 AM', '11 AM', '12 PM', '1 PM', '11 PM']);
          assert.deepEqual([0, 9, 21].map(h => hourLabel(h, true)), ['00:00', '09:00', '21:00']);
        """)

    def test_one_plain_sentence_about_rain(self):
        self.run_js(r"""
          assert.equal(outlook(now({hours: hours({wet: [2, 3]})})), 'Rain around 11 PM');             // dry now, rain coming
          assert.equal(outlook(now({hours: hours({wet: [2]})}), true), 'Rain around 23:00');
          assert.equal(outlook(now({hours: hours({wet: [5], kind: 'snow', label: 'Snow'})})), 'Snow around 2 AM');
          assert.equal(outlook(now({hours: hours({wet: [0], kind: 'storm'})})), 'Thunderstorms around 9 PM');
          assert.equal(outlook(now({condition: 'rain', hours: hours({wet: [0, 1]})})), 'Rain until about 11 PM');   // raining now: when it stops
          assert.equal(outlook(now({condition: 'drizzle', hours: hours({wet: [0,1,2,3,4,5,6,7,8,9,10,11]})})), 'Rain for the next 12 hours');
          assert.equal(outlook(now({condition: 'snow', hours: hours()})), 'Snow until about 9 PM');
          // No rain forecast, but a real chance: say the chance. A small one: say nothing.
          const maybe = hours(); maybe[4].rain = 55;
          assert.equal(outlook(now({hours: maybe})), '55% chance of rain around 1 AM');
          assert.equal(outlook(now({hours: hours({chance: 30})})), '');
          // "Dry" is only said when every one of the 12 hours says so.
          assert.equal(outlook(now()), 'Dry for the next 12 hours');
          assert.equal(outlook(now({hours: hours({n: 6})})), '');
          const unknown = hours(); unknown[3].rain = null;
          assert.equal(outlook(now({hours: unknown})), '');
          for (const nothing of [now({hours: []}), now({hours: undefined}), null, {}]) assert.equal(outlook(nothing), '');
        """)

    def test_feels_like_only_when_it_differs(self):
        self.run_js(r"""
          assert.equal(feelsLike({temperature: 72, feels_like: 68}), 68);
          assert.equal(feelsLike({temperature: 30, feels_like: 33}), 33);
          for (const same of [{temperature: 72, feels_like: 70}, {temperature: 72, feels_like: 72}, {temperature: 72, feels_like: null},
            {temperature: 72}, {}, null]) assert.equal(feelsLike(same), null);
        """)

    def test_the_line_passes_through_every_hour(self):
        self.run_js(r"""
          const c = curve(72, hours(), 240, 42);
          assert.equal(c.pts.length, 13);                                    // now, then one point per hour
          assert.deepEqual(c.pts[0], [0, c.pts[0][1]]);                      // starts at the left edge
          assert.equal(c.pts[1][0], 10); assert.equal(c.pts[12][0], 230);    // each hour in the middle of its slot
          assert.equal(c.pts[2][0], 30); assert.equal(c.pts[5][0], 90);      // so the hours spelled out below sit at 1/8, 3/8, 5/8, 7/8
          for (let i = 1; i < c.pts.length; i++) assert.ok(c.pts[i][1] > c.pts[i - 1][1]);    // cooling: the line goes down
          for (const [, y] of c.pts) assert.ok(y >= 5 && y <= 37, y);        // inside the box
          assert.match(c.d, /^M0 [\d.]+( C[\d. -]+){12}$/);
          // A degree or two of change is a gentle slope, not a cliff.
          const flat = curve(70, hours().map((h, i) => ({...h, temperature: 70 + (i % 2)})), 240, 42);
          const ys = flat.pts.map(p => p[1]);
          assert.ok(Math.max(...ys) - Math.min(...ys) < 8, ys);
          const level = curve(70, hours().map(h => ({...h, temperature: 70})), 240, 42);
          assert.ok(level.pts.every(p => p[1] === 21));                      // no change: straight across the middle
        """)

    def test_tile_markup(self):
        self.run_js(r"""
          const tile = weatherTile(now({feels_like: 66, hours: hours({wet: [2, 3]})}), {place: 'Home <1>'});
          assert.match(tile, /class="w-fill w-weather has-hours" data-weather-status="ready"><fx data-scene="clear">/);
          assert.match(tile, /<span class="w-label widget-heading">Home &lt;1><\/span>/);
          assert.match(tile, /<div class="wx-now"><span class="w-wx"><b>72°<\/b><\/span>\s*<div class="wx-facts"><span class="w-sub">/);   // now is one row
          assert.match(tile, /<span class="w-sub"><svg data-wx="clear" data-day="true"><\/svg><span>Clear<\/span><\/span>\s*<span class="wx-feels">Feels like 66°<\/span>/);   // its own line
          assert.match(tile, /<span class="wx-range">H 76° L 61°<\/span>/);
          assert.match(tile, /<span class="wx-outlook">Rain around 11 PM<\/span>/);
          // Four hours spelled out: 2, 5, 8 and 11 hours from now.
          assert.equal(count(tile, /class="wx-hour"/g), 4);
          assert.deepEqual([...tile.matchAll(/<small>([^<]+)<\/small>/g)].map(m => m[1]), ['10 PM', '1 AM', '4 AM', '7 AM']);
          assert.deepEqual([...tile.matchAll(/<b>(\d+)°<\/b><svg/g)].map(m => m[1]), ['69', '66', '63', '60']);
          assert.match(tile, /aria-label="10 PM: 69 degrees, cloudy, 5% chance of rain"/);
          assert.equal(count(tile, /<rect /g), 2);                           // the chance of rain: only hours with 10% or more
          assert.equal(count(tile, /<i style="left:(12\.50|37\.50|62\.50|87\.50)%/g), 4);   // a dot on the line above each of the four
          assert.match(tile, /<path class="wx-line" d="M0 /);
          // Without the coming hours (or with too few) it is the plain tile at every size.
          for (const few of [now({hours: []}), now({hours: hours({n: 11})}), now({hours: undefined})]) {
            const plain = weatherTile(few, {});
            assert.doesNotMatch(plain, /has-hours|wx-chart|wx-hours|wx-outlook/);
            assert.match(plain, /<span class="w-label widget-heading">Weather<\/span>/); assert.match(plain, /<b>72°<\/b>/); assert.match(plain, />Clear</);
          }
          assert.doesNotMatch(weatherTile(now({high: null, low: null})), /wx-range/);
          assert.doesNotMatch(weatherTile(now()), /wx-feels/);                // same as the temperature: not said
          assert.match(weatherTile(now(), {h24: true}), /<small>22:00<\/small>/);
        """)


if __name__ == "__main__":
    unittest.main()
