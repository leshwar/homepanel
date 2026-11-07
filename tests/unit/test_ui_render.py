"""DOM update helpers in isolation: Node runs plain JS against tiny element fakes.

Node is only a development/test dependency; the panel still has no build step.
"""
import base64
import hashlib
import re
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
SOURCE = Path(__file__).resolve().parents[2] / "web/js/render.js"


class HeadingStructureTests(unittest.TestCase):
    def test_sortable_vendor_build_is_pinned_and_keeps_its_license(self):
        vendor = SOURCE.parents[1] / "vendor/sortablejs"
        self.assertEqual(hashlib.sha256((vendor / "Sortable.min.js").read_bytes()).hexdigest(),
                         "bf4241bc73fef7f11c59a283a69fe8051cdd31c6d8ff5a2b9ba219e7831fcf76")
        license_text = (vendor / "LICENSE").read_text()
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2019 All contributors to Sortable", license_text)

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
             'const {setMarkup, updateRoomCounts, invalidateMarkup} = await import(process.argv[1]);\n' + script, module],
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
    def test_inline_drafts_done_errors_cancel_and_profile_permissions(self):
        source = (SOURCE.parent / "room-sort.js").read_text()
        source = re.sub(r"^import .*?;\n", "", source, flags=re.MULTILINE)
        source = """const {store, renameRoom, emit, esc, toast} = globalThis.testHelpers;
const saveRooms = () => {}, moveRoom = () => {}, invalidateMarkup = () => {};
""" + source
        module = "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()
        result = subprocess.run([NODE, "--input-type=module", "-e", """
            import assert from 'node:assert/strict';
            const handlers = {}, messages = [], writes = [];
            globalThis.document = {
              activeElement: null, querySelector: () => null, querySelectorAll: () => [],
              addEventListener: (event, fn) => {handlers[event] = fn;}
            };
            globalThis.CSS = {escape: x => x};
            globalThis.matchMedia = () => ({matches: false, addEventListener() {}});
            const store = {me: {id:'admin', role:'admin'}, rooms:['Bedroom','Kitchen']};
            globalThis.testHelpers = {
              store, emit() {}, toast: message => messages.push(message),
              esc: value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;'),
              async renameRoom(old, value) {
                const name = value.trim();
                if (!name) throw new Error('Give the room a name.');
                if (store.rooms.includes(name) && name !== old) throw new Error('That room already exists.');
                if (!store.rooms.includes(old)) throw new Error('Room is no longer available.');
                store.rooms = store.rooms.map(r => r === old ? name : r);
                writes.push([old, name]); return name;
              }
            };
            const mod = await import(process.argv[1]);
            assert.equal(mod.isEditingRooms(), false);
            await mod.toggleRoomEditing('#rail');
            assert.equal(mod.isEditingRooms(), true);
            const field = room => ({dataset:{roomName:room}, closest() {return this;}});
            const input = field('Bedroom');
            const type = value => {input.value = value; handlers.input({target:input});};
            type('Kitchen');
            assert.equal(mod.canLeaveRoomNames(), false);
            assert.equal(await mod.toggleRoomEditing('#rail'), false);
            assert.equal(mod.isEditingRooms(), true);
            assert.match(mod.roomNameField('Bedroom'), /That room already exists/);
            assert.match(mod.roomNameField('Bedroom'), /value="Kitchen"/);
            assert.equal(writes.length, 0);
            type('<Study>');
            assert.match(mod.roomNameField('Bedroom'), /value="&lt;Study>"/);
            handlers.keydown({target:input, key:'Escape', preventDefault(){}, stopImmediatePropagation(){}});
            assert.equal(mod.canLeaveRoomNames(), true);
            assert.match(mod.roomNameField('Bedroom'), /value="Bedroom"/);
            type('Study');
            const kitchen = field('Kitchen'); kitchen.value = 'Cooking';
            handlers.input({target:kitchen});
            assert.equal(await mod.toggleRoomEditing('#rail'), true);
            assert.deepEqual(writes, [['Bedroom','Study'],['Kitchen','Cooking']]);
            assert.equal(mod.isEditingRooms(), false);
            await mod.toggleRoomEditing('#rail');
            input.dataset.roomName = 'Study'; type('Pending');
            store.rooms = ['Office','Cooking'];
            assert.deepEqual(mod.editableRoomNames(store.rooms), ['Office','Cooking','Study']);
            assert.equal(await mod.toggleRoomEditing('#rail'), false);
            assert.match(mod.roomNameField('Study'), /no longer available/);
            store.me = {id:'member', role:'member'};
            mod.syncRoomSorters();
            assert.equal(mod.isEditingRooms(), false);
            assert.deepEqual(mod.editableRoomNames(store.rooms), store.rooms);
            assert.equal(await mod.toggleRoomEditing('#rail'), false);
            assert.equal(writes.length, 2);
        """, module], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cache_belongs_to_the_element_not_the_markup(self):
        self.run_js("""
            const a = {}, b = {};
            assert.equal(setMarkup(a, 'Rooms'), true);
            assert.equal(setMarkup(b, 'Rooms'), true);
            assert.equal(setMarkup(a, 'Rooms'), false);
            assert.equal(b.innerHTML, 'Rooms');
        """)

    def test_external_drag_changes_can_be_reset_to_saved_markup(self):
        self.run_js("""
            const el = {};
            setMarkup(el, 'saved order');
            el.innerHTML = 'dragged order';
            invalidateMarkup(el);
            assert.equal(setMarkup(el, 'saved order'), true);
            assert.equal(el.innerHTML, 'saved order');
        """)

    def test_control_drafts_survive_cache_hits_and_can_be_explicitly_reset(self):
        self.run_js("""
            let value, writes=0;
            const el = {set innerHTML(html) {value=html; writes++;}};
            setMarkup(el, 'reported value');
            value='unsaved gesture';
            assert.equal(setMarkup(el, 'reported value'), false);
            assert.equal(value, 'unsaved gesture');
            invalidateMarkup(el);
            assert.equal(setMarkup(el, 'reported value'), true);
            assert.equal(value, 'reported value');
            assert.equal(writes, 2);
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
