"""Unit tests: wallpapers (TIFF conversion, sizes, settings) and device pictures."""
import io
import os
import shutil
import tempfile
import unittest

from PIL import Image

from app.api.auth import LOCKED_OK, MEMBER_OK, _match
from app.core.adapter import AdapterError
from app.core.photos import DevicePictures, PhotoError, PhotoLibrary
from app.core.service import HomeService


def image_bytes(fmt="TIFF", size=(1600, 900), mode="RGB", color=(30, 40, 90, 255)) -> bytes:
    img = Image.new(mode, size, color[: len(mode)] if mode != "RGBA" else color)
    out = io.BytesIO()
    img.save(out, fmt)
    return out.getvalue()


def cutout_png(size=(900, 600)) -> bytes:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste((20, 30, 60, 255), (100, 100, 800, 500))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


class WallpaperLibraryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.lib = PhotoLibrary(os.path.join(self.dir, "wallpapers"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_tiff_becomes_jpeg_with_its_size(self):
        w = self.lib.add(image_bytes("TIFF", (1200, 675)), "Pasted 2026-11-06.tiff")
        self.assertTrue(w["id"].endswith(".jpg"))
        self.assertEqual((w["width"], w["height"]), (1200, 675))
        with Image.open(self.lib.path(w["id"])[0]) as img:
            self.assertEqual(img.format, "JPEG")
        self.assertEqual(self.lib.list()[0]["width"], 1200)            # sizes in the list too (orientation)

    def test_big_tiff_is_shrunk_for_the_screen(self):
        img = Image.new("RGB", (5000, 2500), (10, 10, 10))
        out = io.BytesIO()
        img.save(out, "TIFF", compression="tiff_lzw")
        data = out.getvalue()
        self.assertTrue(data.startswith(b"II*\x00"))
        w = self.lib.add(data)
        self.assertEqual(max(w["width"], w["height"]), 2560)

    def test_tiff_with_transparency_stays_png(self):
        img = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
        out = io.BytesIO()
        img.save(out, "TIFF")
        self.assertTrue(self.lib.add(out.getvalue())["id"].endswith(".png"))

    def test_opaque_rgba_png_becomes_jpeg(self):
        self.assertTrue(self.lib.add(image_bytes("PNG", mode="RGBA"))["id"].endswith(".jpg"))


class DevicePictureTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pics = DevicePictures(os.path.join(self.dir, "device-pictures"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_photo_is_made_small(self):
        name = self.pics.save("lr-tv", image_bytes("JPEG", (3000, 2000)))
        self.assertTrue(name.startswith("lr-tv-") and name.endswith(".jpg"))
        with Image.open(self.pics.path(name)[0]) as img:
            self.assertEqual(max(img.size), 512)

    def test_cutout_keeps_its_transparent_background(self):
        name = self.pics.save("lr-tv", cutout_png())
        self.assertTrue(name.endswith(".png"))
        with Image.open(self.pics.path(name)[0]) as img:
            self.assertEqual(img.getchannel("A").getextrema()[0], 0)

    def test_rejects_gifs_bad_ids_and_junk(self):
        gif = io.BytesIO()
        Image.new("P", (10, 10)).save(gif, "GIF")
        with self.assertRaises(PhotoError):
            self.pics.save("lr-tv", gif.getvalue())
        with self.assertRaises(PhotoError):
            self.pics.save("lr-tv", b"not a picture")
        with self.assertRaises(KeyError):
            self.pics.save("../etc", image_bytes("JPEG"))

    def test_remove(self):
        name = self.pics.save("lr-tv", image_bytes("JPEG"))
        self.pics.remove(name)
        with self.assertRaises(KeyError):
            self.pics.path(name)
        self.pics.remove("")                                          # nothing to do: no error


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_tile_style_setting(self):
        self.assertEqual(self.svc.store.settings["tile_style"], "auto")      # contrast with the background by default
        for style in ("light", "dark", "auto"):
            self.assertEqual(self.svc.update_settings({"tile_style": style})["tile_style"], style)
        with self.assertRaises(AdapterError):
            self.svc.update_settings({"tile_style": "neon"})
        self.assertEqual(self.svc.display_settings()["tile_style"], "auto")  # the sign-in screen uses it too

    async def test_demo_has_wallpapers_and_wallpaper_settings_are_checked(self):
        walls = self.svc.wallpapers.list()
        self.assertEqual(len(walls), 3)
        s = self.svc.update_settings({"background": "wallpaper", "wallpaper": walls[0]["id"],
                                      "wallpaper_every": 15, "wallpaper_dim": 200})
        self.assertEqual((s["background"], s["wallpaper"], s["wallpaper_every"], s["wallpaper_dim"]),
                         ("wallpaper", walls[0]["id"], 15, 80))           # darken is capped at 80 %
        for bad in ({"wallpaper": "nope.jpg"}, {"wallpaper": "../homepanel.json"}, {"wallpaper_every": 7}):
            with self.subTest(bad=bad), self.assertRaises(AdapterError):
                self.svc.update_settings(bad)
        self.assertEqual(self.svc.update_settings({"wallpaper": ""})["wallpaper"], "shuffle")

    async def test_deleting_the_shown_wallpaper_goes_back_to_shuffle(self):
        w = self.svc.wallpapers.list()[0]["id"]
        self.svc.update_settings({"wallpaper": w})
        self.svc.delete_wallpaper(w)
        self.assertEqual(self.svc.store.settings["wallpaper"], "shuffle")

    async def test_device_picture_set_shown_and_cleaned_up(self):
        d = await self.svc.set_device_picture("lr-tv", cutout_png())
        self.assertTrue(d["picture_url"].startswith("/api/v1/devices/lr-tv/picture?v=lr-tv-"))
        first = self.svc.store.devices["lr-tv"].picture
        await self.svc.set_device_picture("lr-tv", image_bytes("JPEG"))     # a new photo replaces the old file
        with self.assertRaises(KeyError):
            self.svc.device_pictures.path(first)
        path, media = self.svc.device_picture_path("lr-tv")
        self.assertEqual(media, "image/jpeg")
        d = await self.svc.clear_device_picture("lr-tv")
        self.assertEqual(d["picture_url"], "")
        self.assertFalse(os.path.exists(path))
        await self.svc.set_device_picture("lr-plug", image_bytes("JPEG"))
        path, _ = self.svc.device_picture_path("lr-plug")
        await self.svc.remove_device("lr-plug")                           # removing the device removes its photo
        self.assertFalse(os.path.exists(path))

    async def test_saved_picture_survives_a_restart(self):
        await self.svc.set_device_picture("lr-tv", image_bytes("JPEG"))
        await self.svc.stop()
        svc2 = HomeService(self.dir, demo=True)
        await svc2.start()
        try:
            self.assertTrue(svc2.public_device(svc2.store.devices["lr-tv"])["picture_url"])
        finally:
            await svc2.stop()
        await self.svc.start()


class AccessRuleTests(unittest.TestCase):
    def test_members_and_locked_panels_see_but_dont_change(self):
        for rules in (MEMBER_OK, LOCKED_OK):
            self.assertTrue(_match(rules, "GET", "/api/v1/wallpapers"))
            self.assertTrue(_match(rules, "GET", "/api/v1/wallpapers/abc.jpg/image"))
            self.assertFalse(_match(rules, "POST", "/api/v1/wallpapers"))
            self.assertFalse(_match(rules, "DELETE", "/api/v1/wallpapers/abc.jpg"))
        self.assertTrue(_match(MEMBER_OK, "GET", "/api/v1/devices/bd-lamp/picture"))
        self.assertFalse(_match(MEMBER_OK, "PUT", "/api/v1/devices/bd-lamp/picture"))
        self.assertFalse(_match(MEMBER_OK, "DELETE", "/api/v1/devices/bd-lamp/picture"))


if __name__ == "__main__":
    unittest.main()
