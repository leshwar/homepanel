"""Status wording: devices that need a person, rooms with nothing in them."""
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
WEB = Path(__file__).resolve().parents[2] / "web"


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class AttentionTests(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run([NODE, "--input-type=module", "-e",
                                 "import assert from 'node:assert/strict';\n" + script, (WEB / "js/util.js").as_uri()],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_vacuum_tile_says_when_it_needs_a_person(self):
        self.run_js("""
          const {statusText,needsAttention,wornPart} = await import(process.argv[1]);
          const bot = state => ({kind:'vacuum', caps:['clean'], state:{online:true, ...state}});
          const worn = [{id:'tray', name:'Mop washing tray', percent:0}, {id:'filter', name:'Filter', percent:60}];
          assert.equal(statusText(bot({activity:'docked', battery:100})), 'Docked, 100%');
          assert.equal(needsAttention(bot({activity:'docked', battery:100})), false);
          // A reported problem wins over everything else it could say.
          assert.equal(statusText(bot({activity:'docked', battery:100, problem:'Tank is full'})), 'Needs attention');
          assert.equal(statusText(bot({activity:'cleaning', battery:60, problem:'Stuck'})), 'Needs attention');
          // A worn part shows while it rests, but never hides cleaning or charging progress.
          assert.equal(statusText(bot({activity:'docked', battery:100, parts:worn})), 'Maintenance due');
          assert.equal(statusText(bot({activity:'idle', parts:worn})), 'Maintenance due');
          assert.equal(statusText(bot({activity:'docked', battery:40, parts:worn})), 'Charging, 40%');
          assert.equal(statusText(bot({activity:'cleaning', battery:80, parts:worn})), 'Cleaning, 80%');
          assert.equal(needsAttention(bot({activity:'cleaning', battery:80, parts:worn})), false);   // the tile only stands out when its words say why
          assert.equal(needsAttention(bot({activity:'docked', battery:100, parts:worn})), true);
          assert.equal(wornPart({parts:worn}).name, 'Mop washing tray');
          assert.equal(wornPart({parts:[{name:'Filter', percent:11}]}), null);
          // Offline and unpaired devices already have their own look.
          assert.equal(needsAttention({state:{online:false, problem:'x'}}), false);
          assert.equal(needsAttention({state:{online:true, needs_pairing:true, problem:'x'}}), false);
          assert.equal(needsAttention(undefined), false);
        """)

    def test_empty_room_is_not_reported_as_everything_off(self):
        self.run_js("""
          const {roomStatus} = await import(process.argv[1]);
          assert.equal(roomStatus(0, 0), 'No devices yet');
          assert.equal(roomStatus(3, 0), 'Everything is off');
          assert.equal(roomStatus(3, 2), '2 of 3 on');
        """)

    def test_styles_mark_attention_and_an_idle_all_off(self):
        css = (WEB / "app.css").read_text()
        self.assertIn(".tile.attn .tile-status { color: var(--lamp);", css)
        self.assertIn('html[data-tiles="light"] .tile.attn .tile-status { color: #7a4a00; }', css)
        self.assertIn(".btn-alloff.idle, .btn-alloff.idle .i { color: var(--haze); }", css)


if __name__ == "__main__":
    unittest.main()
