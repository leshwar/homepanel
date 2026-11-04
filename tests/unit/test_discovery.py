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


class LGSameUidEitherWay(unittest.IsolatedAsyncioTestCase):
    """A TV found by SSDP and the same TV found by the port scan get the same uid (its MAC),
    so "Search all brands" can't offer an already-added TV as new."""
    IP, MAC, UUID = "10.0.0.5", "AA:BB:CC:DD:EE:05", "uuid:14704f92-0000-0000-0000-000000000001"

    def setUp(self):
        self.saved = {n: getattr(lg_tv, n) for n in ("ssdp_search", "local_subnet_hosts", "scan_ports",
                                                      "http", "port_open", "mac_from_arp")}
        self.ssdp_hits = []
        self.arp = {}

        async def ssdp(*a, **k):
            return self.ssdp_hits

        async def scan(hosts, ports, **k):
            return {self.IP: 3001} if self.IP in hosts else {}

        async def fake_http(method, url, **k):
            return "Hello world"

        async def port_open(ip, port, timeout=1.0):
            self.arp[ip] = "aa-bb-cc-dd-ee-05"           # talking to the TV puts it in the ARP cache
            return True

        lg_tv.ssdp_search, lg_tv.scan_ports, lg_tv.http, lg_tv.port_open = ssdp, scan, fake_http, port_open
        lg_tv.local_subnet_hosts = lambda: [self.IP]
        lg_tv.mac_from_arp = lambda ip: self.arp.get(ip)
        self.adapter = lg_tv.LGTVAdapter({}, tempfile.mkdtemp())

    def tearDown(self):
        for n, f in self.saved.items():
            setattr(lg_tv, n, f)

    async def test_ssdp_and_scan_give_the_same_uid(self):
        self.ssdp_hits = [{"ip": self.IP, "usn": f"{self.UUID}::urn:lge-com:service:webos-second-screen:1"}]
        by_ssdp = (await self.adapter.discover())[0]     # ARP was empty: the adapter knocks to learn the MAC
        self.ssdp_hits, self.arp = [], {}
        by_scan = (await self.adapter.discover())[0]
        self.assertEqual(by_ssdp.uid, self.MAC)
        self.assertEqual(by_scan.uid, by_ssdp.uid)
        self.assertEqual((by_ssdp.config["uuid"], by_ssdp.aliases), (self.UUID, [self.UUID]))
        self.assertIn("network scan", by_scan.detail)

    async def test_tv_saved_under_old_ssdp_uid_still_matches(self):
        from app.core.adapter import Device
        old = Device(id="tv", adapter="lg_tv", name="TV", config={"ip": self.IP, "_uid": self.UUID})
        self.ssdp_hits = [{"ip": self.IP, "usn": f"{self.UUID}::urn:lge-com:service:webos-second-screen:1"}]
        f = (await self.adapter.discover())[0]
        self.assertTrue({f.uid, *f.aliases} & self.adapter.known_ids(old))       # via the uuid alias
        old.config["mac"] = "aa:bb:cc:dd:ee:05"                                   # learned after pairing
        self.ssdp_hits, self.arp = [], {}
        f = (await self.adapter.discover())[0]
        self.assertFalse(f.aliases)                                               # the scan can't see the uuid
        self.assertIn(f.uid, self.adapter.known_ids(old))                         # but the MAC matches

    def test_manual_add_with_mac_uses_the_mac_as_uid(self):
        f = self.adapter.from_manual({"ip": self.IP, "mac": "aabbccddee05"})
        self.assertEqual((f.uid, f.aliases, f.config["mac"]), (self.MAC, [self.IP], self.MAC))
        self.assertEqual(self.adapter.from_manual({"ip": self.IP}).uid, self.IP)


class SamsungUid(unittest.IsolatedAsyncioTestCase):
    async def test_uid_is_the_normalised_mac_and_keeps_the_old_form(self):
        from app.adapters import samsung_tv
        saved = (samsung_tv.ssdp_search, samsung_tv.http)

        async def ssdp(*a, **k):
            return [{"ip": "10.0.0.7"}]

        async def fake_http(method, url, **k):
            return {"device": {"name": "TV", "wifiMac": "aa-bb-cc-00-11-22", "id": "uuid:abc"}}
        samsung_tv.ssdp_search, samsung_tv.http = ssdp, fake_http
        try:
            f = (await samsung_tv.SamsungTVAdapter({}, tempfile.mkdtemp()).discover())[0]
        finally:
            samsung_tv.ssdp_search, samsung_tv.http = saved
        self.assertEqual(f.uid, "AA:BB:CC:00:11:22")
        self.assertEqual(f.aliases, ["AA-BB-CC-00-11-22", "UUID:ABC"])         # what older versions saved
        self.assertEqual(f.config["uuid"], "uuid:abc")


if __name__ == "__main__":
    unittest.main()


class PhoneUrl(unittest.TestCase):
    def test_lan_address_becomes_a_link(self):
        self.assertEqual(net.phone_url(8080, ip="192.168.1.20"), "http://192.168.1.20:8080")

    def test_no_network_means_no_link(self):
        self.assertIsNone(net.phone_url(8080, ip="127.0.0.1"))
