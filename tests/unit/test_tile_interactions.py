"""Tile action policy, stable artwork and late-result profile isolation."""
import base64
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web/js"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class TileInteractionTests(unittest.TestCase):
    def run_js(self, filename, helpers, script):
        source = "\n".join(line for line in (WEB / filename).read_text().splitlines() if not line.startswith("import "))
        module = "data:text/javascript;base64," + base64.b64encode((helpers + source).encode()).decode()
        result = subprocess.run([NODE, "--input-type=module", "-e",
                                 "import assert from 'node:assert/strict';\n" + script, module],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_tiles_have_safe_open_controls_and_capability_bound_quick_actions(self):
        self.run_js("tiles.js", """
          const store={busy:new Set(),devices:new Map()}, command=()=>{};
          const esc=s=>String(s??'').replaceAll('<','&lt;').replaceAll('"','&quot;'), icon=()=>'<svg></svg>';
          const isMedia=d=>['tv','speaker'].includes(d.kind), glowVar=()=>'1 2 3', statusText=()=>'On', needsAttention=d=>!!d.state?.problem;
          const toast=()=>{},openDevice=()=>{},deviceIcon=()=>'<svg></svg>',devicePicture=()=>null,syncAttributes=()=>{};
        """, """
          const {tileHtml,primaryAction}=await import(process.argv[1]);
          for(const kind of ['light','plug','switch','fan','purifier','tv','speaker','vacuum','other']){
            const d={id:kind,name:'Device <name>',kind,caps:['power'],state:{online:true,on:false}};
            const html=tileHtml(d);
            assert.match(html,/Open controls/); assert.match(html,/role="group"/);
            assert.ok(html.indexOf('data-more')<html.indexOf('data-quick-action'));
            assert.doesNotMatch(html,/Tap to turn/);assert.match(html,/Turn on/);
            assert.match(html,/&lt;name>/);
            assert.equal(primaryAction({...d,caps:[]}),null);
            assert.equal(primaryAction({...d,state:{online:false,on:false}}).disabled,true);
            assert.equal(primaryAction({...d,state:{online:true}}).disabled,true);
          }
          const vacuum={id:'v',caps:['clean'],state:{online:true,activity:'cleaning'}};
          assert.equal(primaryAction(vacuum).value,'pause');
          assert.equal(primaryAction({...vacuum,state:{online:true,activity:'paused'}}).value,'resume');
          assert.equal(primaryAction({...vacuum,state:{online:true,activity:'returning'}}),null);
          const tv={id:'tv',name:'TV',kind:'tv',caps:['power'],state:{online:true,on:true}};
          assert.doesNotMatch(tileHtml(tv),/data-act=/);
          assert.match(tileHtml({...tv,caps:['power','volume']}),/data-act="volume_up"/);
          assert.match(tileHtml(tv,{editing:true}),/data-more tabindex="-1"/);
          // A wide TV or speaker tile shows the level between its volume buttons, when one is reported.
          const loud={...tv,caps:['power','volume'],state:{online:true,on:true,volume:17.6}};
          const wide=tileHtml(loud,{size:'2x1'});
          assert.match(wide,/<output class="tile-vol" aria-label="Volume 18%">18<.output>/);
          assert.ok(wide.indexOf('volume_down')<wide.indexOf('tile-vol')&&wide.indexOf('tile-vol')<wide.indexOf('volume_up'));
          assert.match(tileHtml({...loud,state:{...loud.state,muted:true}},{size:'2x1'}),/>Muted<.output>/);
          assert.doesNotMatch(tileHtml({...loud,state:{online:true,on:true}},{size:'2x1'}),/tile-vol/);
          assert.doesNotMatch(tileHtml({...loud,state:{...loud.state,on:false}},{size:'2x1'}),/tile-vol|volume_up/);
        """)

    def test_scoped_art_is_stable_without_duplicate_gradient_ids(self):
        self.run_js("art.js", "const esc=s=>String(s);\n", """
          const {artSvg}=await import(process.argv[1]);
          const a=artSvg('bulb','','tile-rooms-a'),b=artSvg('bulb','','tile-rooms-b');
          assert.equal(a,artSvg('bulb','','tile-rooms-a'));
          assert.notEqual(a,b);
          const ids=s=>[...s.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);
          assert.ok(ids(a).length>0);
          assert.ok(ids(a).every(id=>!ids(b).includes(id)));
          assert.notEqual(artSvg('bulb'),artSvg('bulb'));
        """)

    def test_late_command_cannot_restore_another_profiles_hidden_device(self):
        self.run_js("store.js", "const {api,storage,toast}=globalThis.fixture;\n", """
          let resolve,reject;const messages=[];
          globalThis.fixture={api:{command:()=>new Promise((yes,no)=>{resolve=yes;reject=no;})},
            storage:{get:(k,fallback)=>fallback,set(){}},toast:m=>messages.push(m)};
          const {store,command}=await import(process.argv[1]);
          store.me={id:'owner'};store.devices.set('hidden',{id:'hidden',state:{on:false}});
          const sending=command('hidden','power',true);
          store.me={id:'member'};store.devices.clear();
          resolve({id:'hidden',state:{on:true}});await sending;
          assert.equal(store.devices.has('hidden'),false);
          store.me={id:'owner'};store.devices.set('hidden',{id:'hidden',state:{on:false}});
          const failing=command('hidden','power',true);
          store.me={id:'member'};store.devices.clear();
          reject(new Error('Private device failed'));await failing;
          assert.deepEqual(messages,[]);
          assert.equal(store.devices.size,0);
        """)
