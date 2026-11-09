"""Private photo-source policy with fake transport, no sockets."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.adapters.immich_photos import PhotoSource, server_url
from app.core.photos import PhotoError
from app.core.profiles import Viewer, current_viewer
from app.core.remote_photos import RemotePhotos, screen_preview

ALBUM = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PHOTO = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


class PhotoPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owner = {"id": "owner", "name": "Owner", "role": "admin", "devices": "all"}
        self.store = SimpleNamespace(accounts={}, profiles=[self.owner], save=lambda: None)
        self.context = current_viewer.set(Viewer(profile=self.owner))
        self.source = RemotePhotos(self.store, lambda: None)
        out = io.BytesIO()
        Image.new("RGB", (40, 30), "red").save(out, "JPEG")
        self.fake = SimpleNamespace(url="http://photo.local:2283", verify=lambda: {"major": 2, "minor": 0, "patch": 0},
            albums=lambda: [{"id": ALBUM, "name": "Display"}],
            candidates=lambda albums, deadline: [{"id": PHOTO, "updated": "one"}, {"id": OTHER, "updated": "one"}],
            validate=lambda *args: "one", preview=lambda *args: out.getvalue())
        self.patch = patch("app.core.remote_photos.photo_source", return_value=self.fake)
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop()
        current_viewer.reset(self.context)

    async def configure(self):
        await self.source.connect({"url": self.fake.url, "key": "fixture-key"})
        await self.source.select({"albums": [ALBUM], "profiles": ["owner"], "seconds": 30})

    async def test_explicit_source_and_profile_required_secrets_not_public_and_no_repeat(self):
        await self.source.connect({"url": self.fake.url, "key": "fixture-key"})
        self.assertFalse(self.source.status()["ready"])
        self.assertNotIn("fixture-key", json.dumps(self.source.management()))
        self.assertNotIn(self.fake.url, json.dumps(self.source.status()))
        with self.assertRaises(PhotoError):
            await self.source.next()
        await self.source.select({"albums": [ALBUM], "profiles": ["owner"], "seconds": 30})
        first = await self.source.next()
        self.source._attempt.clear()
        second = await self.source.next()
        self.assertNotEqual(first[1], second[1])
        self.assertTrue(first[0].startswith(b"\xff\xd8"))
        with self.assertRaises(PhotoError):
            await self.source.next()
        self.source.disconnect()
        self.assertFalse(self.source.status()["ready"])
        self.assertEqual(len(self.source._cache), 0)
        with self.assertRaises(KeyError):
            await self.source.next()

    async def test_profile_revocation_and_source_changes_reject_in_flight_content(self):
        await self.configure()
        def changed(*args):
            self.store.accounts["photo_library"] = {"generation": "changed"}
            return "one"
        self.fake.validate = changed
        with self.assertRaises(PhotoError):
            await self.source.next()
        self.assertEqual(len(self.source._cache), 0)
        await self.configure()
        self.store.profiles = []
        with self.assertRaises(KeyError):
            await self.source.next()

    async def test_empty_invalid_selection_and_bounds_are_not_silent(self):
        await self.configure()
        for values in ({"albums": [], "profiles": ["owner"]},
                       {"albums": [ALBUM], "profiles": []},
                       {"albums": [ALBUM], "profiles": ["missing"]},
                       {"albums": [ALBUM], "profiles": ["owner"], "seconds": 1}):
            with self.subTest(values=values), self.assertRaises(PhotoError):
                await self.source.select(values)
        self.fake.candidates = lambda *args: []
        with self.assertRaisesRegex(PhotoError, "No eligible"):
            await self.source.next()


class PhotoTransportPolicyTests(unittest.TestCase):
    def test_urls_and_privacy_contract(self):
        self.assertEqual(server_url("http://laptop.local:2283/api/"), "http://laptop.local:2283")
        self.assertEqual(server_url("https://photos.example/immich"), "https://photos.example/immich")
        for url in ("file:///etc/passwd", "ftp://host", "http://u:p@host", "http://host/?key=value",
                    "http://host/#x", "http://host/../private", "http://host/%2e%2e", "http://host:99999", "http://host\n"):
            with self.subTest(url=url), self.assertRaises(PhotoError):
                server_url(url)
        valid = {"type": "IMAGE", "visibility": "timeline", "isTrashed": False, "isOffline": False}
        self.assertTrue(PhotoSource.eligible(valid))
        for changes in ({"type": "VIDEO"}, {"visibility": "archive"}, {"visibility": "hidden"},
                        {"visibility": "locked"}, {"isTrashed": True}, {"isOffline": True}):
            self.assertFalse(PhotoSource.eligible({**valid, **changes}))
        with self.assertRaises(PhotoError):
            PhotoSource.eligible({"type": "IMAGE"})

    def test_previews_are_bounded_and_metadata_free(self):
        out = io.BytesIO()
        image = Image.new("RGB", (1800, 900), "blue")
        exif = Image.Exif(); exif[270] = "private fixture metadata"
        image.save(out, "JPEG", exif=exif)
        result = screen_preview(out.getvalue())
        with Image.open(io.BytesIO(result)) as preview:
            self.assertLessEqual(max(preview.size), 1280)
            self.assertEqual(dict(preview.getexif()), {})
        self.assertNotIn(b"private fixture metadata", result)
        with self.assertRaises(PhotoError):
            screen_preview(b"not an image")
