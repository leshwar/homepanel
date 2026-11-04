"""Service-layer tests: middleware pipeline, commands, scenes, persistence.

Run:  python -m unittest discover -s tests -v      (or: make test / pytest)
"""
import asyncio
import os
import shutil
import tempfile
import unittest

from app.core.adapter import (Action, AdapterError, Cap, DeviceAdapter, Field,
                              Found, Kind, register)
from app.core.service import HomeService


# A fake brand, registered exactly like a real adapter. Proves a new brand plugs in
# without touching the API or service layers.
@register
class FakeAdapter(DeviceAdapter):
    id = "fake_test"
    name = "Fake brand"
    kinds = (Kind.PLUG,)
    hidden = True
    poll_interval = 3600
    manual_fields = [Field("ip", "IP", required=True)]
    calls: list = []
    fail_next = 0

    async def refresh(self, device):
        return {"on": device.state.get("on", False)}

    async def command(self, device, action, value=None):
        if FakeAdapter.fail_next:
            FakeAdapter.fail_next -= 1
            raise OSError("network blip")
        FakeAdapter.calls.append((device.name, action, value))
        return {"on": value} if action == Action.POWER else {}

    def from_manual(self, values):
        if not values.get("ip"):
            raise AdapterError("IP address is required.")
        return Found(adapter=self.id, uid=values["ip"], name=values.get("name", "Fake"), kind=Kind.PLUG,
                     caps=[Cap.POWER], config={"ip": values["ip"]})


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()
        FakeAdapter.calls = []
        FakeAdapter.fail_next = 0

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_demo_seeded(self):
        self.assertGreaterEqual(len(self.svc.store.devices), 10)
        self.assertTrue(self.svc.store.scenes)

    async def test_toggle_goes_through_middleware(self):
        d = self.svc.get("lr-lamp")
        d.state["on"] = True
        out = await self.svc.command("lr-lamp", Action.TOGGLE)
        self.assertFalse(out["state"]["on"])

    async def test_unsupported_action_rejected(self):
        with self.assertRaises(AdapterError):
            await self.svc.command("lr-plug", Action.BRIGHTNESS, 50)    # plugs have no brightness
        with self.assertRaises(AdapterError):
            await self.svc.command("lr-plug", "explode")
        with self.assertRaises(AdapterError):
            await self.svc.command("lr-tv", Action.KEY, "NOT_A_KEY")

    async def test_values_are_clamped(self):
        out = await self.svc.command("lr-lamp", Action.BRIGHTNESS, 250)
        self.assertEqual(out["state"]["brightness"], 100)
        out = await self.svc.command("lr-strip", Action.COLOR, "#ff8000")
        self.assertEqual(out["state"]["color"], {"r": 255, "g": 128, "b": 0})

    async def test_all_off_respects_keep_on(self):
        for did in list(self.svc.store.devices):
            await self.svc.refresh(did)
        self.svc.update_device("kt-fridge", {"keep_on": True})
        await self.svc.command("kt-fridge", Action.POWER, True)
        await self.svc.all_off()
        self.assertTrue(self.svc.get("kt-fridge").state["on"])
        self.assertFalse(self.svc.get("lr-ceiling").state["on"])

    async def test_all_off_for_one_room_and_for_devices_without_a_room(self):
        for did in ("lr-lamp", "kt-kettle", "bd-fan"):
            await self.svc.command(did, Action.POWER, True)
        self.svc.update_device("bd-fan", {"room": ""})            # shows under "Other" on the panel
        self.assertEqual(await self.svc.all_off(""), 1)            # "" = devices without a room
        self.assertFalse(self.svc.get("bd-fan").state["on"])
        self.assertTrue(self.svc.get("lr-lamp").state["on"])
        self.assertEqual(await self.svc.all_off("Kitchen"), 2)       # kettle and fridge
        self.assertFalse(self.svc.get("kt-kettle").state["on"])
        self.assertTrue(self.svc.get("lr-lamp").state["on"])

    async def test_scene_capture_and_run(self):
        await self.svc.command("bd-lamp", Action.BRIGHTNESS, 33)
        scene = self.svc.save_scene({"name": "Reading", "icon": "sun", "capture": ["bd-lamp"]})
        self.assertIn({"device_id": "bd-lamp", "action": "brightness", "value": 33}, scene["actions"])
        await self.svc.command("bd-lamp", Action.POWER, False)
        res = await self.svc.run_scene(scene["id"])
        self.assertEqual(res["failed"], [])
        self.assertTrue(self.svc.get("bd-lamp").state["on"])

    async def test_add_manual_device_and_retry(self):
        d = await self.svc.add_device("fake_test", manual={"ip": "10.0.0.9", "name": "Desk"}, room="Office")
        self.assertIn("Office", self.svc.store.rooms)
        FakeAdapter.fail_next = 1                       # first attempt fails, retry succeeds
        out = await self.svc.command(d["id"], Action.POWER, True)
        self.assertTrue(out["state"]["on"])
        self.assertEqual(FakeAdapter.calls[-1], ("Desk", "power", True))
        self.assertNotIn("config", out)                 # secrets never leave the service
        with self.assertRaises(AdapterError):           # duplicates are refused
            await self.svc.add_device("fake_test", manual={"ip": "10.0.0.9"})

    async def test_persistence(self):
        await self.svc.add_device("fake_test", manual={"ip": "10.0.0.7", "name": "Lamp"})
        self.svc.set_rooms(["Den", "Den", " ", "Porch"])
        again = HomeService(self.dir, demo=True)
        self.assertEqual(again.store.rooms, ["Den", "Porch"])
        self.assertTrue(any(d.name == "Lamp" for d in again.store.devices.values()))
        self.assertEqual(oct(os.stat(again.store.path).st_mode & 0o777), "0o600")

    async def test_custom_middleware(self):
        seen = []

        async def audit(ctx, call_next):
            seen.append(ctx.action)
            return await call_next(ctx)

        self.svc.use(audit)
        await self.svc.command("lr-plug", Action.TOGGLE)
        self.assertEqual(seen, ["power"])               # runs after normalize: toggle -> power

    async def test_events_published(self):
        q = self.svc.subscribe()
        await self.svc.command("lr-plug", Action.POWER, False)
        ev = await asyncio.wait_for(q.get(), 1)
        self.assertEqual(ev["type"], "device")
        self.assertEqual(ev["device"]["id"], "lr-plug")

    async def test_display_settings_defaults_and_validation(self):
        s = self.svc.store.settings
        self.assertEqual((s["background"], s["glass_transparency"], s["glass_effect"]), ("ocean", 45, True))
        out = self.svc.update_settings({"glass_transparency": "150", "glass_effect": "false", "background": "aurora"})
        self.assertEqual((out["glass_transparency"], out["glass_effect"], out["background"]), (100, False, "aurora"))
        self.assertEqual(self.svc.update_settings({"glass_transparency": -5})["glass_transparency"], 0)
        with self.assertRaises(AdapterError):
            self.svc.update_settings({"background": "neon"})
        with self.assertRaises(AdapterError):
            self.svc.update_settings({"glass_transparency": "lots"})

    async def test_clock_face_default_and_validation(self):
        self.assertEqual(self.svc.store.settings["clock_face"], "digital")
        for face in ("digital", "analog", "words", "date", "night"):
            self.assertEqual(self.svc.update_settings({"clock_face": face})["clock_face"], face)
        with self.assertRaises(AdapterError) as cm:
            self.svc.update_settings({"clock_face": "sundial"})
        self.assertIn("Clock face", str(cm.exception))
        self.assertEqual(self.svc.store.settings["clock_face"], "night")   # bad value didn't stick

    async def test_account_password_kept_when_blank(self):
        self.svc.set_account("govee", {"api_key": "secret-1"})
        self.svc.set_account("govee", {"api_key": ""})
        self.assertEqual(self.svc.store.accounts["govee"]["api_key"], "secret-1")
        self.assertEqual(self.svc.account_public("govee")["api_key"], "••••••")


if __name__ == "__main__":
    unittest.main()
