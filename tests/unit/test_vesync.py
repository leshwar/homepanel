"""VeSync v3 contracts and Core300S mapping using fake SDK objects only."""
import inspect
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.adapters.vesync import VeSyncAdapter
from app.core.adapter import Action, AdapterBackoff, AdapterError, Cap, Device, Kind
from app.core.service import HomeService


class FakePurifier:
    def __init__(self):
        self.cid = "core-fixture"
        self.device_type = "Core300S"
        self.device_name = "Bedroom purifier"
        self.supports_air_quality = True
        self.fan_levels = [1, 2, 3]
        self.modes = ["sleep", "manual", "auto"]
        self.last_response = SimpleNamespace(error_type="success")
        self.state = SimpleNamespace(connection_status="online", device_status="on", mode="auto", fan_level=2,
                                     filter_life=75, pm25=12, air_quality_string="good")
        self.calls = []
        self.fail = False

    async def update(self):
        self.calls.append(("refresh", None))

    async def turn_on(self):
        self.calls.append(("power", True))
        if self.fail:
            return False
        self.state.device_status = "on"
        return True

    async def turn_off(self):
        self.calls.append(("power", False))
        if self.fail:
            return False
        self.state.device_status = "off"
        return True

    async def set_fan_speed(self, speed):
        self.calls.append(("speed", speed))
        self.state.fan_level = speed; self.state.mode = "manual"; self.state.device_status = "on"
        return True

    async def set_mode(self, mode):
        self.calls.append(("mode", mode))
        self.state.mode = mode; self.state.device_status = "on"
        return True


class FakeManager:
    instances = []
    login_error = None

    def __init__(self, username, password, **kwargs):
        self.kwargs = kwargs
        self.enabled = False
        self.closed = False
        self.verbose = None
        purifier = FakePurifier()
        other = FakePurifier(); other.cid = "unsupported"; other.device_type = "Core400S"
        self.devices = SimpleNamespace(air_purifiers=[purifier, other])
        self.__class__.instances.append(self)

    async def login(self):
        if self.login_error:
            raise self.login_error
        self.enabled = True
        return True

    async def get_devices(self):
        return True

    async def __aexit__(self, *args):
        self.closed = True


class VeSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeManager.instances = []; FakeManager.login_error = None
        self.patch = patch("pyvesync.VeSync", FakeManager); self.patch.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.adapter = VeSyncAdapter({"email": "fixture@example.com", "password": "fixture-password", "country": "US"}, self.tmp.name)
        self.device = Device(id="purifier", adapter="vesync", name="Purifier", kind=Kind.PURIFIER, config={"cid": "core-fixture"})

    async def asyncTearDown(self):
        await self.adapter.stop()
        self.patch.stop(); self.tmp.cleanup(); FakeManager.login_error = None

    async def test_core300s_discovery_state_modes_speed_and_redaction(self):
        found = await self.adapter.discover()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, Kind.PURIFIER)
        self.assertNotIn("config", found[0].to_dict())
        await self.adapter.setup(self.device)
        state = await self.adapter.refresh(self.device)
        self.assertEqual((state["pm25"], state["filter_life"], state["air_quality"]), (12, 75, "Good"))
        manager = FakeManager.instances[-1]
        self.assertTrue(manager.kwargs["redact"])
        self.assertFalse(manager.verbose)
        self.assertEqual(self.device.meta["fan_speeds"], [{"id": str(n), "name": f"Speed {n}"} for n in (1, 2, 3)])
        self.assertEqual((await self.adapter.command(self.device, Action.SET_FAN_SPEED, "3"))["fan_mode"], "manual")
        self.assertEqual((await self.adapter.command(self.device, Action.SET_FAN_MODE, "sleep"))["fan_mode"], "sleep")
        self.assertFalse((await self.adapter.command(self.device, Action.POWER, False))["on"])
        with self.assertRaises(AdapterError):
            await self.adapter.command(self.device, Action.SET_FAN_SPEED, "4")
        purifier = manager.devices.air_purifiers[0]
        purifier.supports_air_quality = False
        state = await self.adapter.refresh(self.device)
        self.assertNotIn("pm25", state)
        self.assertNotIn(Cap.AIR_QUALITY, self.device.caps)

    async def test_failures_are_explicit_redacted_and_service_backoff_blocks_retries(self):
        from pyvesync.utils.errors import VeSyncLoginError, VeSyncRateLimitError
        service = HomeService(self.tmp.name)
        for index, error in enumerate((VeSyncLoginError("fixture-password token=private"), VeSyncRateLimitError())):
            FakeManager.login_error = error
            service._adapter_backoff.clear()
            with self.assertRaises(AdapterBackoff) as caught:
                await service._with_adapter_backoff("vesync", self.adapter.discover)
            self.assertNotIn("private", str(caught.exception))
            self.assertNotIn("fixture-password", str(caught.exception))
            self.assertTrue(FakeManager.instances[-1].closed)
            attempts = len(FakeManager.instances)
            with self.assertRaisesRegex(AdapterError, "Retry in"):
                await service._with_adapter_backoff("vesync", self.adapter.discover)
            self.assertEqual(len(FakeManager.instances), attempts)
            service.set_account("vesync", {})
            self.assertIn("vesync", service._adapter_backoff)
            service.set_account("vesync", {"email": f"new{index}@example.com"})
            self.assertNotIn("vesync", service._adapter_backoff)

    async def test_offline_false_commands_and_missing_readings_are_not_success(self):
        await self.adapter.setup(self.device)
        purifier = FakeManager.instances[-1].devices.air_purifiers[0]
        purifier.fail = True
        with self.assertRaises(AdapterBackoff):
            await self.adapter.command(self.device, Action.POWER, False)
        purifier.fail = False; purifier.state.connection_status = "offline"
        with self.assertRaisesRegex(AdapterBackoff, "offline in VeSync"):
            await self.adapter.refresh(self.device)
        purifier.state.connection_status = "online"; purifier.state.pm25 = None; purifier.state.filter_life = None
        state = await self.adapter.refresh(self.device)
        self.assertNotIn("pm25", state); self.assertNotIn("filter_life", state)
        purifier.state.pm25 = float("nan")
        with self.assertRaisesRegex(AdapterError, "invalid reading"):
            await self.adapter.refresh(self.device)

    def test_pinned_sdk_has_the_async_contract_and_core300s_model(self):
        from importlib.metadata import version
        from pyvesync.devices.vesyncpurifier import VeSyncAirBypass
        self.assertEqual(version("pyvesync"), "3.5.0")
        for method in ("update", "set_mode", "set_fan_speed", "turn_on", "turn_off"):
            self.assertTrue(inspect.iscoroutinefunction(getattr(VeSyncAirBypass, method)), method)
