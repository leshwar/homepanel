"""The speaker panel: a volume dial, mute, and inputs and sound modes as chips. No browser."""
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
        source = "const {store,command,esc,icon,bindRelativeRange,chipChoices} = globalThis.fakeSpeaker;\n" + source
        module = "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()
        harness = """
          import assert from 'node:assert/strict';
          globalThis.fakeSpeaker = {store:{devices:new Map()}, command:() => {}, bindRelativeRange:() => {},
            esc:value => String(value ?? '').replaceAll('<','&lt;').replaceAll('>','&gt;'), icon:() => '<svg></svg>',
            chipChoices:(options, current, attr) => options.map(o => `<chip ${attr}="${o.id}" on="${String(o.id) === String(current)}">${o.name}</chip>`).join('')};
          const {simpleSpeaker,speakerPanel} = await import(process.argv[1]);
        """
        result = subprocess.run([NODE, "--input-type=module", "-e", harness + script, module],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_simple_speaker_does_not_replace_tv_or_richer_media_controls(self):
        self.run_js("""
          assert.equal(simpleSpeaker({kind:'speaker',caps:['volume','sound_mode']}), true);
          assert.equal(simpleSpeaker({kind:'tv',caps:['volume']}), false);
          assert.equal(simpleSpeaker({kind:'speaker',caps:['media']}), false);
          assert.equal(simpleSpeaker({kind:'speaker',caps:['remote']}), false);
          assert.equal(simpleSpeaker({kind:'speaker',caps:['apps'],meta:{apps:[{id:'one'}]}}), false);
        """)

    def test_dial_mute_and_choices_follow_what_the_speaker_reports(self):
        self.run_js("""
          const d = {name:'Speaker',kind:'speaker',caps:['power','mute','volume','volume_level','inputs','sound_mode'],
            state:{on:true,online:true,volume:8,muted:false,input:'arc',sound_mode:'ai'},
            meta:{playback_help:'Start music in the <app>.', inputs:[{id:'arc',name:'HDMI ARC'}],sound_modes:[
              {id:'ai',name:'AI Sound Pro'}, {id:'26',name:'Device-reported mode 26',advanced:true}]}};
          let p = speakerPanel(d);
          assert.match(p.stage, /class="dial" style="--pct:8"[^>]*aria-label="Volume 8%"/);
          assert.match(p.stage, /data-speaker-level>8</);
          assert.match(p.stage, /data-speaker-volume min="0" max="100" step="1" value="8"/);
          assert.match(p.stage, /data-act="volume_down" data-repeat/); assert.match(p.stage, /data-act="volume_up" data-repeat/);
          assert.match(p.stage, /data-mute aria-pressed="false"[\\s\\S]*>Mute</);
          assert.doesNotMatch(p.stage, /Power:|Drag to adjust|disabled/);           // power is the header switch; no printed instructions
          assert.deepEqual(p.tabs.map(t => t.id), ['input', 'sound']);
          assert.match(p.tabs[0].html, /data-input="arc" on="true"/); assert.match(p.tabs[0].html, /Start music in the &lt;app&gt;\\./);
          // Named presets first; modes the speaker lists by number are apart, with their ids.
          const [named, reported] = p.tabs[1].html.split('Reported by the speaker');
          assert.match(named, /data-sound-mode="ai" on="true"/); assert.doesNotMatch(named, /="26"/);
          assert.match(reported, /data-sound-mode="26"[^>]*>Device-reported mode 26 · ID 26</);
          // Muted, off, and missing readings.
          assert.match(speakerPanel({...d,state:{...d.state,muted:true}}).stage, /aria-pressed="true"[\\s\\S]*>Unmute<[\\s\\S]*|Muted/);
          p = speakerPanel({...d,state:{...d.state,on:false}});
          assert.match(p.stage, /speaker-stage idle/); assert.match(p.stage, /data-speaker-volume[^>]*disabled/);
          assert.match(p.stage, /Turn it on to change the volume/); assert.match(p.tabs[0].html, /<fieldset class="pane-set" disabled>/);
          p = speakerPanel({...d,state:{on:true,online:true}});
          assert.match(p.stage, /data-speaker-level>–</); assert.doesNotMatch(p.stage, /data-speaker-volume|data-mute/); assert.match(p.stage, /data-refresh/);
          assert.doesNotMatch(speakerPanel({...d,caps:['power','volume']}).stage, /data-speaker-volume/);   // buttons only: no slider
          assert.deepEqual(speakerPanel({...d,caps:['power','volume']}).tabs, []);
          assert.equal(speakerPanel({...d,caps:['power','inputs']}).stage, '');
        """)


if __name__ == "__main__":
    unittest.main()
