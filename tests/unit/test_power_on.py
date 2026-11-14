"""Unit tests: turning TVs on (MAC addresses, wake-up packets) and saving what adapters learn."""
import shutil
import asyncio
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.adapters import lg_tv
from app.adapters.lg_tv import LGTVAdapter, mac_from_connection_info
from app.core import net
from app.core.adapter import Action, AdapterError, Cap, Device, DeviceAdapter, Found, Kind, PairingRequired, register
from app.core.service import HomeService


class MacAddresses(unittest.TestCase):
    def test_normalize(self):
        for raw in ("a4:36:c7:1:2:3", "A4-36-C7-01-02-03", "a436c7010203", " A4:36:C7:01:02:03 "):
            self.assertEqual(net.normalize_mac(raw), "A4:36:C7:01:02:03")
        for bad in ("", None, "hello", "00:00:00:00:00:00", "12:34"):
            self.assertIsNone(net.normalize_mac(bad))

    def test_macos_arp_output(self):
        out = ("? (192.168.88.1) at 48:a9:8a:0:11:22 on en0 ifscope [ethernet]\n"
               "? (192.168.88.13) at 64:e4:a5:3:4:5 on en0 ifscope [ethernet]\n")
        self.assertEqual(net.parse_arp_output(out, "192.168.88.13"), "64:E4:A5:03:04:05")
        self.assertIsNone(net.parse_arp_output("? (192.168.88.13) (incomplete) on en0", "192.168.88.13"))

    def test_mac_from_lg_connection_info(self):
        info = {"returnValue": True,
                "wiredInfo": {"macAddress": "11:22:33:44:55:66", "connected": False},
                "wifiInfo": {"macAddress": "64:e4:a5:03:04:05", "ipAddress": "192.168.88.13", "connected": True}}
        self.assertEqual(mac_from_connection_info(info, "192.168.88.13"), "64:E4:A5:03:04:05")
        self.assertIsNone(mac_from_connection_info(None))

    def test_wake_packet_and_targets(self):
        pkt = net.wol_packet("64:e4:a5:03:04:05")
        self.assertEqual(len(pkt), 102)
        self.assertTrue(pkt.startswith(b"\xff" * 6))
        with self.assertRaises(ValueError):
            net.wol_packet("nope")
        targets = net.wol_targets("192.168.88.13")
        self.assertIn("255.255.255.255", targets)
        self.assertEqual(targets[-1], "192.168.88.13")

class LGWakeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.adapter = LGTVAdapter({}, tempfile.gettempdir())
        self.device = Device(id="tv", adapter="lg_tv", name="TV", kind=Kind.TV, caps=list(lg_tv.CAPS),
                             config={"ip": "192.0.2.10", "client_key": "test-key", "mac": "AA:BB:CC:DD:EE:01"},
                             state={"on": False}, power_on_screen="home")
        self.client = SimpleNamespace(get_power_state=AsyncMock(side_effect=[
            {"state": "Suspend"}, {"state": "Active"}]), input_connection=SimpleNamespace(closed=False),
            connection=SimpleNamespace(closed=False), button=AsyncMock(), disconnect=AsyncMock(), is_connected=lambda: True)
        self.adapter._client = AsyncMock(return_value=self.client)
        self.wol = patch.object(lg_tv, "wake_on_lan", AsyncMock())
        self.wake = self.wol.start()
        self.poll = patch.object(lg_tv, "WAKE_POLL", .001)
        self.poll.start()

    async def asyncTearDown(self):
        self.wol.stop()
        self.poll.stop()

    async def test_home_is_sent_once_only_after_authenticated_active_input_ready(self):
        result = await self.adapter.command(self.device, Action.POWER, True)
        self.assertTrue(result["on"])
        self.assertFalse(result["stale"])
        self.wake.assert_awaited_once()
        self.client.button.assert_awaited_once_with("HOME")
        self.assertEqual(self.client.get_power_state.await_count, 2)

    async def test_already_on_and_previous_input_never_send_home(self):
        self.client.get_power_state.side_effect = None
        self.client.get_power_state.return_value = {"state": "Active"}
        await self.adapter.command(self.device, Action.POWER, True)  # stale off snapshot, actual TV already on
        self.wake.assert_not_awaited()
        self.client.button.assert_not_awaited()
        self.device.state["on"] = True
        await self.adapter.command(self.device, Action.POWER, True)
        self.assertEqual(self.client.get_power_state.await_count, 1)
        self.device.state["on"] = False
        self.device.power_on_screen = "previous"
        self.client.get_power_state.side_effect = [{"state": "Suspend"}, {"state": "Active"}]
        await self.adapter.command(self.device, Action.POWER, True)
        self.client.button.assert_not_awaited()

    async def test_cold_connect_and_boot_errors_retry_but_not_home_write(self):
        self.adapter._client.side_effect = [OSError("booting"), OSError("booting"), self.client]
        self.client.get_power_state.side_effect = None
        self.client.get_power_state.return_value = {"state": "Active"}
        await self.adapter.command(self.device, Action.POWER, True)
        self.client.button.assert_awaited_once_with("HOME")
        self.adapter._client.side_effect = None
        self.client.get_power_state.side_effect = [{"state": "Suspend"}, {"state": "Active"}]
        self.client.button.reset_mock()
        self.client.button.side_effect = OSError("lost socket")
        with self.assertRaisesRegex(AdapterError, "woke, but Home"):
            await self.adapter.command(self.device, Action.POWER, True)
        self.client.button.assert_awaited_once()

    async def test_timeout_unpaired_and_cancellation_never_claim_success(self):
        self.client.get_power_state.side_effect = None
        self.client.get_power_state.return_value = {"state": "Suspend"}
        with patch.object(lg_tv, "WAKE_READY_TIMEOUT", .01):
            with self.assertRaisesRegex(AdapterError, "did not become ready"):
                await self.adapter.command(self.device, Action.POWER, True)
        self.client.button.assert_not_awaited()
        del self.device.config["client_key"]
        with self.assertRaises(PairingRequired):
            await self.adapter.command(self.device, Action.POWER, True)
        self.device.config["client_key"] = "test-key"
        self.adapter._clients[self.device.id] = self.client
        ready_started = asyncio.Event()
        async def wait_for_ready(_):
            ready_started.set()
            await asyncio.Event().wait()
        self.adapter._ready = wait_for_ready
        pending = asyncio.create_task(self.adapter.command(self.device, Action.POWER, True))
        await ready_started.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.client.button.assert_not_awaited()
        self.client.disconnect.assert_awaited()
        self.assertNotIn(self.device.id, self.adapter._waking)

    async def test_cancel_at_a_completed_readiness_check_does_not_continue_waking(self):
        async def completed_ready(_):
            pending.cancel()
            return None
        self.adapter._ready = completed_ready
        pending = asyncio.create_task(self.adapter.command(self.device, Action.POWER, True))
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.wake.assert_not_awaited()
        self.client.button.assert_not_awaited()
        self.assertNotIn(self.device.id, self.adapter._waking)

    async def test_input_socket_must_be_ready_even_when_network_and_power_are_active(self):
        self.client.get_power_state.side_effect = None
        self.client.get_power_state.return_value = {"state": "Active"}
        self.client.input_connection.closed = True
        with patch.object(lg_tv, "WAKE_READY_TIMEOUT", .01):
            with self.assertRaisesRegex(AdapterError, "did not become ready"):
                await self.adapter.command(self.device, Action.POWER, True)
        self.client.button.assert_not_awaited()

    async def test_cancelled_connect_is_disconnected_before_it_can_deliver_home(self):
        self.adapter = LGTVAdapter({}, tempfile.gettempdir())
        entered = asyncio.Event()
        async def connect():
            entered.set()
            await asyncio.Event().wait()
        client = SimpleNamespace(connect=connect, disconnect=AsyncMock())
        with patch.object(lg_tv, "_new_client", return_value=client):
            task = asyncio.create_task(self.adapter._client(self.device))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        client.disconnect.assert_awaited_once()
        self.assertNotIn(self.device.id, self.adapter._clients)


