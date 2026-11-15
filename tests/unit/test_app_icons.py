"""App pictures on TV panels: only ever fetched from the TV itself, only real bitmaps,
and the panel learns a token, never the TV's address."""
import asyncio
import shutil
import tempfile
import unittest

from app.adapters.lg_tv import icon_url
from app.core import net
from app.core.service import HomeService

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class IconAddress(unittest.TestCase):
    def test_pinned_to_the_tv_whatever_host_it_names(self):
        app = {"icon": "http://lgsmarttv.lan:3000/resources/ab12/icon.png?x=1"}
        self.assertEqual(icon_url(app, "192.168.1.40"), "http://192.168.1.40:3000/resources/ab12/icon.png?x=1")
        self.assertEqual(icon_url({"icon": "https://evil.example/steal.png"}, "192.168.1.40"),
                         "https://192.168.1.40/steal.png")            # still only the TV is asked

    def test_prefers_the_large_picture_and_skips_what_cannot_be_fetched(self):
        app = {"largeIcon": "https://tv:3001/resources/big.png", "icon": "http://tv:3000/resources/small.png"}
        self.assertEqual(icon_url(app, "10.0.0.7"), "https://10.0.0.7:3001/resources/big.png")
        app = {"largeIcon": "/usr/palm/applications/x/large.png", "icon": "http://tv:3000/resources/small.png"}
        self.assertEqual(icon_url(app, "10.0.0.7"), "http://10.0.0.7:3000/resources/small.png")
        for nothing in ({}, {"icon": "/usr/palm/x.png"}, {"icon": None}, {"icon": "ftp://tv/x.png"}, {"icon": "http://[bad/x.png"}):
            self.assertIsNone(icon_url(nothing, "10.0.0.7"), nothing)
        self.assertIsNone(icon_url({"icon": "http://tv:3000/x.png"}, ""))    # the TV's address isn't known


class PictureKinds(unittest.TestCase):
    def test_judged_by_content(self):
        self.assertEqual(net.image_type(PNG), "image/png")
        self.assertEqual(net.image_type(b"\xff\xd8\xff\xe0rest"), "image/jpeg")
        self.assertEqual(net.image_type(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertEqual(net.image_type(b"GIF89a..."), "image/gif")
        for not_a_bitmap in (b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", b"<html>", b"", b"RIFF1234WAVE"):
            self.assertIsNone(net.image_type(not_a_bitmap))


class ServiceAppIcons(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()
        self.tv = self.svc.get("lr-tv")
        self.tv.meta["apps"] = [dict(a) for a in self.tv.meta["apps"]]     # our own copies: the demo's list is shared
        self.adapter = self.svc._adapter_for(self.tv)
        self.calls = []

        async def app_icon(device, app_id):
            self.calls.append(app_id)
            return ("image/png", PNG) if app_id == "netflix" else None
        self.adapter.app_icon = app_icon

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def mark(self, app_id, token):
        for a in self.tv.meta["apps"]:
            if a["id"] == app_id:
                a["icon"] = token

    async def test_only_apps_the_device_marked_and_fetched_once(self):
        with self.assertRaises(KeyError):                       # no token: the device has no picture for it
            await self.svc.app_icon("lr-tv", "netflix")
        self.assertEqual(self.calls, [])
        self.mark("netflix", "t1")
        self.assertEqual(await self.svc.app_icon("lr-tv", "netflix"), ("image/png", PNG))
        await self.svc.app_icon("lr-tv", "netflix")
        self.assertEqual(self.calls, ["netflix"])               # kept: the TV isn't asked again
        self.mark("netflix", "t2")                              # the picture changed on the TV
        await self.svc.app_icon("lr-tv", "netflix")
        self.assertEqual(self.calls, ["netflix", "netflix"])

    async def test_unavailable_picture_is_not_found_and_not_remembered(self):
        self.mark("youtube", "t1")
        for _ in range(2):
            with self.assertRaises(KeyError):
                await self.svc.app_icon("lr-tv", "youtube")
        self.assertEqual(self.calls, ["youtube", "youtube"])    # asked again next time: the TV may be back
        with self.assertRaises(KeyError):
            await self.svc.app_icon("lr-tv", "not-an-app")
        with self.assertRaises(KeyError):
            await self.svc.app_icon("no-such-device", "netflix")

    async def test_the_panel_never_sees_where_the_tv_keeps_it(self):
        self.mark("netflix", "t1")
        public = self.svc.public_device(self.tv)
        self.assertNotIn("http", str(public["meta"]["apps"]))
        self.assertEqual(await asyncio.wait_for(self.adapter.__class__.app_icon(self.adapter, self.tv, "netflix"), 1), None)   # other brands: none


if __name__ == "__main__":
    unittest.main()
