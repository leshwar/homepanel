"""The last command sent wins: commands for one device run in the order they arrived, and a
refresh that was reading while a command finished doesn't put the older state back."""
import asyncio
import shutil
import tempfile
import unittest

from app.core.adapter import Action, Cap, DeviceAdapter, Found, Kind, register
from app.core.service import HomeService


@register
class SlowFirstLight(DeviceAdapter):
    """A light that answers some commands slowly (like a busy Wi-Fi bulb) and reads slowly."""
    id = "slow_first_test"
    name = "Slow light"
    kinds = (Kind.LIGHT,)
    hidden = True
    poll_interval = 3600
    delays = {}            # color -> seconds the light takes to apply it
    refresh_delay = 0.0
    state = {}
    started = []           # (action, value) in the order the light started on them

    async def refresh(self, device):
        seen = dict(SlowFirstLight.state)       # what the light says now…
        await asyncio.sleep(SlowFirstLight.refresh_delay)   # …arrives a little later
        return seen

    async def command(self, device, action, value=None):
        SlowFirstLight.started.append((action, value))
        if action == Action.COLOR:
            await asyncio.sleep(SlowFirstLight.delays.get(str(value), 0))
            SlowFirstLight.state.update(on=True, color=value, color_mode="color")
            return {"on": True, "color": value, "color_mode": "color"}
        if action == Action.POINTER:
            return {}
        return {}

    def from_manual(self, values):
        return Found(adapter=self.id, uid=values["ip"], name="Strip", kind=Kind.LIGHT,
                     caps=[Cap.POWER, Cap.COLOR, Cap.POINTER], config={"ip": values["ip"]})


RED, GREEN = {"r": 255, "g": 0, "b": 0}, {"r": 94, "g": 224, "b": 122}


class CommandOrder(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()
        SlowFirstLight.delays, SlowFirstLight.refresh_delay, SlowFirstLight.started = {}, 0.0, []
        SlowFirstLight.state = {"on": True, "color": RED, "color_mode": "color"}
        self.id = (await self.svc.add_device("slow_first_test", manual={"ip": "10.0.0.7"}))["id"]

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def color(self):
        return self.svc.get(self.id).state.get("color")

    async def test_last_command_sent_wins(self):
        # red takes the light a while, green is quick: without ordering, red would land last
        SlowFirstLight.delays = {str(RED): 0.15}
        first = asyncio.create_task(self.svc.command(self.id, "color", "#ff0000"))
        await asyncio.sleep(0.01)
        second = asyncio.create_task(self.svc.command(self.id, "color", "#5ee07a"))
        await asyncio.gather(first, second)
        self.assertEqual([v for a, v in SlowFirstLight.started if a == "color"], [RED, GREEN])
        self.assertEqual(self.color(), GREEN)
        self.assertEqual(SlowFirstLight.state["color"], GREEN)

    async def test_other_devices_are_not_held_up(self):
        SlowFirstLight.delays = {str(RED): 0.3}
        slow = asyncio.create_task(self.svc.command(self.id, "color", "#ff0000"))
        await asyncio.sleep(0.01)
        await asyncio.wait_for(self.svc.command("kt-kettle", "power", True), 0.25)   # another device: no wait
        await asyncio.wait_for(self.svc.command(self.id, "pointer", {"dx": 3, "dy": 0}), 0.25)  # pointer: no queue
        await slow

    async def test_a_stale_refresh_doesnt_undo_a_command(self):
        SlowFirstLight.refresh_delay = 0.2
        reading = asyncio.create_task(self.svc.refresh(self.id))     # reads "red" now, reports it later
        await asyncio.sleep(0.05)
        await self.svc.command(self.id, "color", "#5ee07a")
        await reading
        self.assertEqual(self.color(), GREEN)
        SlowFirstLight.refresh_delay = 0
        await self.svc.refresh(self.id)                               # the next reading applies as usual
        self.assertEqual(self.color(), GREEN)
        SlowFirstLight.state["color"] = RED                           # changed on the light itself
        await self.svc.refresh(self.id)
        self.assertEqual(self.color(), RED)


if __name__ == "__main__":
    unittest.main()
