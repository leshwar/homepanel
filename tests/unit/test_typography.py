"""Bundled typography integrity and preview state, without network/browser."""
import base64
import hashlib
import re
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
NODE = shutil.which("node")


class FontAssetTests(unittest.TestCase):
    def test_settings_text_surfaces_do_not_use_dashboard_transparency(self):
        css = (WEB / "app.css").read_text()
        rule = re.search(r"#settings :is\(\.card, \.list\) \{([^}]+)\}", css).group(1)
        self.assertIn("background-color: var(--dusk)", rule)
        self.assertIn("backdrop-filter: none", rule)
        self.assertNotIn("--glass-alpha", rule)

    def test_unmodified_variable_font_and_license_are_bundled(self):
        font = (WEB / "fonts/manrope-variable.ttf").read_bytes()
        self.assertEqual(len(font), 164700)
        self.assertEqual(hashlib.sha256(font).hexdigest(),
                         "3ae11c49db0455a3cc33e37d380f20fdb8c7f8b41dc07625c177e3d87a9d6ae6")
        self.assertEqual(font[:4], b"\x00\x01\x00\x00")
        self.assertIn(b"fvar", font)
        license_text = (WEB / "fonts/OFL.txt").read_text()
        self.assertIn("Copyright 2018 The Manrope Project Authors", license_text)
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", license_text)
        css = (WEB / "app.css").read_text()
        self.assertIn('url("/fonts/manrope-variable.ttf")', css)
        self.assertIn("font-display: swap", css)
        self.assertIn('font-weight: 200 800', css)
        self.assertNotIn("fonts.googleapis.com", css)

    @unittest.skipUnless(NODE, "Node.js is needed for the JS unit tests")
    def test_three_sizes_preview_persists_across_refresh_and_cancel_restores_saved_value(self):
        module = "data:text/javascript;base64," + base64.b64encode((WEB / "js/typography.js").read_bytes()).decode()
        script = """
          import assert from 'node:assert/strict';
          globalThis.document = {documentElement:{dataset:{}}};
          const warnings = []; console.warn = message => warnings.push(message);
          const {FONT_SIZES, FONT_SIZE_NAMES, applyTypography, previewTypography} = await import(process.argv[1]);
          assert.deepEqual(FONT_SIZES, ['small','medium','large']);
          assert.deepEqual(Object.values(FONT_SIZE_NAMES), ['Small','Medium','Large']);
          applyTypography();
          assert.equal(document.documentElement.dataset.fontSize, 'medium');
          previewTypography('large');
          applyTypography('small'); // a live snapshot must not erase the local preview
          assert.equal(document.documentElement.dataset.fontSize, 'large');
          previewTypography(null);
          assert.equal(document.documentElement.dataset.fontSize, 'small');
          applyTypography('large');
          assert.equal(document.documentElement.dataset.fontSize, 'large');
          applyTypography('invalid');
          assert.equal(document.documentElement.dataset.fontSize, 'medium');
          assert.equal(warnings.length, 1);
        """
        result = subprocess.run([NODE, "--input-type=module", "-e", script, module],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
