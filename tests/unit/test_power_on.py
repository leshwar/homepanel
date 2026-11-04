"""Unit tests: turning TVs on (MAC addresses, wake-up packets) and saving what adapters learn."""
import shutil
import tempfile
import unittest

from app.adapters.lg_tv import mac_from_connection_info
from app.core import net
from app.core.adapter import Action, AdapterError, Cap, DeviceAdapter, Found, Kind, register
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


if __name__ == "__main__":
    unittest.main()
