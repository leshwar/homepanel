"""Unit tests: the photo library (validation, screen-ready processing, safety) and frame settings."""
import asyncio
import io
import os
import shutil
import tempfile
import time
import unittest

from PIL import Image

from app.core import photos as photos_mod
from app.core.adapter import AdapterError
from app.core.photos import PhotoError, PhotoLibrary, is_night
from app.core.service import HomeService


def jpeg_bytes(w=4000, h=3000, orientation=None, gps=False) -> bytes:
    img = Image.new("RGB", (w, h), (200, 80, 40))
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation             # Orientation tag
    if gps:
        exif[0x8825] = {1: "N", 2: (47.0, 36.0, 0.0)}   # GPSInfo
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


class PhotoLibraryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.lib = PhotoLibrary(os.path.join(self.dir, "photos"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_upload_is_made_screen_ready(self):
        p = self.lib.add(jpeg_bytes(orientation=6, gps=True), "IMG_1.jpg")   # 6 = rotated 90° by the camera
        path, media_type = self.lib.path(p["id"])
        self.assertEqual(media_type, "image/jpeg")
        img = Image.open(path)
        self.assertEqual(img.size, (1920, 2560))          # upright (portrait) and shrunk to 2560 on the long side
        self.assertEqual(len(img.getexif()), 0)           # no metadata kept, so no GPS location

    def test_png_with_transparency_stays_png(self):
        out = io.BytesIO()
        Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(out, "PNG")
        p = self.lib.add(out.getvalue())
        self.assertTrue(p["id"].endswith(".png"))

    def test_same_photo_twice_is_stored_once(self):
        data = jpeg_bytes(800, 600)
        self.assertEqual(self.lib.add(data)["id"], self.lib.add(data)["id"])
        self.assertEqual(len(self.lib.list()), 1)

    def test_rejects_non_images_and_empty_files(self):
        with self.assertRaises(PhotoError):
            self.lib.add(b"hello, not a photo")
        with self.assertRaises(PhotoError):
            self.lib.add(b"")

    def test_rejects_huge_uploads(self):
        old = photos_mod.MAX_UPLOAD_BYTES
        photos_mod.MAX_UPLOAD_BYTES = 1000
        try:
            with self.assertRaises(PhotoError):
                self.lib.add(jpeg_bytes(800, 600))
        finally:
            photos_mod.MAX_UPLOAD_BYTES = old

    def test_only_photos_inside_the_folder_can_be_read(self):
        secret = os.path.join(self.dir, "secret.jpg")
        open(secret, "wb").write(jpeg_bytes(10, 10))
        for bad in ("../secret.jpg", "..%2Fsecret.jpg", ".hidden.jpg", "notes.txt", "", "a/b.jpg"):
            with self.subTest(bad=bad), self.assertRaises(KeyError):
                self.lib.path(bad)

    def test_delete(self):
        p = self.lib.add(jpeg_bytes(100, 100))
        self.lib.delete(p["id"])
        self.assertEqual(self.lib.list(), [])
        with self.assertRaises(KeyError):
            self.lib.delete(p["id"])

    def test_demo_photos(self):
        self.assertEqual(self.lib.seed_demo(3), 3)
        self.assertEqual(len(self.lib.list()), 3)

    def test_is_night(self):
        def at(hour):
            return time.mktime(time.struct_time((2026, 11, 3, hour, 0, 0, 0, 0, -1)))
        self.assertTrue(is_night(at(23)))
        self.assertTrue(is_night(at(3)))
        self.assertFalse(is_night(at(12)))


class FrameSettings(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_defaults_and_validation(self):
        s = self.svc.store.settings
        self.assertEqual((s["idle_screen"], s["frame_seconds"], s["frame_shuffle"]), ("clock", 15, True))
        out = self.svc.update_settings({"idle_screen": "photos", "frame_seconds": 1, "frame_clock": "false"})
        self.assertEqual((out["idle_screen"], out["frame_seconds"], out["frame_clock"]), ("photos", 5, False))
        with self.assertRaises(AdapterError):
            self.svc.update_settings({"idle_screen": "video"})
        with self.assertRaises(AdapterError):
            self.svc.update_settings({"frame_seconds": "soon"})

    def test_demo_mode_has_photos(self):
        demo = HomeService(os.path.join(self.dir, "demo"), demo=True)
        asyncio.run(self._start_stop(demo))
        self.assertGreater(len(demo.photos.list()), 0)

    @staticmethod
    async def _start_stop(svc):
        await svc.start()
        await svc.stop()


if __name__ == "__main__":
    unittest.main()
