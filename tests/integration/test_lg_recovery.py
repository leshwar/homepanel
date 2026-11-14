"""Verified recovery through the service, with only fake TV/SSDP endpoints."""
import asyncio
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.adapters import lg_tv
from app.core.adapter import AdapterError
from app.core.service import HomeService
from tests.unit.test_lg_recovery import OLD, NEW, device, client, hit, descriptor


class LGRecoveryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.svc=HomeService(self.folder.name)
        self.d=device()
        self.c=client()
        self.a=lg_tv.LGTVAdapter({},self.folder.name)
        self.svc.store.devices[self.d.id]=self.d
        self.svc.adapters={"lg_tv":self.a}
        self.a._client=AsyncMock(side_effect=OSError("unreachable"))
        self.patches=[
            patch.object(lg_tv,"ssdp_search",AsyncMock(return_value=[hit()])),
            patch.object(lg_tv,"http",AsyncMock(return_value=descriptor())),
            patch.object(lg_tv,"local_subnet_hosts",return_value=[OLD,NEW]),
            patch.object(lg_tv,"mac_from_arp",return_value=None),
            patch.object(lg_tv,"_new_client",return_value=self.c),
            patch.object(lg_tv,"wake_on_lan",AsyncMock()),
        ]
        for p in self.patches:p.start()

    async def asyncTearDown(self):
        await self.svc.stop()
        for p in reversed(self.patches):p.stop()
        self.folder.cleanup()

    async def test_verified_recovery_is_saved_with_same_identity_and_no_actuation(self):
        before=copy.deepcopy(self.d.config)
        await self.svc.refresh(self.d.id)
        saved=HomeService(self.folder.name).get(self.d.id)
        self.assertEqual(saved.config,{**before,"ip":NEW})
        state=self.svc.public_device(self.d)["state"]
        self.assertTrue(state["online"]);self.assertTrue(state["on"]);self.assertTrue(state["remote_ready"])
        self.assertFalse(state["stale"])
        self.c.button.assert_not_awaited()
        lg_tv.wake_on_lan.assert_not_awaited()

    async def test_first_failed_read_is_unavailable_not_current_off_and_recovery_clears_it(self):
        lg_tv.ssdp_search.return_value=[]
        await self.svc.refresh(self.d.id)
        state=self.d.state
        self.assertFalse(state["online"])
        self.assertIsNone(state["on"])
        self.assertTrue(state["last_known"]["on"])
        self.assertTrue(state["wake_available"])
        self.assertFalse(Path(self.svc.store.path).exists())
        lg_tv.ssdp_search.return_value=[hit()]
        self.a._recover_after.clear()
        await self.svc.refresh(self.d.id)
        self.assertTrue(self.d.state["on"])
        self.assertFalse(self.d.state["stale"])
        self.assertNotIn("error",self.d.state)

    async def test_verified_address_survives_later_uncertain_write_without_replay(self):
        self.c.button.side_effect=ConnectionError("uncertain delivery")
        with self.assertRaisesRegex(AdapterError,"not repeated"):
            await self.svc.command(self.d.id,"key","UP")
        self.c.button.assert_awaited_once_with("UP")
        self.assertEqual(HomeService(self.folder.name).get(self.d.id).config["ip"],NEW)

    async def test_outer_timeout_does_not_retry_a_possibly_delivered_key(self):
        self.a._client.side_effect=None
        self.a._client.return_value=self.c
        async def delayed(_):await asyncio.Event().wait()
        self.c.button.side_effect=delayed
        with patch("app.core.service.COMMAND_TIMEOUT",.02):
            with self.assertRaisesRegex(AdapterError,"didn't respond"):
                await self.svc.command(self.d.id,"key","UP")
        self.c.button.assert_awaited_once_with("UP")
