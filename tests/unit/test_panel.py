"""The shared device panel (header switch, stage, tabs) and each kind's stage and tabs.

Plain JS run in Node with tiny stand-ins for the modules a file imports: no browser, no devices.
"""
import base64
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
WEB = Path(__file__).resolve().parents[2] / "web"

STUBS = """
const esc = s => String(s ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const icon = name => `<svg data-i="${name}"></svg>`, svg = icon, deviceIcon = () => '<svg data-i="device"></svg>';
const devicePicture = d => d.picture ? {kind:'photo', html:'<img>'} : null;
const isMedia = d => ['tv','speaker'].includes(d.kind);
const statusText = d => d.state?.online === false ? 'Offline' : d.state?.on ? (d.state.app || 'On') : 'Off';
const kelvinToRgb = () => [255, 200, 150], WORN_PERCENT = 10, toast = () => {};
const store = {devices: new Map()}, command = () => {}, bindRelativeRange = () => {};
const api = {mapUrl: (id, rev) => `/map/${id}?v=${rev}`}, storage = {get: (k, d) => d, set() {}};
globalThis.addEventListener ??= () => {}; globalThis.document ??= {addEventListener() {}, hidden: false};
"""
PANEL_STUBS = """
const powerHero = (d, hint = '') => `<hero data-power hint="${hint}"></hero>`;
const chipChoices = (options, current, attr) => options.map(o => `<chip ${attr}="${o.id}" on="${String(o.id) === String(current)}">${o.name}</chip>`).join('');
const effectTabs = d => (d.caps.includes('effects') ? [{id:'scenes', label:'Scenes', html:'<scenes></scenes>'}] : []);
"""


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class PanelTests(unittest.TestCase):
    def run_js(self, filename, script, stubs=STUBS + PANEL_STUBS):
        source = "\n".join(line for line in (WEB / "js" / filename).read_text().splitlines() if not line.startswith("import "))
        module = "data:text/javascript;base64," + base64.b64encode((stubs + source).encode()).decode()
        result = subprocess.run([NODE, "--input-type=module", "-e",
                                 "import assert from 'node:assert/strict';\nconst count = (html, re) => (html.match(re) || []).length;\n" + script, module],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_header_switch_status_and_settings(self):
        self.run_js("panel.js", """
          const {panelHead, panelStatus, powerSwitch} = await import(process.argv[1]);
          const lamp = {id:'l', name:'Lamp <b>', kind:'light', caps:['power'], state:{online:true, on:true}};
          const head = panelHead(lamp);
          assert.match(head, /Lamp &lt;b>/);
          assert.match(head, /role="switch" data-power aria-checked="true"/);
          assert.match(head, /title="Turn off"/);
          assert.match(head, /data-edit aria-label="Device settings"/);
          assert.match(head, /data-close aria-label="Close device controls"/);
          assert.ok(head.indexOf('data-power') < head.indexOf('data-edit') && head.indexOf('data-edit') < head.indexOf('data-close'));
          assert.match(powerSwitch({...lamp, state:{online:true, on:false}}), /aria-checked="false"[\\s\\S]*title="Turn on"/);
          // Power not reported: no blind toggle.
          const unknown = {...lamp, state:{online:true}};
          assert.match(powerSwitch(unknown), /aria-checked="false"[\\s\\S]*power, not reported[\\s\\S]*disabled/);
          assert.equal(panelStatus(unknown), 'Connected; power not reported');
          assert.equal(powerSwitch({...lamp, caps:['clean']}), '');                 // a vacuum has no power switch
          assert.doesNotMatch(panelHead(lamp, {controls:false}), /data-power/);    // offline or unpaired: nothing to switch
          assert.equal(panelStatus({kind:'tv', caps:['power'], state:{online:true, on:true, app:'Netflix', muted:true}}), 'Netflix · Muted');
          assert.equal(panelStatus({kind:'tv', caps:['power'], state:{online:true, on:false, muted:true}}), 'Off');
          assert.match(panelHead({...lamp, picture:true}), /class="panel-pic photo"/);
          assert.match(panelHead(lamp), /class="panel-pic line"/);
        """, STUBS)

    def test_tabs_show_one_pane_and_remember_the_choice(self):
        self.run_js("panel.js", """
          const {panelBody, activeTab, setTab, tabKey} = await import(process.argv[1]);
          const d = {id:'d1'}, tabs = [{id:'a', label:'Apps', html:'<p>apps</p>'}, {id:'b', label:'Inputs', html:'<p>inputs</p>', alert:true},
            {id:'c', label:'Empty', html:''}, false];
          let html = panelBody(d, {stage:'<div>stage</div>', tabs});
          assert.match(html, /class="panel duo"/);
          assert.equal(count(html, /role="tab"/g), 2);                             // empty and missing tabs are dropped
          assert.match(html, /data-tab="a" aria-selected="true"[^>]*tabindex="0"/s);
          assert.match(html, /data-tab="b" aria-selected="false"[^>]*tabindex="-1"/s);
          assert.match(html, /data-pane="a" role="tabpanel"/);
          assert.match(html, /apps/); assert.doesNotMatch(html, /inputs<\\/p>/);    // only the chosen pane is drawn
          assert.match(html, /tab-alert/);
          html = panelBody(d, {stage:'x', tabs, prefer:'b'});                      // what the device is doing now
          assert.match(html, /data-pane="b"/);
          setTab('d1', 'a');                                                       // the person's pick wins from then on
          assert.match(panelBody(d, {stage:'x', tabs, prefer:'b'}), /data-pane="a"/);
          assert.equal(activeTab('d1', [{id:'z'}]), 'z');                          // a tab that is gone falls back
          assert.equal(activeTab('other', []), null);
          // One tab: no tab bar, just the pane. No tabs: the stage alone.
          html = panelBody({id:'d2'}, {stage:'x', tabs:[tabs[0]]});
          assert.doesNotMatch(html, /role="tab"/); assert.match(html, /role="group" aria-label="Apps"/);
          assert.match(panelBody({id:'d3'}, {stage:'x'}), /class="panel solo"/);
          assert.match(panelBody({id:'d3'}, {tabs:[tabs[0]]}), /class="panel solo"/);
          assert.match(panelBody({id:'d3'}, {stage:'x', note:'<div class="note">hint</div>'}), /^<div class="note">hint/);
          // Arrow keys walk the tab list and wrap.
          const list = ['a','b','c'].map(id => ({dataset:{tab:id}}));
          const parent = {querySelectorAll: () => list};
          const key = (from, name) => { let stopped = false; const tab = list[from]; tab.parentElement = parent;
            const next = tabKey({key:name, target:{closest: () => tab}, preventDefault() { stopped = true; }}); return [next, stopped]; };
          assert.deepEqual(key(0, 'ArrowRight'), ['b', true]);
          assert.deepEqual(key(0, 'ArrowLeft'), ['c', true]);
          assert.deepEqual(key(1, 'Home'), ['a', true]);
          assert.deepEqual(key(1, 'End'), ['c', true]);
          assert.deepEqual(key(1, 'Enter'), [null, false]);
          assert.equal(tabKey({key:'ArrowRight', target:{closest: () => null}}), null);
        """, STUBS)

    def test_power_button_and_chips(self):
        self.run_js("panel.js", """
          const {powerHero, chipChoices} = await import(process.argv[1]);
          const plug = {name:'Kettle', caps:['power'], state:{online:true, on:true}};
          assert.match(powerHero(plug), /class="power-orb" data-power aria-pressed="true"[\\s\\S]*aria-label="Turn off Kettle"[\\s\\S]*<b>On<\\/b>/);
          assert.match(powerHero({...plug, state:{online:true, on:false}}, 'Turn it on to use the remote.'), /<b>Off<\\/b>[\\s\\S]*Turn it on to use the remote/);
          const unknown = powerHero({...plug, state:{online:true}});
          assert.match(unknown, /disabled/); assert.match(unknown, /Not reported/); assert.match(unknown, /data-refresh/);
          const chips = chipChoices([{id:'arc', name:'TV <ARC>'}, {id:1, name:'Optical'}], '1', 'data-input', {glyph:'input', label:'Input'});
          assert.match(chips, /role="group" aria-label="Input"/);
          assert.match(chips, /data-input="arc" aria-pressed="false"/); assert.match(chips, /data-input="1" aria-pressed="true"/);
          assert.match(chips, /TV &lt;ARC>/); assert.equal(count(chips, /data-i="input"/g), 2);
          assert.equal(chipChoices([], null, 'data-input'), '');
        """, STUBS)

    def test_light_stage_and_tabs_follow_capabilities(self):
        self.run_js("light.js", """
          const {lightPanel, isLight, tempWord} = await import(process.argv[1]);
          const lamp = (caps, state = {}) => ({id:'l', name:'Lamp', kind:'light', caps, state:{online:true, on:true, ...state}});
          let p = lightPanel(lamp(['power','brightness','color','color_temp','effects'], {brightness:60, color_mode:'effect'}));
          assert.match(p.stage, /id="bri" role="slider"[\\s\\S]*aria-valuemin="0"[\\s\\S]*aria-valuenow="60"/);
          assert.match(p.stage, /id="bri-val">60%</);
          assert.doesNotMatch(p.stage, /Drag|Release/);                            // no instructions printed on the control
          assert.deepEqual(p.tabs.map(t => t.id), ['color', 'white', 'scenes']);
          assert.equal(p.prefer, 'scenes');                                        // open on what the light is doing
          assert.equal(lightPanel(lamp(['power','brightness','color'], {color_mode:'color'})).prefer, 'color');
          assert.equal(count(p.tabs[0].html, /data-color="#/g), 8);
          assert.equal(count(p.tabs[1].html, /data-kelvin="/g), 3);
          assert.match(p.tabs[1].html, /id="ct" role="slider"/);
          // Off: the bar is empty and says so. Unknown level: says so and cannot be dragged.
          assert.match(lightPanel(lamp(['power','brightness'], {on:false, brightness:60})).stage, /aria-valuenow="0"[\\s\\S]*>Off</);
          p = lightPanel(lamp(['power','brightness']));
          assert.match(p.stage, /aria-disabled="true"/); assert.match(p.stage, /Not reported/); assert.match(p.stage, /data-refresh/);
          assert.deepEqual(p.tabs, []);
          // Brightness only: it cannot be turned off from here, so the bar stops at 1.
          assert.match(lightPanel(lamp(['brightness'], {brightness:45})).stage, /aria-valuemin="1"/);
          // No brightness: the big power button takes the stage.
          assert.match(lightPanel(lamp(['power','color'])).stage, /<hero data-power/);
          assert.match(lightPanel({...lamp(['power','brightness'], {brightness:5}), meta:{hint:'Turn on <LAN> control'}}).note, /Turn on &lt;LAN> control/);
          assert.equal(isLight({kind:'plug', caps:['power']}), false);
          assert.equal(isLight({kind:'other', caps:['color_temp']}), true);
          assert.deepEqual([2700, 4000, 6000].map(tempWord), ['Warm', 'Neutral', 'Cool']);
        """)

    def test_tv_stage_and_tabs_follow_capabilities(self):
        self.run_js("remote.js", """
          const {remotePanel} = await import(process.argv[1]);
          const tv = (caps, state = {}, meta = {}) => ({id:'t', name:'TV', kind:'tv', caps, meta, state:{online:true, on:true, ...state}});
          const full = ['power','volume','mute','channel','remote','media','apps','inputs','sound_mode'];
          const meta = {apps:[{id:'z', name:'Zebra'}, {id:'n', name:'Netflix'}, {id:'y', name:'YouTube'}], inputs:[{id:'hdmi1', name:'HDMI 1'}],
            sound_modes:[{id:'cinema', name:'Cinema'}]};
          let p = remotePanel(tv(full, {volume:18, muted:false, app:'n'}, meta));
          assert.match(p.stage, /data-layout="dpad"/);
          for (const hook of ['data-act="volume_up"', 'data-act="volume_down"', 'data-act="channel_up"', 'data-key="OK"', 'data-key="BACK"',
            'data-key="HOME"', 'data-playpause', 'data-mute']) assert.ok(p.stage.includes(hook), hook);
          assert.match(p.stage, /<b>18<\\/b>Vol/);
          assert.match(p.stage, /data-mute aria-label="Mute"\\s+aria-pressed="false"/);
          assert.deepEqual(p.tabs.map(t => t.id), ['apps', 'inputs', 'sound', 'keys']);
          assert.equal(p.prefer, 'apps');
          const apps = p.tabs[0].html;                                             // well-known apps first, then A to Z
          assert.ok(apps.indexOf('YouTube') < apps.indexOf('Netflix') && apps.indexOf('Netflix') < apps.indexOf('Zebra'));
          assert.match(apps, /data-app="n" aria-pressed="true"/);
          assert.match(p.tabs[3].html, /data-key="MENU"/); assert.match(p.tabs[3].html, /data-key="EXIT"/);
          assert.equal(remotePanel(tv(full, {input:'hdmi1'}, meta)).prefer, 'inputs');
          // Off: one big power button, no remote to press by mistake, no tabs.
          p = remotePanel(tv(full, {on:false}, meta));
          assert.match(p.stage, /<hero data-power hint="Turn it on to use the remote\\."/); assert.deepEqual(p.tabs, []);
          assert.match(remotePanel(tv(full, {on:undefined}, meta)).stage, /Waiting for the device/);
          // Fewer capabilities: only what the device can do.
          p = remotePanel(tv(['power','volume'], {volume:5, muted:true}));
          assert.match(p.stage, /data-layout="none"/); assert.doesNotMatch(p.stage, /data-key=|data-mute|channel_up/); assert.deepEqual(p.tabs, []);
          assert.doesNotMatch(remotePanel(tv(['power','volume','mute'], {})).stage, /data-mute/);     // mute not reported: no blind toggle
          assert.match(remotePanel(tv(['power','volume','mute'], {muted:true})).stage, /aria-label="Unmute"\\s+aria-pressed="true"/);
          assert.equal(count(remotePanel(tv(['power','remote','pointer'])).stage, /data-mode="/g), 3);
        """)

    def test_vacuum_stage_and_tabs(self):
        self.run_js("vacuum.js", """
          const {vacuumPanel, picked} = await import(process.argv[1]);
          const bot = (state = {}, meta = {}) => ({id:'v', name:'Bot', kind:'vacuum', caps:['clean','dock','map','rooms','suction','clean_mode','station','locate'],
            meta:{rooms:[{id:1, name:'Hall'}, {id:2, name:'Kitchen <1>'}], suction_levels:[{id:'max', name:'Max'}], clean_modes:[{id:'mop', name:'Mop'}],
              station_actions:[{id:'empty_dustbin', name:'Empty dustbin'}], ...meta},
            state:{online:true, activity:'docked', battery:100, map_rev:3, ...state}});
          let p = vacuumPanel(bot({parts:[{id:'f', name:'Filter', percent:18}], last_clean:{area_m2:46, minutes:38}}));
          assert.match(p.stage, /data-clean="start" data-activity="cleaning"[^>]*>[\\s\\S]*Start cleaning/);
          assert.match(p.stage, /src="\\/map\\/v\\?v=3"/); assert.match(p.stage, /Last clean 46 m² in 38 min/);
          assert.match(p.stage, /data-locate/); assert.doesNotMatch(p.stage, /data-dock|data-clean="stop"/);   // already docked, nothing to stop
          assert.deepEqual(p.tabs.map(t => t.id), ['rooms', 'options', 'station', 'care']);
          assert.match(p.tabs[0].html, /Kitchen &lt;1>/); assert.match(p.tabs[0].html, /Tap rooms to clean only those/);
          assert.equal(p.tabs[3].alert, false); assert.match(p.tabs[3].html, /All parts good\\. Filter at 18%/);
          // Picking rooms changes the main button, and says how many.
          picked('v').add('2'); picked('v').add('99');                              // 99 is no longer a room: dropped
          p = vacuumPanel(bot());
          assert.match(p.stage, /data-clean-rooms>[\\s\\S]*Clean 1 room</); assert.match(p.tabs[0].html, /1 selected/);
          assert.match(p.tabs[0].html, /data-room-pick="2" aria-pressed="true"/); assert.match(p.tabs[0].html, /data-rooms-clear/);
          picked('v').clear();
          // While cleaning: pause is the main button, with Stop and Dock beside it.
          p = vacuumPanel(bot({activity:'cleaning', battery:60}));
          assert.match(p.stage, /data-clean="pause"/); assert.match(p.stage, /data-clean="stop"/); assert.match(p.stage, /data-dock/);
          assert.match(vacuumPanel(bot({activity:'paused'})).stage, /data-clean="resume"[\\s\\S]*Keep cleaning/);
          // Problems and worn parts are shown, not hidden behind a tab.
          p = vacuumPanel(bot({problem:'Tank <full>', parts:[{id:'t', name:'Mop tray', percent:0}]}));
          assert.match(p.stage, /class="note warn">Tank &lt;full></);
          assert.equal(p.tabs.at(-1).alert, true); assert.match(p.tabs.at(-1).html, /Mop tray needs replacing/);
          assert.match(vacuumPanel(bot({activity:undefined})).stage, /data-refresh>Refresh status/);
          assert.deepEqual(vacuumPanel({...bot(), caps:['clean'], meta:{}}).tabs, []);
        """)

    def test_purifier_stage_and_tabs(self):
        self.run_js("purifier.js", """
          const {purifierPanel} = await import(process.argv[1]);
          const air = (caps, state = {}) => ({id:'p', name:'Air', kind:'purifier', caps,
            meta:{fan_modes:[{id:'auto', name:'Auto'}, {id:'manual', name:'Manual'}], fan_speeds:[{id:1, name:'Low'}, {id:2, name:'High'}]},
            state:{online:true, on:true, ...state}});
          let p = purifierPanel(air(['power','fan_mode','fan_speed','air_quality','filter_life'], {fan_mode:'manual', fan_speed:2, pm25:7, air_quality:'Good', filter_life:80}));
          assert.match(p.stage, /PM2\\.5[\\s\\S]*<b>7<\\/b>[\\s\\S]*Good[\\s\\S]*<b>80<\\/b>/);
          assert.deepEqual(p.tabs.map(t => t.id), ['mode', 'speed']);
          assert.match(p.tabs[0].html, /data-fan-mode="manual" on="true"/); assert.match(p.tabs[1].html, /data-fan-speed="2" on="true"/);
          assert.match(p.tabs[1].html, /switches to Manual mode/);
          // Off: nothing is "current", and the readings are marked as the last ones.
          p = purifierPanel(air(['power','fan_mode','air_quality'], {on:false, fan_mode:'auto'}));
          assert.doesNotMatch(p.tabs[0].html, /on="true"/); assert.match(p.stage, /Last readings/); assert.match(p.stage, /Not reported/);
          assert.match(purifierPanel(air(['power','fan_mode'])).stage, /<hero data-power/);          // no readings: the power button
        """)


if __name__ == "__main__":
    unittest.main()
