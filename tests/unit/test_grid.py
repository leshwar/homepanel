"""Shared Home/room grid geometry, without a browser or third-party JS packages."""
import base64
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
SOURCE = Path(__file__).resolve().parents[2] / "web/js/grid.js"


@unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
class GridTests(unittest.TestCase):
    def run_js(self, script):
        module = "data:text/javascript;base64," + base64.b64encode(SOURCE.read_bytes()).decode()
        result = subprocess.run(
            [NODE, "--input-type=module", "-e",
             'import assert from "node:assert/strict";\n'
             'const {arrange, remember, place, fits, columnsFor, watchGridWidth} = await import(process.argv[1]);\n' + script, module],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_free_placement_preserves_holes_and_other_tiles(self):
        self.run_js("""
            const items = [{id: 'a', size: '1x1'}, {id: 'b', size: '2x1'}];
            for (const cols of [2, 4, 6]) {
                const before = remember(items, cols);
                assert.equal(place(items, cols, 'a', {x: 0, y: 5, size: '2x2'}), true);
                const saved = arrange(items, cols);
                assert.deepEqual(saved.get('a'), {x: 0, y: 5, size: '2x2'});
                assert.deepEqual(saved.get('b'), before.get('b'));
                assert.equal(place(items, cols, 'a', {...saved.get('b')}), false);
                assert.equal(place(items, cols, 'a', {x: cols - 1, y: 5, size: '2x2'}), false);
                assert.equal(place(items, cols, 'a', {x: 0, y: -1, size: '1x1'}), false);
                assert.deepEqual(arrange(items, cols), saved);
            }
        """)

    def test_responsive_projection_does_not_mutate_saved_positions(self):
        self.run_js("""
            const items = [
              {id: 'a', size: '1x1', positions: {6: {x: 4, y: 3, size: '2x2'}}},
              {id: 'b', size: '2x1', positions: {6: {x: 0, y: 0, size: '2x1'}}},
              {id: 'c', size: '1x1'},
            ];
            const original = JSON.stringify(items);
            for (const cols of [2, 4, 6]) {
                const occupied = [];
                for (const p of arrange(items, cols).values()) {
                    assert.equal(fits(p, occupied, cols), true);
                    occupied.push(p);
                }
            }
            assert.equal(JSON.stringify(items), original);
            assert.equal(place(items, 2, 'a', {x: 0, y: 8, size: '1x1'}), true);
            assert.deepEqual(items[0].positions[6], {x: 4, y: 3, size: '2x2'});
            assert.equal(columnsFor(599), 2);
            assert.equal(columnsFor(600), 4);
            assert.equal(columnsFor(959), 4);
            assert.equal(columnsFor(960), 6);
        """)

    def test_new_and_hidden_items_do_not_compact_existing_positions(self):
        self.run_js("""
            const items = [
                {id: 'a', size: '1x1', positions: {4: {x: 3, y: 3, size: '1x1'}}},
                {id: 'hidden', hidden: true, size: '2x2', positions: {4: {x: 0, y: 0, size: '2x2'}}},
                {id: 'new', size: '2x1'},
            ];
            const positions = remember(items, 4);
            assert.deepEqual(positions.get('a'), {x: 3, y: 3, size: '1x1'});
            assert.deepEqual(positions.get('new'), {x: 0, y: 0, size: '2x1'});
            assert.equal(positions.has('hidden'), false);
        """)

    def test_resize_observer_keeps_nodes_when_snapshot_already_rendered_width(self):
        self.run_js("""
            let notify, renders = 0, columns = 4;
            globalThis.ResizeObserver = class {
                constructor(callback) {notify = callback;}
                observe() {}
            };
            const root = {querySelectorAll: () => [{style: {getPropertyValue: () => String(columns)}}]};
            watchGridWidth(root, () => {renders++; columns = 2;});
            notify([{contentRect: {width: 720}}]);
            assert.equal(renders, 0);
            notify([{contentRect: {width: 393}}]);
            assert.equal(renders, 1);
            notify([{contentRect: {width: 393}}]);
            notify([{contentRect: {width: 0}}]);
            assert.equal(renders, 1);
        """)
