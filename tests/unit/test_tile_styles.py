"""Unit tests: the tile styles keep a readable minimum whatever Glass transparency is set to.

The look is CSS (web/app.css), so these read the rules themselves; the browser test
test_tiles_stay_readable_at_full_glass_transparency checks them as drawn.
"""
import os
import re
import unittest

CSS = open(os.path.join(os.path.dirname(__file__), "..", "..", "web", "app.css")).read()


def rule(selector_start: str) -> str:
    """The body of the first rule whose selector starts with selector_start."""
    i = CSS.index(selector_start)
    return CSS[CSS.index("{", i) + 1: CSS.index("}", i)]


class TileStyleTests(unittest.TestCase):
    def test_light_tiles_have_an_opacity_floor(self):
        body = rule('html[data-tiles="light"] :is(.tile, .widget:not(.t-device), .scene')
        m = re.search(r"background-color: rgb\(246 248 253 / clamp\(([\d.]+),", body)
        self.assertIsNotNone(m, body)
        self.assertGreaterEqual(float(m.group(1)), 0.7)
        on = rule('html[data-tiles="light"] .tile.on')
        self.assertGreaterEqual(float(re.search(r"clamp\(([\d.]+),", on).group(1)), 0.8)

    def test_dark_tiles_over_a_wallpaper_have_a_floor(self):
        body = rule('html.has-wallpaper[data-tiles="dark"] :is(.tile')
        self.assertGreaterEqual(float(re.search(r"max\(([\d.]+),", body).group(1)), 0.5)

    def test_light_tile_text_is_dark_enough(self):
        body = rule('html[data-tiles="light"] :is(.tile, .widget:not(.t-device), .scene')
        haze = re.search(r"--haze: #([0-9a-f]{6})", body).group(1)
        r, g, b = (int(haze[i:i + 2], 16) for i in (0, 2, 4))
        self.assertLess(0.299 * r + 0.587 * g + 0.114 * b, 80)       # secondary text readable on white glass

    def test_text_on_a_wallpaper_gets_a_shadow(self):
        self.assertIn("text-shadow", rule('html.has-wallpaper[data-tone="dark"] :is(.topbar-title'))
        self.assertIn("text-shadow", rule('html.has-wallpaper[data-tone="light"] :is(.topbar-title'))


if __name__ == "__main__":
    unittest.main()
