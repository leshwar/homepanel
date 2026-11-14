"""Paired LG endpoint recovery; fake discovery and clients, never LAN or media actions."""
import asyncio
import copy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.adapters import lg_tv
from app.core.adapter import AdapterError, Device, PairingRequired

UUID = "uuid:01234567-89ab-cdef-0123-456789abcdef"
OLD, NEW = "192.168.1.10", "192.168.1.20"
MAC = "AA:BB:CC:DD:EE:01"


def device():
    return Device(id="tv", adapter="lg_tv", name="TV", kind="tv", caps=list(lg_tv.CAPS),
                  config={"ip":OLD,"client_key":"fixture-key","mac":MAC,"_uid":UUID},
                  meta={"model":"OLED65G4SUB.DUSQLJR"}, state={"online":True,"on":True,"volume":14},
                  power_on_screen="home")


def client():
    return SimpleNamespace(
        connection=SimpleNamespace(closed=False), input_connection=SimpleNamespace(closed=False),
        connect=AsyncMock(), disconnect=AsyncMock(), is_connected=lambda:True, client_key="fixture-key",
        get_power_state=AsyncMock(return_value={"state":"Active"}),
        button=AsyncMock(), move=AsyncMock(), power_off=AsyncMock(),
        tv_info=SimpleNamespace(connection={"wifiInfo":{"macAddress":MAC,"ipAddress":NEW}},
                                system={"modelName":"OLED65G4SUB.DUSQLJR"}),
        tv_state=SimpleNamespace(current_app_id="netflix",volume=14,muted=False,apps={},inputs={}))


def hit(ip=NEW, identity=UUID, location=None):
    return {"ip":ip,"usn":identity+"::urn:lge-com:service:webos-second-screen:1",
            "location":location or f"http://{ip}:1800/description.xml"}


def descriptor(identity=UUID):
    return f'<root xmlns="urn:schemas-upnp-org:device-1-0"><device><UDN>{identity}</UDN></device></root>'


class LGRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.d = device()
        self.a = lg_tv.LGTVAdapter({}, tempfile.gettempdir())
        self.c = client()
        self.discovery = AsyncMock(return_value=[hit(),hit()])
        self.descriptor = AsyncMock(return_value=descriptor())
        self.factory = patch.object(lg_tv,"_new_client",return_value=self.c).start()
        self.patches = [
            patch.object(lg_tv,"ssdp_search",self.discovery),
            patch.object(lg_tv,"http",self.descriptor),
            patch.object(lg_tv,"local_subnet_hosts",return_value=[OLD,NEW,"192.168.1.21"]),
            patch.object(lg_tv,"mac_from_arp",return_value=None),
            patch.object(lg_tv,"wake_on_lan",AsyncMock()),
        ]
        for p in self.patches:p.start()
        self.a._client = AsyncMock(side_effect=OSError("old endpoint unreachable"))

    async def asyncTearDown(self):
        await self.a.stop()
        patch.stopall()

    async def test_exact_uuid_model_guard_and_authenticated_mac_recovers_once(self):
        before=copy.deepcopy(self.d.config)
        state=await self.a.refresh(self.d)
        self.assertTrue(state["online"])
        self.assertTrue(state["on"])
        self.assertTrue(state["remote_ready"])
        self.assertFalse(state["stale"])
        self.assertEqual(self.d.config,{**before,"ip":NEW})
        self.assertEqual(self.d.power_on_screen,"home")
        self.discovery.assert_awaited_once_with(UUID,timeout=2)
        self.c.button.assert_not_awaited()
        lg_tv.wake_on_lan.assert_not_awaited()
        self.d.state=state
        self.a._client.side_effect=None
        self.a._client.return_value=self.c
        await self.a.refresh(self.d)
        self.discovery.assert_awaited_once()

    async def test_no_candidate_means_unknown_with_stale_last_report_not_off(self):
        self.discovery.return_value=[]
        state=await self.a.refresh(self.d)
        self.assertEqual((state["online"],state["on"],state["stale"]),(False,None,True))
        self.assertEqual(state["last_known"],{"on":True,"volume":14})
        self.assertTrue(state["wake_available"])
        self.d.state=state
        for _ in range(3):await self.a.refresh(self.d)
        self.discovery.assert_awaited_once()
        self.factory.assert_not_called()
        self.assertEqual(self.d.config["ip"],OLD)
        self.d.state={}
        self.assertIsNone((await self.a.refresh(self.d))["last_known"])

    async def test_unrelated_ambiguous_external_or_wrong_descriptor_never_get_credentials(self):
        cases=[[hit(identity="uuid:11111111-1111-1111-1111-111111111111")],
               [hit(),hit("192.168.1.21")],
               [hit(location="https://example.com/tv.xml")],
               [hit(location=f"http://user:pass@{NEW}/tv.xml")],
               [hit("127.0.0.1")], [hit("169.254.169.254")]]
        for hits in cases:
            self.a._recover_after.clear()
            self.discovery.return_value=hits
            state=await self.a.refresh(self.d)
            self.assertFalse(state["online"])
            self.assertEqual(self.d.config["ip"],OLD)
        self.factory.assert_not_called()
        self.a._recover_after.clear()
        self.discovery.return_value=[hit()]
        self.descriptor.return_value=descriptor("uuid:11111111-1111-1111-1111-111111111111")
        await self.a.refresh(self.d)
        self.factory.assert_not_called()

    async def test_wrong_local_mac_is_rejected_before_pairing_key_is_used(self):
        with patch.object(lg_tv,"mac_from_arp",return_value="AA:BB:CC:DD:EE:02"):
            state=await self.a.refresh(self.d)
        self.assertFalse(state["online"])
        self.factory.assert_not_called()

    async def test_rejection_at_old_endpoint_checks_saved_identity_before_repairing(self):
        self.a._client.side_effect=PairingRequired("Saved endpoint rejected the key")
        state=await self.a.refresh(self.d)
        self.assertTrue(state["online"])
        self.assertEqual(self.d.config["ip"],NEW)
        self.assertEqual(self.d.config["client_key"],"fixture-key")

    async def test_power_on_after_rediscovery_does_not_wake_or_route_an_already_on_tv_home(self):
        self.d.state={"online":False,"on":None,"stale":True}
        state=await self.a.command(self.d,"power",True)
        self.assertTrue(state["on"])
        self.assertFalse(state["stale"])
        self.assertEqual(self.d.config["ip"],NEW)
        self.c.button.assert_not_awaited()
        lg_tv.wake_on_lan.assert_not_awaited()

    async def test_authenticated_wrong_mac_or_key_or_missing_status_is_not_persisted(self):
        for failure in ("mac","key","power"):
            self.a._recover_after.clear()
            candidate=client()
            if failure=="mac":candidate.tv_info.connection["wifiInfo"]["macAddress"]="AA:BB:CC:DD:EE:02"
            if failure=="key":candidate.client_key="unexpected-key"
            if failure=="power":candidate.get_power_state.return_value={}
            self.factory.return_value=candidate
            state=await self.a.refresh(self.d)
            self.assertFalse(state["online"])
            self.assertEqual(self.d.config["ip"],OLD)
            candidate.disconnect.assert_awaited_once()

    async def test_explicit_standby_is_off_but_screen_saver_is_on(self):
        self.a._client.side_effect=None
        self.a._client.return_value=self.c
        for power,on in (("Suspend",False),("Power Off",False),("Active Standby",False),("Screen Saver",True),("Active",True),("Unknown",None)):
            self.c.get_power_state.return_value={"state":power}
            state=await self.a.refresh(self.d)
            self.assertTrue(state["online"])
            self.assertEqual(state["on"],on)
            self.assertFalse(state["stale"])
        self.discovery.assert_not_awaited()

    async def test_cancel_removal_and_concurrent_endpoint_change_do_not_commit_candidate(self):
        entered=asyncio.Event()
        async def wait():entered.set();await asyncio.Event().wait()
        self.c.connect.side_effect=wait
        task=asyncio.create_task(self.a.refresh(self.d))
        await entered.wait()
        await self.a.forget(self.d)
        with self.assertRaises(asyncio.CancelledError):await task
        self.c.disconnect.assert_awaited()
        self.assertEqual(self.d.config["ip"],OLD)
        self.a=lg_tv.LGTVAdapter({},tempfile.gettempdir())
        self.a._client=AsyncMock(side_effect=OSError())
        async def change():self.d.config["ip"]="192.168.1.21"
        self.c.connect.side_effect=change
        await self.a.refresh(self.d)
        self.assertEqual(self.d.config["ip"],"192.168.1.21")

    async def test_closed_input_socket_is_replaced_before_next_command(self):
        del self.a._client
        dead=client();dead.input_connection.closed=True
        self.a._clients[self.d.id]=dead
        await self.a.command(self.d,"key","UP")
        dead.disconnect.assert_awaited_once()
        dead.button.assert_not_awaited()
        self.c.button.assert_awaited_once_with("UP")
        self.discovery.assert_not_awaited()

    async def test_delivered_then_failed_command_is_not_replayed(self):
        self.a._client.side_effect=None
        self.a._client.return_value=self.c
        self.c.button.side_effect=ConnectionError("write outcome unknown")
        with self.assertRaisesRegex(AdapterError,"not repeated"):await self.a.command(self.d,"key","UP")
        self.c.button.assert_awaited_once()

    async def test_simultaneous_polls_use_one_discovery_and_shutdown_cancels_work(self):
        self.a._client.side_effect=lambda d:self.a._clients[d.id] if d.id in self.a._clients else (_ for _ in ()).throw(OSError())
        results=await asyncio.gather(self.a.refresh(self.d),self.a.refresh(self.d))
        self.assertTrue(all(s["online"] for s in results))
        self.discovery.assert_awaited_once()
        self.a._clients.clear()
        self.a._recover_after.clear()
        entered=asyncio.Event()
        async def wait():entered.set();await asyncio.Event().wait()
        self.c.connect.side_effect=wait
        task=asyncio.create_task(self.a.refresh(self.d))
        await entered.wait()
        await self.a.stop()
        with self.assertRaises(asyncio.CancelledError):await task
        self.c.disconnect.assert_awaited()


class LGRegistrationGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_older_library_cannot_bypass_identity_guard(self):
        with patch("aiowebostv.WebOsClient", type("OldClient", (), {})):
            with self.assertRaisesRegex(AdapterError,"1.0 or newer"):
                lg_tv._new_client(device())

    async def test_model_is_checked_before_key_and_pairing_is_never_recreated(self):
        d=device()
        c=lg_tv._new_client(d)
        ws=SimpleNamespace(send_json=AsyncMock(),receive_json=AsyncMock())
        c.tv_info.system={"modelName":"OTHER TV"}
        with self.assertRaisesRegex(AdapterError,"key was not sent"):await c._check_registration(ws)
        ws.send_json.assert_not_awaited()
        c.tv_info.system={"modelName":d.meta["model"]}
        for response in ({"type":"response","payload":{"pairingType":"PROMPT"}},
                         {"type":"registered","payload":{"client-key":"different"}}):
            ws.receive_json.return_value=response
            with self.assertRaises(PairingRequired):await c._check_registration(ws)
        ws.receive_json.return_value={"type":"registered","payload":{"client-key":"fixture-key"}}
        await c._check_registration(ws)
        self.assertEqual(c.client_key,"fixture-key")
