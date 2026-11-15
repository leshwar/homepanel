"""Compact-card semantics and permission-filtered notification contents."""
import base64
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from app.core.profiles import ProfileError
from app.core.service import HomeService

WEB = Path(__file__).resolve().parents[2] / "web/js"


@unittest.skipUnless(shutil.which("node"), "Node.js is required")
class OverviewLogicTests(unittest.TestCase):
    def run_js(self, filename, stubs, script):
        source = "\n".join(line for line in (WEB / filename).read_text().splitlines() if not line.startswith("import "))
        util = (WEB / "util.js").read_text()
        util = util[:util.index("let toastTimer")]  # pure status helpers; no DOM lifecycle
        vacuum = (WEB / "vacuum-status.js").read_text()
        prefix = util + "\n" + vacuum + "\n" + stubs
        url = "data:text/javascript;base64," + base64.b64encode((prefix + source).encode()).decode()
        result = subprocess.run(["node","--input-type=module","-e",
                                 "import assert from 'node:assert/strict'; const m=await import(process.argv[1]);\n"+script, url],
                                capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_attention_is_prioritized_deduplicated_and_clears_with_visible_set(self):
        self.run_js("notifications.js","const store={settings:{}};", """
          const d=(id,state,caps=[])=>({id,name:id,kind:'vacuum',caps,state});
          const problem=d('tank',{online:true,activity:'docked',problem:'Empty tank'});
          const offline=d('offline',{online:false,problem:'Old problem'});
          const pair=d('pair',{online:true,needs_pairing:true});
          const worn=d('filter',{online:true,activity:'docked',parts:[{name:'Filter',percent:5}]});
          const items=m.attentionItems([offline,problem,pair,worn,problem]);
          assert.deepEqual(items.map(i=>i.id),['tank','pair','offline','filter']);
          assert.equal(items[2].text,'Offline · Check connection');
          assert.equal(m.attentionItems([d('ok',{online:true,activity:'docked',battery:100})]).length,0);
          assert.deepEqual(m.attentionItems([]),[]);
        """)

    def test_cards_show_only_supported_safe_controls_and_real_status(self):
        self.run_js("room-cards.js","const store={busy:new Set()};", """
          const d={id:'light',name:'Lamp',kind:'light',caps:['power','brightness'],state:{online:true,on:true,brightness:45}};
          assert.match(m.compactBody(d,null,'',false),/data-card-range="brightness"/);
          assert.doesNotMatch(m.compactBody({...d,caps:['power']},null,'',false),/data-card-range/);
          assert.match(m.compactBody({...d,state:{online:true}},null,'',false),/Not reported/);
          assert.match(m.compactBody({...d,state:{online:false}},null,'',false),/disabled/);
          const vacuum={id:'v',name:'Bot',kind:'vacuum',caps:['clean'],state:{online:true,activity:'docked',battery:100,problem:'Tank full'}};
          const quick={action:'clean',value:'start',label:'Start cleaning',glyph:'play'};
          const html=m.compactBody(vacuum,quick,'',false);
          assert.match(html,/Tank full/); assert.doesNotMatch(html,/data-quick-action|100% complete/);
          const running=m.compactBody({...vacuum,state:{online:true,activity:'cleaning',battery:65}},null,'',false);
          assert.match(running,/Battery 65%/); assert.match(running,/role="progressbar"/);
          assert.doesNotMatch(running,/aria-valuenow/);
          const speaker={...d,kind:'speaker',caps:['power','volume_level','mute'],state:{online:true,on:true,volume:12,muted:false}};
          assert.match(m.compactBody(speaker,null,'',false),/data-card-range="volume"/);
          assert.match(m.compactBody(speaker,null,'',false),/data-act="mute"/);
        """)


class LayoutViewPreferenceTests(unittest.TestCase):
    def test_retired_mode_requests_are_refused_without_changing_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            svc = HomeService(folder)
            svc.profiles.migrate(svc.store.settings)
            profile = svc.profiles.owner()
            before = dict(profile)
            with self.assertRaises(ProfileError):
                svc.profiles.update(profile["id"],{"room_view":"free"})
            self.assertEqual(svc.profiles.owner(),before)
