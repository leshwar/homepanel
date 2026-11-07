"""Shared control labels and gesture safety without a browser or devices."""
import base64
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
SOURCE = Path(__file__).resolve().parents[2] / "web/js/device-controls.js"


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class DeviceControlTests(unittest.TestCase):
    def test_labels_capabilities_and_relative_gesture_lifecycle(self):
        source = "\n".join(line for line in SOURCE.read_text().splitlines() if not line.startswith("import "))
        source = """const esc = s => String(s).replaceAll('<','&lt;'), icon = () => '<svg></svg>', statusText = () => 'Offline';\n""" + source
        module = "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()
        result = subprocess.run([NODE, "--input-type=module", "-e", """
            import assert from 'node:assert/strict';
            const {powerControls,deviceHeading,relativeValue,bindRelativeRange,controlGestureBusy,clearControlGestures}
              = await import(process.argv[1]);
            assert.equal(powerControls({caps:[],state:{}}), '');
            assert.match(powerControls({caps:['power'],state:{on:false}}), /Turn on/);
            assert.match(powerControls({caps:['power'],state:{}}), /disabled/);
            assert.match(powerControls({caps:['mute'],state:{muted:true}}), /Unmute/);
            assert.match(deviceHeading({name:'<device>',caps:[]}), /&lt;device>/);
            assert.match(deviceHeading({name:'Device',caps:['power'],state:{online:true}}), /power not reported/);
            assert.equal(relativeValue(30, 100, 100, 200), 30);
            assert.equal(relativeValue(30, 100, 140, 200), 50);
            assert.equal(relativeValue(90, 0, 100, 200), 100);
            const events = {}, sent = [], previews = [];
            let current = 30;
            const range = {
              disabled:false, min:'0', max:'100', step:'5', value:'30', isConnected:true,
              addEventListener:(name, fn) => {events[name] = fn;},
              focus() {}, setPointerCapture() {}, closest:() => null,
              getBoundingClientRect:() => ({width:200}),
            };
            bindRelativeRange(range, {value:()=>current, preview:v=>previews.push(v),
              commit:v=>{current=v; sent.push(v);}, idle() {}});
            const event = (type, x, y=0) => events[type]({type,pointerId:1,button:0,clientX:x,clientY:y,preventDefault(){}});
            event('pointerdown',170); event('pointerup',170);
            assert.deepEqual(sent, []); assert.equal(Number(range.value), 30);
            event('pointerdown',50); event('pointermove',90);
            assert.equal(controlGestureBusy(), true); assert.equal(Number(range.value), 50);
            assert.deepEqual(sent, []);
            event('pointercancel',90); assert.equal(Number(range.value), 30);
            assert.equal(controlGestureBusy(), false);
            event('pointerdown',50); event('pointermove',60,80); event('pointerup',60,80);
            assert.deepEqual(sent, []); // vertical scrolling cannot adjust a horizontal slider
            event('pointerdown',50); event('pointermove',90); clearControlGestures(); event('pointerup',90);
            assert.deepEqual(sent, []); assert.equal(controlGestureBusy(), false);
            event('pointerdown',50); event('pointermove',90); event('pointerup',90);
            assert.deepEqual(sent, [50]); assert.equal(controlGestureBusy(), false);
        """, module], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
