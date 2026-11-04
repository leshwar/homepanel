"""Unit tests: "Search all brands" (HomeService.discover_all). No network: demo mode and fake brands."""
import asyncio
import shutil
import tempfile
import unittest

from app.core.adapter import AdapterError, Cap, DeviceAdapter, Field, Found, Kind
from app.core.service import HomeService


# Fake brands are added straight into the running service (not @register), so they
# don't show up in other tests.
class _Base(DeviceAdapter):
    async def refresh(self, device):
        return {"on": False}

    async def command(self, device, action, value=None):
        return {}


class _Plugs(_Base):
    id, name, kinds, hidden = "t_plugs", "Test plugs", (Kind.PLUG,), True

    async def discover(self, timeout=6.0):
        return [Found(adapter=self.id, uid="p1", name="Desk plug", kind=Kind.PLUG, caps=[Cap.POWER],
                      config={"ip": "10.0.0.9"}, detail="10.0.0.9")]

    async def setup(self, device):
        pass


class _Broken(_Base):
    id, name, kinds, hidden = "t_broken", "Broken brand", (Kind.LIGHT,), True

    async def discover(self, timeout=6.0):
        raise OSError("network unreachable")


class _Slow(_Base):
    id, name, kinds, hidden = "t_slow", "Slow brand", (Kind.LIGHT,), True

    async def discover(self, timeout=6.0):
        raise asyncio.TimeoutError


class _NeedsAccount(_Base):
    id, name, kinds, hidden = "t_cloud", "Cloud brand", (Kind.LIGHT,), True
    account_fields = [Field("api_key", "API key", type="password", required=True)]
    searched = False

    async def discover(self, timeout=6.0):
        _NeedsAccount.searched = True
        return []


class _Manual(_Base):
    id, name, kinds, hidden, can_discover = "t_manual", "Manual only", (Kind.PLUG,), True, False


class DiscoverAllTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()
        for cls in (_Plugs, _Broken, _Slow, _NeedsAccount, _Manual):
            self.svc.adapters[cls.id] = cls({}, self.dir)
        _NeedsAccount.searched = False

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_searches_every_brand_and_marks_added(self):
        r = await self.svc.discover_all()
        self.assertIn("demo", r["searched"])
        self.assertIn("t_plugs", r["searched"])
        plug = next(f for f in r["found"] if f["uid"] == "p1")
        self.assertEqual((plug["adapter"], plug["adapter_name"], plug["added"]), ("t_plugs", "Test plugs", False))
        self.assertNotIn("config", plug)                       # secrets never leave the server
        demo = [f for f in r["found"] if f["adapter"] == "demo"]
        self.assertTrue(demo and all(f["added"] for f in demo))  # demo devices are already on the panel
        self.assertFalse(r["found"][0]["added"])                 # new devices are listed first

    async def test_one_broken_brand_does_not_stop_the_others(self):
        r = await self.svc.discover_all()
        failed = {f["adapter"]: f["error"] for f in r["failed"]}
        self.assertEqual(set(failed), {"t_broken", "t_slow"})
        self.assertIn("too long", failed["t_slow"])
        self.assertTrue(any(f["uid"] == "p1" for f in r["found"]))

    async def test_brands_needing_an_account_are_listed_not_searched(self):
        r = await self.svc.discover_all()
        self.assertEqual(r["needs_account"], [{"adapter": "t_cloud", "adapter_name": "Cloud brand"}])
        self.assertFalse(_NeedsAccount.searched)
        self.assertNotIn("t_manual", r["searched"])           # can't discover: skipped quietly
        self.svc.store.accounts["t_cloud"] = {"api_key": "x"}
        r = await self.svc.discover_all()
        self.assertIn("t_cloud", r["searched"])
        self.assertTrue(_NeedsAccount.searched)

    async def test_result_can_be_added(self):
        await self.svc.discover_all()
        d = await self.svc.add_device("t_plugs", uid="p1", room="Office")
        self.assertEqual((d["name"], d["room"]), ("Desk plug", "Office"))
        r = await self.svc.discover_all()
        self.assertTrue(next(f for f in r["found"] if f["uid"] == "p1")["added"])

    async def test_real_mode_skips_pretend_brands(self):
        svc = HomeService(tempfile.mkdtemp(), demo=False)
        svc.adapters = {"t_plugs": _Plugs({}, self.dir)}       # hidden = pretend: never searched for real
        ready, _ = svc._searchable()
        self.assertEqual(ready, [])


