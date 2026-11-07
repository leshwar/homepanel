"""DOM update helpers in isolation: Node runs plain JS against tiny element fakes.

Node is only a development/test dependency; the panel still has no build step.
"""
import base64
import re
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
SOURCE = Path(__file__).resolve().parents[2] / "web/js/render.js"


class HeadingStructureTests(unittest.TestCase):
    def test_home_keeps_accessible_heading_and_navigation_without_brand_heading(self):
        web = SOURCE.parents[1]
        self.assertIn('<h1 id="title">Home</h1>', (web / "index.html").read_text())
        app = (web / "js/app.js").read_text()
        self.assertIn('data-nav="home"', app)
        self.assertNotIn('class="rail-head"', app)
        css = (web / "shell.css").read_text()
        rule = re.search(r'html\[data-view="home"\] #title \{([^}]+)\}', css).group(1)
        for declaration in ("position: absolute", "width: 1px", "height: 1px", "clip-path: inset(50%)"):
            self.assertIn(declaration, rule)
        self.assertNotIn("display: none", rule)
        self.assertNotIn("visibility: hidden", rule)


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class RenderTests(unittest.TestCase):
    def run_js(self, script):
        module = "data:text/javascript;base64," + base64.b64encode(SOURCE.read_bytes()).decode()
        result = subprocess.run(
            [NODE, "--input-type=module", "-e",
             'import assert from "node:assert/strict";\n'
             'const {setMarkup, updateRoomCounts} = await import(process.argv[1]);\n' + script, module],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unchanged_markup_is_not_written_and_changed_markup_is(self):
        self.run_js("""
            const writes = [];
            const el = {set innerHTML(value) {writes.push(value);}};
            assert.equal(setMarkup(el, '<button>Kitchen</button>'), true);
            assert.equal(setMarkup(el, '<button>Kitchen</button>'), false);
            assert.equal(setMarkup(el, '<button>Bedroom</button>'), true);
            assert.equal(setMarkup(el, ''), true);
            assert.equal(setMarkup(el, ''), false);
            assert.deepEqual(writes, ['<button>Kitchen</button>', '<button>Bedroom</button>', '']);
        """)

    def test_cache_belongs_to_the_element_not_the_markup(self):
        self.run_js("""
            const a = {}, b = {};
            assert.equal(setMarkup(a, 'Rooms'), true);
            assert.equal(setMarkup(b, 'Rooms'), true);
            assert.equal(setMarkup(a, 'Rooms'), false);
            assert.equal(b.innerHTML, 'Rooms');
        """)

    def test_badges_update_in_place_including_zero_without_rewriting_same_text(self):
        self.run_js("""
            let text = '', label = '', textWrites = 0, labelWrites = 0;
            const badge = {
                dataset: {roomCount: 'Kitchen'}, hidden: true,
                get textContent() {return text;},
                set textContent(value) {text = value; textWrites++;},
                getAttribute(name) {assert.equal(name, 'aria-label'); return label;},
                setAttribute(name, value) {assert.equal(name, 'aria-label'); label = value; labelWrites++;},
            };
            const root = {querySelectorAll: () => [badge]};
            updateRoomCounts(root, room => {assert.equal(room, 'Kitchen'); return 2;});
            assert.equal(badge.hidden, false);
            assert.equal(text, '2');
            assert.equal(label, '2 on');
            updateRoomCounts(root, () => 2);
            assert.equal(textWrites, 1);
            assert.equal(labelWrites, 1);
            updateRoomCounts(root, () => 0);
            assert.equal(badge.hidden, true);
            assert.equal(text, '0');
            assert.equal(label, '0 on');
            updateRoomCounts(root, () => 1);
            assert.equal(badge.hidden, false);
            assert.equal(text, '1');
        """)
