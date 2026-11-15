"""Pure shared idle/cleaning presentation; no browser, network or devices."""
import base64
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web/js"


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for JS unit tests")
class IdleVacuumTests(unittest.TestCase):
    def run_js(self, filename, script, prefix=""):
        source = "\n".join(line for line in (WEB / filename).read_text().splitlines() if not line.startswith("import "))
        module = "data:text/javascript;base64," + base64.b64encode((prefix + source).encode()).decode()
        result = subprocess.run(["node", "--input-type=module", "-e",
                                 "import assert from 'node:assert/strict';\n" + script, module],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_status_uses_current_job_not_battery_or_previous_clean(self):
        self.run_js("vacuum-status.js", """
          const {vacuumStatus, idleVacuumLine} = await import(process.argv[1]);
          const s={online:true,activity:'cleaning',battery:100,last_clean:{area_m2:34,minutes:104}};
          assert.equal(vacuumStatus(s).label, 'Cleaning...');
          assert.equal(vacuumStatus(s).metrics, '');
          const job={run_id:'one',status:'cleaning',area_m2:4,elapsed_seconds:300};
          assert.match(vacuumStatus({...s,cleaning:job}).metrics, /5 min reported · 4 m²/);
          for (const activity of ['paused','returning','docked']) {
            assert.equal(vacuumStatus({...s,activity,cleaning:job}).metrics, '');
            assert.notEqual(vacuumStatus({...s,activity}).phase, 'completed');
          }
          assert.equal(vacuumStatus({...s,cleaning:{...job,stats_stale:true}}).metrics, '');
          assert.equal(vacuumStatus({...s,online:false,cleaning:job}).phase, 'offline');
          assert.equal(vacuumStatus({...s,online:false,cleaning:job}).metrics, '');
          assert.equal(vacuumStatus({}).phase, 'unknown');
          assert.equal(vacuumStatus({...s,problem:'Tank full',cleaning:{status:'completed'}}).phase, 'attention');
          assert.equal(vacuumStatus({...s,cleaning:{status:'stopped'}}).phase, 'stopped');
          assert.equal(vacuumStatus({...s,cleaning:{status:'completed'}}).phase, 'cleaning');
          assert.equal(vacuumStatus({...s,cleaning:{run_id:'one',status:'completed'}}).phase, 'completed');
          const bot=(id,name,state)=>({id,name,kind:'vacuum',state});
          const first=bot('a','Kitchen bot',s), second=bot('b','Hall bot',{...s,problem:'Tank full'});
          assert.equal(idleVacuumLine([first,second]), 'Hall bot · Needs attention · +1 more');
          assert.equal(idleVacuumLine([second,first]), idleVacuumLine([first,second]));
          assert.equal(idleVacuumLine([first]), 'Kitchen bot · Cleaning...');
          assert.equal(idleVacuumLine([]), ''); // replacing a profile's device collection clears its summary
          assert.equal(idleVacuumLine([bot('a','Bot',{online:true,activity:'docked',battery:100})]), '');
        """)

    def test_clock_hierarchy_meridiem_faces_and_night_window(self):
        self.run_js("clockfaces.js", """
          const {faceHTML, idleNight, driftOffset} = await import(process.argv[1]);
          const now=new Date(2026, 10, 11, 13, 45);
          const html=faceHTML('date',now,{h24:false,place:'<City>',weather:{temperature:15,condition:'cloudy',label:'Cloudy'}});
          assert.ok(html.indexOf('cf-time') < html.indexOf('cf-calendar'));
          assert.match(html,/cf-weekday/); assert.match(html,/cf-day/);
          assert.match(html,/cf-meridiem/); assert.match(html,/&lt;City>/);
          assert.doesNotMatch(faceHTML('date',now,{h24:true}),/cf-meridiem/);
          assert.match(faceHTML('date',now,{h24:true}),/13:45/);
          for (const face of ['analog','words','date','night','digital']) assert.match(faceHTML(face,now),new RegExp(`cf-${face}`));
          assert.equal(idleNight(now,{}),false);
          assert.equal(idleNight(new Date(2026,10,11,22),{}),true);
          assert.equal(idleNight(new Date(2026,10,11,6),{}),true);
          assert.equal(idleNight(new Date(2026,10,11,7),{}),false);
          assert.equal(idleNight(new Date(2026,10,11,23),{frame_night_clock:false}),false);
          assert.equal(idleNight(now,{clock_face:'night'}),true);
          assert.notDeepEqual(driftOffset(100000,40,30),driftOffset(900000,40,30));
        """, "const esc=s=>String(s).replaceAll('<','&lt;');\n")
