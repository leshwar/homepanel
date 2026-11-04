"""Unit tests for app/main.py helpers."""
import unittest

from app.main import ui_cache_header


class CachePolicy(unittest.TestCase):
    def test_ui_files_are_always_revalidated(self):
        for path in ("/", "/index.html", "/app.css", "/js/app.js", "/js/glass.js"):
            with self.subTest(path=path):
                self.assertEqual(ui_cache_header(path), "no-cache")

    def test_api_and_images_are_left_alone(self):
        for path in ("/api/v1/state", "/api/v1/photos/abc.jpg/image", "/favicon.png"):
            with self.subTest(path=path):
                self.assertIsNone(ui_cache_header(path))


if __name__ == "__main__":
    unittest.main()
