"""Integration tests for the API layer: the real server in demo mode, called over HTTP."""
import json
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request

from tests.helpers import DemoServer


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir).start()
        cls.port = cls.server.port

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def test_state_has_no_secrets(self):
        status, data = self.call("GET", "/state")
        self.assertEqual(status, 200)
        self.assertTrue(data["devices"])
        for d in data["devices"]:
            self.assertNotIn("config", d)

    def test_command_and_errors(self):
        status, d = self.call("POST", "/devices/lr-ceiling/command", {"action": "brightness", "value": 42})
        self.assertEqual((status, d["state"]["brightness"]), (200, 42))
        status, err = self.call("POST", "/devices/lr-plug/command", {"action": "color", "value": "#ffffff"})
        self.assertEqual(status, 400)
        self.assertIn("can't", err["error"])
        status, _ = self.call("POST", "/devices/nope/command", {"action": "power", "value": True})
        self.assertEqual(status, 404)

    def test_scene_and_all_off(self):
        status, res = self.call("POST", "/scenes/movie/run")
        self.assertEqual(status, 200)
        self.assertEqual(res["failed"], [])
        status, res = self.call("POST", "/all-off", {"room": "Living room"})
        self.assertEqual(status, 200)

    def test_health_and_logs(self):
        status, h = self.call("GET", "/health")
        self.assertTrue(h["ok"])
        self.assertIn("demo", h["adapters"])
        status, logs = self.call("GET", "/logs")
        self.assertEqual(status, 200)
        self.assertIsInstance(logs["logs"], list)

    def test_energy_and_automations(self):
        status, e = self.call("GET", "/devices/kt-fridge/energy")
        self.assertEqual((status, len(e["days"])), (200, 7))
        status, a = self.call("POST", "/automations", {"when": {"type": "time", "at": "21:15", "days": [5, 6]},
                                                       "do": {"type": "all_off"}})
        self.assertEqual(status, 200)
        self.assertEqual(a["name"], "All off at 21:15")
        status, err = self.call("POST", "/automations", {"when": {"type": "time", "at": "nope"}, "do": {"type": "all_off"}})
        self.assertEqual(status, 400)
        status, listing = self.call("GET", "/automations")
        self.assertIn(a["id"], [x["id"] for x in listing["automations"]])
        status, _ = self.call("POST", f"/automations/{a['id']}/run")
        self.assertEqual(status, 200)
        status, _ = self.call("DELETE", f"/automations/{a['id']}")
        self.assertEqual(status, 200)
        status, sun = self.call("GET", "/sun")
        self.assertEqual(status, 200)
        status, err = self.call("PUT", "/settings", {"latitude": "200"})
        self.assertEqual(status, 400)

    def test_ui_served(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as r:
            self.assertIn(b"HomePanel", r.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/js/app.js", timeout=5) as r:
            self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()