@register
class LearningTV(DeviceAdapter):
    """A fake TV adapter that learns its MAC address during refresh, like the LG adapter."""
    id = "learning_tv_test"
    name = "Learning TV"
    kinds = (Kind.TV,)
    hidden = True
    poll_interval = 3600

    async def refresh(self, device):
        device.config.setdefault("mac", "AA:BB:CC:DD:EE:01")
        return {"on": True}

    async def command(self, device, action, value=None):
        return {}

    def from_manual(self, values):
        return Found(adapter=self.id, uid=values["ip"], name="TV", kind=Kind.TV, caps=[Cap.POWER],
                     config={"ip": values["ip"]})


class LearnedSettingsAreSaved(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_mac_learned_in_refresh_is_saved_and_shown(self):
        d = await self.svc.add_device("learning_tv_test", manual={"ip": "10.0.0.20"})
        await self.svc.refresh(d["id"])
        again = HomeService(self.dir, demo=True)
        self.assertEqual(again.store.devices[d["id"]].config["mac"], "AA:BB:CC:DD:EE:01")
        self.assertEqual(self.svc.public_device(self.svc.get(d["id"]))["mac"], "AA:BB:CC:DD:EE:01")

    async def test_mac_can_be_entered_or_cleared(self):
        out = self.svc.update_device("lr-tv", {"mac": "64-e4-a5-03-04-05"})
        self.assertEqual(out["mac"], "64:E4:A5:03:04:05")
        with self.assertRaises(AdapterError):
            self.svc.update_device("lr-tv", {"mac": "not a mac"})
        self.assertEqual(self.svc.update_device("lr-tv", {"mac": ""})["mac"], "")

    async def test_plugs_dont_expose_a_mac_field(self):
        self.assertNotIn("mac", self.svc.public_device(self.svc.get("lr-plug")))
        await self.svc.command("lr-plug", Action.POWER, True)

    async def test_startup_preference_is_supported_explicit_and_persistent(self):
        device = Device(id="fake-lg", adapter="lg_tv", name="TV", kind=Kind.TV, caps=list(lg_tv.CAPS))
        self.svc.store.devices[device.id] = device
        out = self.svc.public_device(device)
        self.assertEqual(out["power_on_screen"], "previous")
        self.assertEqual([o["id"] for o in out["startup_screens"]], ["previous", "home"])
        self.svc.update_device(device.id, {"power_on_screen": "home"})
        self.assertEqual(HomeService(self.dir, demo=True).store.devices[device.id].power_on_screen, "home")
        for bad in ("ps5", True, None):
            with self.assertRaises(AdapterError):
                self.svc.update_device(device.id, {"power_on_screen": bad})
        with self.assertRaises(AdapterError):
            self.svc.update_device("lr-plug", {"power_on_screen": "home"})
        self.svc.update_device(device.id, {"power_on_screen": "previous"})
        self.assertEqual(device.power_on_screen, "previous")


if __name__ == "__main__":
    unittest.main()
