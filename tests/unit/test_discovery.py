"""Unit tests: TV discovery fallbacks (no network: the network helpers are replaced)."""
import tempfile
import unittest

from app.adapters import lg_tv
from app.core import net


class Helpers(unittest.TestCase):
    def test_is_multicast(self):
        self.assertTrue(net.is_multicast("239.255.255.250"))
        self.assertFalse(net.is_multicast("192.168.1.20"))
        self.assertFalse(net.is_multicast("not-an-ip"))

    def test_in_container_is_a_bool(self):
        self.assertIsInstance(net.in_container(), bool)


class LGScanFallback(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.saved = {n: getattr(lg_tv, n) for n in ("ssdp_search", "local_subnet_hosts", "scan_ports",
                                                      "http", "port_open", "mac_from_arp")}

        async def no_ssdp(*a, **k):
            return []                                   # network blocks discovery broadcasts

        async def scan(hosts, ports, **k):
            return {"10.0.0.5": 3001, "10.0.0.9": 3000}  # two hosts with a webOS-like port open

        async def fake_http(method, url, **k):
            if "10.0.0.5" in url:
                return "Hello world"                    # what webOS answers on :3000
            raise OSError("connection refused")

        async def closed(*a, **k):
            return False

        lg_tv.ssdp_search, lg_tv.scan_ports, lg_tv.http, lg_tv.port_open = no_ssdp, scan, fake_http, closed
        lg_tv.local_subnet_hosts = lambda: ["10.0.0.5", "10.0.0.9"]
        lg_tv.mac_from_arp = lambda ip: "AA:BB:CC:DD:EE:05" if ip == "10.0.0.5" else None

    def tearDown(self):
        for n, f in self.saved.items():
            setattr(lg_tv, n, f)

    async def test_finds_tv_when_broadcast_discovery_is_blocked(self):
        found = await lg_tv.LGTVAdapter({}, tempfile.mkdtemp()).discover()
        self.assertEqual([(f.config["ip"], f.uid, f.needs_pairing) for f in found],
                         [("10.0.0.5", "AA:BB:CC:DD:EE:05", True)])   # the non-webOS host is ignored
        self.assertIn("network scan", found[0].detail)


if __name__ == "__main__":
    unittest.main()
