"""The TV pointer (Magic Remote–style touchpad): validation in the service, and the LG
adapter's calls into aiowebostv (faked, so no TV is needed)."""
import asyncio
import shutil
import tempfile
import unittest
from unittest import mock

from app.adapters import lg_tv
from app.adapters.lg_tv import LGTVAdapter
from app.core.adapter import Action, AdapterError, Cap, Device, Key, Kind
from app.core.service import HomeService, normalize_pointer


class NormalizePointer(unittest.TestCase):
    def test_move(self):
        self.assertEqual(normalize_pointer({"dx": 12.4, "dy": "-3"}), {"dx": 12, "dy": -3})
        self.assertEqual(normalize_pointer({"dy": 5}), {"dx": 0, "dy": 5})

    def test_moves_are_clamped(self):
        self.assertEqual(normalize_pointer({"dx": 5000, "dy": -5000}), {"dx": 400, "dy": -400})
        self.assertEqual(normalize_pointer({"scroll": -9999}), {"scroll": -400})

    def test_click_and_scroll(self):
        self.assertEqual(normalize_pointer({"click": True}), {"click": True})
        self.assertEqual(normalize_pointer({"click": True, "dx": 3}), {"click": True})   # one thing per message
        self.assertEqual(normalize_pointer({"scroll": 40}), {"scroll": 40})

    def test_bad_values_have_plain_errors(self):
        for bad in (None, 5, "left", [], {}, {"click": False}, {"dx": "far"}, {"scroll": None}):
            with self.subTest(bad=bad), self.assertRaises(AdapterError):
                normalize_pointer(bad)

    def test_vocabulary(self):
        self.assertIn(Action.POINTER, Action.ALL)
        self.assertEqual(Action.REQUIRES[Action.POINTER], Cap.POINTER)
        self.assertIn(Action.POINTER, Action.QUIET)
        for k in ("EXIT", "CHANNEL_LIST", "INFO", "0", "9"):
            self.assertIn(k, Key.ALL)


class PointerThroughTheService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_pointer_needs_the_capability(self):
        # the demo "Samsung TV" has no pointer, the demo "LG TV" has one
        with self.assertRaisesRegex(AdapterError, "can't do 'pointer'"):
            await self.svc.command("lr-tv", "pointer", {"dx": 1, "dy": 1})
        await self.svc.command("bd-tv", "pointer", {"dx": 1, "dy": 1})

    async def test_pointer_is_quiet(self):
        q = self.svc.subscribe()
        with mock.patch.object(self.svc, "refresh", mock.AsyncMock()) as refresh:
            await asyncio.sleep(0.5)            # let the start-up polls of every device go by
            refresh.reset_mock()
            await self.svc.command("bd-tv", "pointer", {"click": True})
            self.assertTrue(q.empty())          # no live event for every pointer move
            await asyncio.sleep(1.7)            # other commands re-read the device after 1.5 s
            refresh.assert_not_called()         # pointer moves don't
            await self.svc.command("bd-tv", "mute", True)
            self.assertFalse(q.empty())

    async def test_bad_pointer_value_is_rejected(self):
        with self.assertRaises(AdapterError):
            await self.svc.command("bd-tv", "pointer", "up")


class FakeWebOs:
    """Stands in for aiowebostv.WebOsClient."""
    def __init__(self):
        self.calls = []

    def is_connected(self):
        return True

    async def move(self, dx, dy, down=0):
        self.calls.append(("move", dx, dy))

    async def click(self):
        self.calls.append(("click",))

    async def scroll(self, dx, dy):
        self.calls.append(("scroll", dx, dy))

    async def button(self, name):
        self.calls.append(("button", name))


class LGPointer(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = LGTVAdapter({}, tempfile.gettempdir())
        self.tv = Device(id="tv1", adapter="lg_tv", name="LG TV", kind=Kind.TV, caps=list(lg_tv.CAPS),
                         config={"ip": "10.0.0.9", "client_key": "k"}, state={"on": True})
        self.client = FakeWebOs()
        self.adapter._clients["tv1"] = self.client

    async def test_move_click_scroll(self):
        await self.adapter.command(self.tv, Action.POINTER, {"dx": 10, "dy": -4})
        await self.adapter.command(self.tv, Action.POINTER, {"click": True})
        await self.adapter.command(self.tv, Action.POINTER, {"scroll": 30})
        self.assertEqual(self.client.calls, [("move", 10, -4), ("click",), ("scroll", 0, 30)])

    async def test_new_keys(self):
        await self.adapter.command(self.tv, Action.KEY, Key.EXIT)
        await self.adapter.command(self.tv, Action.KEY, Key.CHANNEL_LIST)
        await self.adapter.command(self.tv, Action.KEY, "7")
        self.assertEqual(self.client.calls, [("button", "EXIT"), ("button", "LIST"), ("button", "7")])

    def test_lg_tvs_have_a_pointer(self):
        self.assertIn(Cap.POINTER, lg_tv.CAPS)

    async def test_tvs_added_earlier_gain_the_pointer(self):
        self.tv.caps = [c for c in self.tv.caps if c != Cap.POINTER]
        self.client.current_app_id = "youtube"
        with mock.patch.object(lg_tv, "port_open", mock.AsyncMock(return_value=True)), \
             mock.patch.object(self.adapter, "_learn_mac", mock.AsyncMock()):
            await self.adapter.refresh(self.tv)
        self.assertIn(Cap.POINTER, self.tv.caps)


if __name__ == "__main__":
    unittest.main()
