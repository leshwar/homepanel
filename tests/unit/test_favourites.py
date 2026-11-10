"""Favourites on Home and automation wording: plain JS run in Node, no browser."""
import base64
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
WEB = Path(__file__).resolve().parents[2] / "web"


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class FavouritesAndAutomationTextTests(unittest.TestCase):
    def run_js(self, module, script):
        result = subprocess.run([NODE, "--input-type=module", "-e",
                                 "import assert from 'node:assert/strict';\n" + script, module],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_favourites_show_chosen_devices_or_the_first_usable_ones(self):
        source = "\n".join(line for line in (WEB / "js/home.js").read_text().splitlines() if not line.startswith("import "))
        module = "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()
        self.run_js(module, """
          const {favouriteDevices, MAX_FAVOURITES} = await import(process.argv[1]);
          const dev = (id, caps = ['power']) => ({id, caps});
          const all = [dev('tv'), dev('sensor', []), dev('lamp'), dev('bot', ['clean'])];
          const ids = list => list.map(d => d.id);
          // Chosen: in the order chosen, skipping one that was removed since.
          assert.deepEqual(ids(favouriteDevices({devices: ['bot', 'gone', 'tv']}, all)), ['bot', 'tv']);
          assert.deepEqual(ids(favouriteDevices({devices: ['sensor']}, all)), ['sensor']);
          // Nothing chosen (or all of them gone): the first ones with something to tap.
          assert.deepEqual(ids(favouriteDevices({devices: []}, all)), ['tv', 'lamp', 'bot']);
          assert.deepEqual(ids(favouriteDevices(undefined, all)), ['tv', 'lamp', 'bot']);
          assert.deepEqual(ids(favouriteDevices({devices: ['gone']}, all)), ['tv', 'lamp', 'bot']);
          const many = Array.from({length: 12}, (_, i) => dev('d' + i));
          assert.equal(MAX_FAVOURITES, 8);
          assert.equal(favouriteDevices({}, many).length, 8);
          assert.equal(favouriteDevices({}, many.values(), 2).length, 2);     // any iterable, e.g. a Map's values
          assert.deepEqual(favouriteDevices({}, []), []);
        """)

    def test_automation_form_values_and_wording(self):
        self.run_js((WEB / "js/automation-text.js").as_uri(), """
          const {buildWhen, whenText} = await import(process.argv[1]);
          assert.deepEqual(buildWhen({when: 'time', at: '07:00', days: ['0', '4']}), {type: 'time', at: '07:00', days: [0, 4]});
          assert.deepEqual(buildWhen({when: 'sunset', offset_min: '-15'}), {type: 'sun', event: 'sunset', offset_min: -15});
          assert.deepEqual(buildWhen({when: 'all_away'}), {type: 'presence', event: 'all_away'});
          assert.deepEqual(buildWhen({when: 'device_on', watch_id: 'tv'}), {type: 'device', device_id: 'tv', event: 'on'});
          assert.deepEqual(buildWhen({when: 'device_off', watch_id: 'tv'}), {type: 'device', device_id: 'tv', event: 'off'});
          const name = id => ({tv: 'LG TV'})[id];
          const auto = when => ({enabled: true, when, next_run: null});
          assert.equal(whenText(auto({type: 'device', device_id: 'tv', event: 'on'}), name), 'When LG TV turns on');
          assert.equal(whenText(auto({type: 'device', device_id: 'tv', event: 'off'}), name), 'When LG TV turns off');
          assert.equal(whenText(auto({type: 'device', device_id: 'gone', event: 'on'}), name), 'When a device turns on');
          assert.equal(whenText(auto({type: 'presence', event: 'all_away'})), 'When everyone leaves');
          assert.equal(whenText(auto({type: 'time', at: '07:00'})), 'No upcoming run');
          assert.match(whenText({enabled: true, when: {type: 'time'}, next_run: 1790000000}), /^Next: /);
          assert.equal(whenText({enabled: false, when: {type: 'device', device_id: 'tv', event: 'on'}}, name), 'Paused');
        """)

    def test_favourites_rows_are_compact_and_still_touch_sized(self):
        css = (WEB / "shell.css").read_text()
        self.assertIn(".w-favs .tile { min-height: 54px;", css)                 # row height; the quick button stays 48 px
        self.assertIn("flex-direction: row;", css.split(".w-favs .tile {")[1].split("}")[0])
        self.assertIn(".w-favs .tile-tv-ctl { display: none; }", css)


if __name__ == "__main__":
    unittest.main()
