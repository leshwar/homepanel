"""Unit tests: robot vacuum commands in the service layer (demo vacuum, no network)."""
import asyncio
import shutil
import tempfile
import unittest

from app.core.adapter import Action, Activity, AdapterError, Clean
from app.core.service import HomeService


class VacuumServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_clean_pause_and_dock(self):
        d = await self.svc.command("lr-vacuum", Action.CLEAN, Clean.START)
        self.assertEqual((d["state"]["activity"], d["state"]["on"]), (Activity.CLEANING, True))
        d = await self.svc.command("lr-vacuum", Action.CLEAN, Clean.PAUSE)
        self.assertEqual(d["state"]["activity"], Activity.PAUSED)
        d = await self.svc.command("lr-vacuum", Action.DOCK)
        self.assertEqual(d["state"]["activity"], Activity.RETURNING)

    async def test_bad_values_and_wrong_devices_are_rejected(self):
        with self.assertRaises(AdapterError):
            await self.svc.command("lr-vacuum", Action.CLEAN, "turbo")
        with self.assertRaises(AdapterError):
            await self.svc.command("lr-plug", Action.CLEAN, Clean.START)     # a plug can't clean
        with self.assertRaises(AdapterError):
            await self.svc.command("lr-vacuum", Action.POWER, True)          # a vacuum has no on/off

    async def test_rooms_options_and_map(self):
        d = await self.svc.command("lr-vacuum", Action.CLEAN_ROOMS, [1, 3])
        self.assertEqual(d["state"]["activity"], Activity.CLEANING)
        d = await self.svc.command("lr-vacuum", Action.SET_SUCTION, "strong")
        self.assertEqual(d["state"]["suction"], "strong")
        await self.svc.command("lr-vacuum", Action.STATION, "empty_dustbin")
        await self.svc.command("lr-vacuum", Action.LOCATE)
        content_type, body = await self.svc.map_image("lr-vacuum")
        self.assertEqual(content_type, "image/svg+xml")
        self.assertIn(b"<svg", body)

    async def test_options_are_checked_against_the_device(self):
        for action, value in ((Action.CLEAN_ROOMS, []), (Action.CLEAN_ROOMS, [99]), (Action.CLEAN_ROOMS, "1"),
                              (Action.SET_SUCTION, "turbo"), (Action.SET_CLEAN_MODE, "polish"),
                              (Action.STATION, "self_destruct")):
            with self.subTest(action=action, value=value), self.assertRaises(AdapterError):
                await self.svc.command("lr-vacuum", action, value)
        with self.assertRaises(AdapterError):
            await self.svc.map_image("lr-plug")                      # a plug has no map

    async def test_rooms_that_arrive_later_are_saved_and_published(self):
        q = self.svc.subscribe()
        d = self.svc.store.devices["lr-vacuum"]
        d.meta = {}                                                   # as if the rooms weren't known yet
        await self.svc.refresh("lr-vacuum")                           # the adapter fills them in
        self.assertTrue(d.meta.get("rooms"))
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        self.assertTrue(events)                                       # the change was sent to the screen

    async def test_adapter_can_push_a_change(self):
        """A device that changes on its own shows up without waiting for the next poll."""
        demo = self.svc.adapters["demo"]
        demo._state["lr-vacuum"].update(activity=Activity.CLEANING, on=True, battery=55)
        demo.changed("lr-vacuum")
        await asyncio.sleep(0.6)
        st = self.svc.store.devices["lr-vacuum"].state
        self.assertEqual((st["activity"], st["battery"]), (Activity.CLEANING, 55))

    async def test_all_off_leaves_a_cleaning_vacuum_alone(self):
        await self.svc.command("lr-vacuum", Action.CLEAN, Clean.START)
        await self.svc.all_off()
        self.assertEqual(self.svc.store.devices["lr-vacuum"].state["activity"], Activity.CLEANING)


if __name__ == "__main__":
    unittest.main()
