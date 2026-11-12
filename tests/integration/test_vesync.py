"""Core300S account/API/UI integration with fake async SDK, never real hardware."""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tests.helpers import DemoServer
from tests.integration.test_auth import Client
from tests.unit.test_vesync import FakeManager

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    if os.environ.get("REQUIRE_UI_TESTS"):
        raise
    sync_playwright = None


class VeSyncApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FakeManager.instances = []; FakeManager.login_error = None
        cls.patch = patch("pyvesync.VeSync", FakeManager); cls.patch.start()
        cls.dir = tempfile.mkdtemp(); cls.server = DemoServer(cls.dir, sign_in=True).start()
        cls.owner = Client(cls.server.url); cls.owner.sign_in(profile_id="owner", password="homepanel")

    @classmethod
    def tearDownClass(cls):
        cls.server.stop(); cls.patch.stop(); shutil.rmtree(cls.dir, ignore_errors=True)

    def test_protected_account_discovery_commands_and_scene_capture(self):
        owner = self.owner
        status, data, _ = owner.call("PUT", "/adapters/vesync/account",
                                    {"email": "fixture@example.com", "password": "fixture-password", "country": "US"})
        self.assertEqual(status, 200); self.assertNotIn("fixture-password", json.dumps(data))
        status, data, _ = owner.call("POST", "/adapters/vesync/actions/verify", {})
        self.assertEqual(status, 200, data)
        self.assertIn("Connected", data["message"])
        self.assertFalse([call for d in FakeManager.instances[-1].devices.air_purifiers for call in d.calls if call[0] != "refresh"])
        status, data, _ = owner.call("POST", "/adapters/vesync/discover", {})
        self.assertEqual(status, 200, data)
        found = data["found"]
        self.assertEqual(len(found), 1)
        status, device, _ = owner.call("POST", "/devices", {"adapter": "vesync", "uid": found[0]["uid"], "room": "Bedroom"})
        self.assertEqual(status, 200, device)
        did = device["id"]
        try:
            status, state, _ = owner.call("POST", f"/devices/{did}/command", {"action": "set_fan_speed", "value": "3"})
            self.assertEqual(status, 200, state); self.assertEqual(state["state"]["fan_speed"], "3")
            self.assertEqual(owner.call("POST", f"/devices/{did}/command", {"action": "set_fan_speed", "value": "9"})[0], 400)
            status, scene, _ = owner.call("POST", "/scenes", {"name": "Air", "capture": [did]})
            self.assertEqual(status, 200)
            self.assertIn({"device_id": did, "action": "set_fan_speed", "value": "3"}, scene["actions"])
            member = Client(self.server.url); member.sign_in(profile_id="sam")
            self.assertEqual(member.call("GET", "/adapters/vesync/account")[0], 403)
            self.assertEqual(member.call("POST", f"/devices/{did}/command", {"action": "power", "value": False})[0], 404)
            snapshot = owner.call("GET", "/state")[1]
            self.assertNotIn("fixture-password", json.dumps(snapshot))
            if sync_playwright:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    page = browser.new_page(viewport={"width": 393, "height": 852})
                    errors = []; page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(self.server.url)
                    page.click('[data-pick="owner"]'); page.fill('input[name=password]', "homepanel")
                    page.click('#signin button[type=submit]')
                    page.wait_for_selector("#app")
                    page.evaluate("async id => (await import('/js/sheet.js')).openDevice(id)", did)
                    page.wait_for_selector('#sheet[data-kind="purifier"] .purifier-stage')
                    self.assertIn("12", page.locator(".purifier-readings").inner_text())      # readings are the stage
                    self.assertEqual(page.locator("#sheet [data-tab]").all_inner_texts(), ["Mode", "Fan speed"])
                    page.click('[data-fan-mode="sleep"]')                                     # Mode is the first tab
                    page.wait_for_selector('[data-fan-mode="sleep"][aria-pressed="true"]')
                    page.click('#sheet [data-tab="speed"]')
                    page.click('[data-fan-speed="1"]')
                    page.wait_for_selector('[data-fan-speed="1"][aria-pressed="true"]')
                    for size in ("small", "medium", "large"):
                        page.evaluate("async size => (await import('/js/typography.js')).applyTypography(size)", size)
                        self.assertTrue(page.locator("#sheet").evaluate("e => e.scrollWidth<=e.clientWidth"))
                    self.assertEqual(errors, [])
                    browser.close()
            purifier = FakeManager.instances[-1].devices.air_purifiers[0]
            purifier.fail = True
            purifier.last_response.error_type = "rate_limit_error"
            self.assertEqual(owner.call("POST", f"/devices/{did}/command", {"action": "power", "value": False})[0], 400)
            calls = len(purifier.calls)
            status, error, _ = owner.call("POST", f"/devices/{did}/command", {"action": "power", "value": False})
            self.assertEqual(status, 400); self.assertIn("Retry in", error["error"])
            self.assertEqual(len(purifier.calls), calls)
        finally:
            owner.call("DELETE", f"/devices/{did}")