class _TVs(_Base):
    """A brand that reports a different uid depending on how it found the device (the bug)."""
    id, name, kinds, hidden = "t_tvs", "Test TVs", (Kind.TV,), True
    results: list = []

    async def discover(self, timeout=6.0):
        return list(_TVs.results)

    def from_manual(self, values):
        return Found(adapter=self.id, uid=values["uid"], name="Manual", kind=Kind.TV, config={"ip": values["ip"]})

    async def setup(self, device):
        pass


def _tv(uid, ip, mac=""):
    return Found(adapter="t_tvs", uid=uid, name="TV", kind=Kind.TV, config={"ip": ip, "mac": mac})


class SameAddressSafetyNet(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()
        self.svc.adapters["t_tvs"] = _TVs({}, self.dir)
        _TVs.results = [_tv("uuid:1470", "10.0.0.13")]
        await self.svc.discover("t_tvs")
        await self.svc.add_device("t_tvs", uid="uuid:1470")

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def added(self, r, uid):
        return next(f for f in r["found"] if f["uid"] == uid)["added"]

    async def test_same_brand_and_address_counts_as_added(self):
        _TVs.results = [_tv("AA:BB:CC:DD:EE:13", "10.0.0.13")]     # same TV, found the other way
        r = await self.svc.discover_all()
        self.assertTrue(self.added(r, "AA:BB:CC:DD:EE:13"))
        with self.assertRaisesRegex(AdapterError, "Already added"):
            await self.svc.add_device("t_tvs", uid="AA:BB:CC:DD:EE:13")
        self.assertEqual(sum(d.adapter == "t_tvs" for d in self.svc.store.devices.values()), 1)
        self.assertTrue(all("config" not in f and "aliases" not in f for f in r["found"]))

    async def test_aliases_match_and_are_saved(self):
        f = _tv("AA:BB:CC:DD:EE:14", "10.0.0.14")
        f.aliases = ["uuid:other"]
        _TVs.results = [f]
        await self.svc.discover("t_tvs")
        d = await self.svc.add_device("t_tvs", uid="AA:BB:CC:DD:EE:14")
        self.assertEqual(self.svc.store.devices[d["id"]].config["_aliases"], ["uuid:other"])
        _TVs.results = [_tv("uuid:other", "10.0.0.99")]               # found by its old id, new address
        self.assertTrue((await self.svc.discover("t_tvs"))[0]["added"])

    async def test_different_address_or_brand_is_new(self):
        _TVs.results = [_tv("AA:BB:CC:DD:EE:20", "10.0.0.20")]
        self.assertFalse((await self.svc.discover("t_tvs"))[0]["added"])
        self.svc.adapters["t_plugs"] = _Plugs({}, self.dir)            # _Plugs is at 10.0.0.9 …
        _TVs.results = [_tv("AA:BB:CC:DD:EE:09", "10.0.0.9")]         # … another brand there doesn't count
        await self.svc.discover("t_plugs")
        await self.svc.add_device("t_plugs", uid="p1")
        self.assertFalse((await self.svc.discover("t_tvs"))[0]["added"])

    async def test_new_device_on_a_reused_address_is_new(self):
        self.svc.store.devices[next(d.id for d in self.svc.store.devices.values()
                                    if d.adapter == "t_tvs")].config["mac"] = "AA:BB:CC:DD:EE:13"
        _TVs.results = [_tv("AA:BB:CC:DD:EE:77", "10.0.0.13", mac="aa:bb:cc:dd:ee:77")]   # MACs differ
        self.assertFalse((await self.svc.discover("t_tvs"))[0]["added"])

    async def test_shared_address_is_not_used(self):
        _TVs.results = [_tv("ch-1", "10.0.0.13"), _tv("ch-2", "10.0.0.13")]   # a hub: many devices, one address
        r = await self.svc.discover("t_tvs")
        self.assertEqual([f["added"] for f in r], [False, False])
        await self.svc.add_device("t_tvs", uid="ch-1")                         # can still be added

    async def test_manual_add_at_the_same_address_is_allowed(self):
        await self.svc.add_device("t_tvs", manual={"uid": "second-channel", "ip": "10.0.0.13"})
        with self.assertRaisesRegex(AdapterError, "Already added"):
            await self.svc.add_device("t_tvs", manual={"uid": "uuid:1470", "ip": "10.0.0.50"})


if __name__ == "__main__":
    unittest.main()
