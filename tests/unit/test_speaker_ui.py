"""Capability-driven speaker markup and safe relative volume math."""
import base64
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
SOURCE = Path(__file__).resolve().parents[2] / "web/js/speaker.js"


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class SpeakerUITests(unittest.TestCase):
    def run_js(self, script):
        source = "\n".join(line for line in SOURCE.read_text().splitlines() if not line.startswith("import "))
        source = "const {store,command,esc,icon} = globalThis.fakeSpeaker;\n" + source
        module = "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()
        harness = """
          import assert from 'node:assert/strict';
          globalThis.CSS = {supports:() => false};
          globalThis.fakeSpeaker = {store:{devices:new Map()}, command:() => {},
            esc:value => String(value ?? '').replaceAll('<','&lt;').replaceAll('>','&gt;'), icon:() => '<svg></svg>'};
          const {simpleSpeaker,speakerTop,speakerBody,draggedVolume} = await import(process.argv[1]);
        """
        result = subprocess.run([NODE, "--input-type=module", "-e", harness + script, module],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_relative_volume_never_jumps_to_track_touch_and_clamps(self):
        self.run_js("""
          assert.equal(draggedVolume(8, 180, 180, 200), 8);
          assert.equal(draggedVolume(8, 180, 220, 200), 28);
          assert.equal(draggedVolume(8, 180, 0, 200), 0);
          assert.equal(draggedVolume(90, 0, 100, 200), 100);
        """)

    def test_simple_speaker_does_not_replace_tv_or_richer_media_controls(self):
        self.run_js("""
          assert.equal(simpleSpeaker({kind:'speaker',caps:['volume','sound_mode']}), true);
          assert.equal(simpleSpeaker({kind:'tv',caps:['volume']}), false);
          assert.equal(simpleSpeaker({kind:'speaker',caps:['media']}), false);
          assert.equal(simpleSpeaker({kind:'speaker',caps:['remote']}), false);
          assert.equal(simpleSpeaker({kind:'speaker',caps:['apps'],meta:{apps:[{id:'one'}]}}), false);
        """)

    def test_controls_are_labeled_and_unknown_modes_are_separated(self):
        self.run_js("""
          const d = {name:'Speaker',kind:'speaker',caps:['power','mute','volume','volume_level','inputs','sound_mode'],
            state:{on:true,online:true,volume:8,muted:false,input:'arc',sound_mode:'ai'},
            meta:{inputs:[{id:'arc',name:'HDMI ARC'}],sound_modes:[
              {id:'ai',name:'AI Sound Pro'}, {id:'26',name:'Device-reported mode 26',advanced:true}]}};
          const html = speakerBody(d);
          assert.match(html, /Power: On/);
          assert.match(html, /Turn off/);
          assert.match(html, /Mute: Off/);
          assert.match(html, /8%/);
          assert.match(html, /data-speaker-volume/);
          const basic = html.split('<details')[0];
          assert.doesNotMatch(basic, /value="26"/);
          assert.match(html, /<details class="speaker-advanced">/);
          assert.match(html, /value="26"/);
          assert.match(speakerTop({...d,name:'<script>'}), /&lt;script&gt;/);
          const off = speakerBody({...d,state:{...d.state,on:false}});
          assert.match(off, /Turn on/);
          assert.match(off, /Turn the speaker on/);
          assert.doesNotMatch(speakerBody({...d,caps:['power','volume']}), /data-speaker-volume/);
        """)
