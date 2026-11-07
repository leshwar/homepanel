"""Integration tests for the API layer: the real server in demo mode, called over HTTP."""
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

from tests.helpers import (IPWHOIS_LYON, REVERSE_SEATTLE, DemoServer, FakeJsonServer,
                           FakeWeatherSource)


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

    def test_quick_commands_to_one_device_end_on_the_last_one(self):
        # Two colors sent 10 ms apart over HTTP (like the color wheel and then a preset). The demo
        # light answers each after a random 30-120 ms, so without ordering the first could land last.
        import threading
        import time
        for _ in range(8):
            first = threading.Thread(target=self.call, args=("POST", "/devices/lr-lamp/command",
                                                             {"action": "color", "value": "#ff0000"}))
            first.start()
            time.sleep(0.01)
            self.call("POST", "/devices/lr-lamp/command", {"action": "color", "value": "#5ee07a"})
            first.join()
            _, state = self.call("GET", "/state")
            lamp = next(d for d in state["devices"] if d["id"] == "lr-lamp")
            self.assertEqual(lamp["state"]["color"], {"r": 94, "g": 224, "b": 122})

    def test_state_has_no_secrets(self):
        status, data = self.call("GET", "/state")
        self.assertEqual(status, 200)
        self.assertTrue(data["devices"])
        for d in data["devices"]:
            self.assertNotIn("config", d)

    def test_all_off_for_devices_without_a_room(self):
        self.call("PATCH", "/devices/kt-kettle", {"room": ""})
        try:
            self.call("POST", "/devices/kt-kettle/command", {"action": "power", "value": True})
            self.call("POST", "/devices/kt-pendant/command", {"action": "power", "value": True})
            status, res = self.call("POST", "/all-off", {"room": ""})
            self.assertEqual((status, res["turned_off"]), (200, 1))
            _, s = self.call("GET", "/state")
            on = {d["id"]: d["state"].get("on") for d in s["devices"]}
            self.assertEqual((on["kt-kettle"], on["kt-pendant"]), (False, True))
        finally:
            self.call("PATCH", "/devices/kt-kettle", {"room": "Kitchen"})

    def test_home_layout_is_saved_for_every_screen(self):
        _, s = self.call("GET", "/state")
        default = s["settings"]["home_layout"]
        self.assertEqual(default["widgets"][0]["type"], "clock")
        try:
            mine = {"widgets": [{"id": "zone-us", "type": "zone", "size": "2x1",
                                 "options": {"tz": "America/Los_Angeles", "label": "US"}}]}
            status, saved = self.call("PUT", "/settings", {"home_layout": mine})
            self.assertEqual(status, 200)
            _, s = self.call("GET", "/state")
            self.assertEqual(s["settings"]["home_layout"], saved["home_layout"])
            self.assertEqual(s["settings"]["home_layout"]["widgets"][0]["options"]["tz"], "America/Los_Angeles")
            status, err = self.call("PUT", "/settings", {"home_layout": {"widgets": [{"id": "a", "type": "clock", "size": "9x9"}]}})
            self.assertEqual(status, 400)
            self.assertIn("Widget size", err["error"])
        finally:
            self.call("PUT", "/settings", {"home_layout": None})
        _, s = self.call("GET", "/state")
        self.assertEqual(s["settings"]["home_layout"], default)

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

    def test_robot_vacuum_commands(self):
        status, d = self.call("POST", "/devices/lr-vacuum/command", {"action": "clean", "value": "start"})
        self.assertEqual((status, d["state"]["activity"]), (200, "cleaning"))
        status, d = self.call("POST", "/devices/lr-vacuum/command", {"action": "dock"})
        self.assertEqual((status, d["state"]["activity"]), (200, "returning"))
        status, err = self.call("POST", "/devices/lr-vacuum/command", {"action": "clean", "value": "turbo"})
        self.assertEqual(status, 400)
        self.assertIn("cleaning command", err["error"])
        status, _ = self.call("POST", "/devices/lr-plug/command", {"action": "dock"})
        self.assertEqual(status, 400)

    def test_light_effects(self):
        _, st = self.call("GET", "/state")
        strip = next(d for d in st["devices"] if d["id"] == "lr-strip")
        for cap in ("effects", "music", "segments", "toggles"):
            self.assertIn(cap, strip["caps"])
        self.assertEqual({e["group"] for e in strip["meta"]["effects"]}, {"Scenes", "DIY", "Snapshots"})
        self.assertEqual(strip["meta"]["segments"], 10)

        status, d = self.call("POST", "/devices/lr-strip/command", {"action": "set_effect", "value": "diy-movie-night"})
        self.assertEqual((status, d["state"]["effect"], d["state"]["color_mode"]), (200, "diy-movie-night", "effect"))
        status, d = self.call("POST", "/devices/lr-strip/command",
                              {"action": "set_music", "value": {"mode": "energic", "sensitivity": 35}})
        self.assertEqual((status, d["state"]["music"], d["state"]["effect"]), (200, {"mode": "energic", "sensitivity": 35}, None))
        status, d = self.call("POST", "/devices/lr-strip/command",
                              {"action": "set_segments", "value": {"segments": [9], "color": "#ff5cb8"}})
        self.assertEqual((status, d["state"]["segments"][9], d["state"]["color_mode"]), (200, "#ff5cb8", "segments"))
        status, d = self.call("POST", "/devices/lr-strip/command",
                              {"action": "set_toggle", "value": {"id": "sync", "on": True}})
        self.assertEqual((status, d["state"]["toggles"]["sync"]), (200, True))
        status, _ = self.call("POST", "/devices/lr-strip/command", {"action": "update_effects"})
        self.assertEqual(status, 200)
        # plain-language refusals
        for dev, body, words in (("lr-strip", {"action": "set_effect", "value": "nope"}, "doesn't have the option"),
                                 ("lr-lamp", {"action": "set_effect", "value": "scene-sunset"}, "can't play scenes"),
                                 ("lr-strip", {"action": "set_segments", "value": {"segments": [12], "color": "#fff"}},
                                  "numbered 0 to 9"),
                                 ("kt-pendant", {"action": "set_music", "value": "energic"}, "can't follow music")):
            status, err = self.call("POST", f"/devices/{dev}/command", body)
            self.assertEqual(status, 400, body)
            self.assertIn(words, err["error"])

    def test_vacuum_rooms_suction_and_map(self):
        status, d = self.call("POST", "/devices/lr-vacuum/command", {"action": "clean_rooms", "value": [2]})
        self.assertEqual((status, d["state"]["activity"]), (200, "cleaning"))
        self.assertEqual([r["name"] for r in d["meta"]["rooms"]][:2], ["Living room", "Kitchen"])
        status, err = self.call("POST", "/devices/lr-vacuum/command", {"action": "set_suction", "value": "turbo"})
        self.assertEqual(status, 400)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/v1/devices/lr-vacuum/map", timeout=5) as r:
            self.assertEqual(r.headers["Content-Type"].split(";")[0], "image/svg+xml")
            self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])   # can't run scripts
            self.assertTrue(r.read().startswith(b"<svg"))
        status, _ = self.call("GET", "/devices/lr-plug/map")
        self.assertEqual(status, 400)

    def test_search_all_brands_and_add_a_result(self):
        status, _ = self.call("DELETE", "/devices/bd-fan")
        self.assertIn(status, (200, 204))
        status, r = self.call("POST", "/discover")
        self.assertEqual(status, 200)
        self.assertIn("demo", r["searched"])          # other test suites may register extra pretend brands
        self.assertEqual(r["failed"], [])
        fan = next(f for f in r["found"] if f["uid"] == "bd-fan")
        self.assertEqual((fan["adapter"], fan["added"]), ("demo", False))
        self.assertTrue(all("config" not in f for f in r["found"]))
        status, d = self.call("POST", "/devices", {"adapter": fan["adapter"], "uid": fan["uid"], "room": "Bedroom"})
        self.assertEqual((status, d["name"]), (200, "Fan plug"))
        _, r = self.call("POST", "/discover")
        self.assertTrue(next(f for f in r["found"] if f["uid"] == "bd-fan")["added"])

    def test_health_and_logs(self):
        status, h = self.call("GET", "/health")
        self.assertTrue(h["ok"])
        self.assertIn("unsupported", h)
        if sys.version_info[:2] != (3, 14):        # e.g. CI: the vacuum brand needs 3.14
            self.assertIn("Needs Python 3.14", h["unsupported"]["ecovacs"])
            self.assertNotIn("ecovacs", h["unavailable"])        # "not for this Python", not "not installed"
        self.assertNotIn("in_container", h)
        self.assertIn("phone_url", h)          # where to open the panel on a phone
        if h["phone_url"]:
            self.assertRegex(h["phone_url"], r"^http://[0-9.]+:\d+$")
        self.assertIn("demo", h["adapters"])
        status, logs = self.call("GET", "/logs")
        self.assertEqual(status, 200)
        self.assertIsInstance(logs["logs"], list)

    def test_native_startup_loads_all_supported_brand_libraries(self):
        status, health = self.call("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])
        self.assertGreater(health["devices"], 0)
        self.assertEqual(health["unavailable"], {})
        self.assertNotIn("in_container", self.call("GET", "/state")[1])

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

    def test_display_settings(self):
        status, s = self.call("PUT", "/settings", {"background": "night", "glass_transparency": 70})
        self.assertEqual((status, s["background"], s["glass_transparency"]), (200, "night", 70))
        status, err = self.call("PUT", "/settings", {"background": "neon"})
        self.assertEqual(status, 400)
        self.assertIn("Background", err["error"])
        self.call("PUT", "/settings", {"background": "sky", "glass_transparency": 45})

    def test_clock_face_setting(self):
        status, s = self.call("PUT", "/settings", {"clock_face": "words"})
        self.assertEqual((status, s["clock_face"]), (200, "words"))
        status, err = self.call("PUT", "/settings", {"clock_face": "sundial"})
        self.assertEqual(status, 400)
        self.assertIn("Clock face", err["error"])
        self.call("PUT", "/settings", {"clock_face": "digital"})

    def test_weather_from_source_and_hidden_without_it(self):
        status, w = self.call("GET", "/weather")
        self.assertEqual((status, w["available"]), (200, False))      # off until the user opts in
        source = FakeWeatherSource(temperature=21.4, code=0)
        os.environ["HOMEPANEL_WEATHER_URL"] = source.url
        try:
            self.call("PUT", "/settings", {"latitude": 47.61, "longitude": -122.33, "weather_enabled": True,
                                           "temperature_unit": "C"})
            status, w = self.call("GET", "/weather")
            self.assertEqual((status, w["available"], w["temperature"], w["unit"], w["condition"]),
                             (200, True, 21, "C", "clear"))
            self.assertIn("latitude=47.61", source.requests[0])
            self.call("GET", "/weather")
            self.assertEqual(len(source.requests), 1)                  # cached
            source.stop()
            os.environ["HOMEPANEL_WEATHER_URL"] = source.url.replace("/v1", "/gone/v1")   # new source, unreachable
            status, w = self.call("GET", "/weather")
            self.assertEqual((status, w["available"]), (200, False))   # no error, just no weather
        finally:
            os.environ.pop("HOMEPANEL_WEATHER_URL", None)
            self.call("PUT", "/settings", {"latitude": None, "longitude": None, "weather_enabled": False,
                                           "temperature_unit": "F"})

    def test_location_lookup_device_approximate_and_errors(self):
        svc = FakeJsonServer({"/ipapi/": (429, {"error": True, "reason": "RateLimited"}),
                              "/ipwho/": (200, IPWHOIS_LYON), "/reverse": (200, REVERSE_SEATTLE)})
        env = {"HOMEPANEL_GEO_IP_URLS": f"{svc.base}/ipapi/,{svc.base}/ipwho/",
               "HOMEPANEL_GEO_REVERSE_URL": f"{svc.base}/reverse"}
        os.environ.update(env)
        try:
            # coordinates from the device → only a place name is looked up, with rounded coordinates
            status, r = self.call("POST", "/location/lookup", {"latitude": 47.60621, "longitude": -122.33207})
            self.assertEqual((status, r), (200, {"latitude": 47.61, "longitude": -122.33,
                                                 "place_name": "Seattle, WA", "source": "device"}))
            self.assertEqual(svc.requests, ["/reverse?latitude=47.61&longitude=-122.33&localityLanguage=en"])
            # no device location → first service is rate-limited, the backup answers
            status, r = self.call("POST", "/location/lookup", {})
            self.assertEqual((status, r["place_name"], r["source"], r["latitude"]),
                             (200, "Lyon, France", "approximate", 45.76))
            self.assertEqual(svc.requests[1:], ["/ipapi/", "/ipwho/"])
            # nothing was saved
            self.assertIsNone(self.call("GET", "/state")[1]["settings"]["latitude"])
            status, err = self.call("POST", "/location/lookup", {"latitude": 123, "longitude": 0})
            self.assertEqual(status, 400)
            svc.stop()                                           # offline
            status, err = self.call("POST", "/location/lookup", {})
            self.assertEqual(status, 400)
            self.assertIn("enter your location by hand", err["error"])
        finally:
            for k in env:
                os.environ.pop(k, None)

    def _upload(self, data: bytes, content_type="image/png"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/photos?name=test.png", data=data,
                                     method="POST", headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_photo_upload_list_view_delete(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (640, 480), (30, 120, 200)).save(buf, "PNG")
        status, photo = self._upload(buf.getvalue())
        self.assertEqual(status, 200)
        status, listing = self.call("GET", "/photos")
        self.assertIn(photo["id"], [p["id"] for p in listing["photos"]])
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{photo['url']}", timeout=5) as r:
            self.assertTrue(r.headers["Content-Type"].startswith("image/"))
            self.assertGreater(len(r.read()), 100)
        status, _ = self.call("DELETE", f"/photos/{photo['id']}")
        self.assertEqual(status, 200)
        status, err = self._upload(b"definitely not an image", "image/jpeg")
        self.assertEqual(status, 400)
        self.assertIn("supported photo", err["error"])
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/v1/photos/..%2Fhomepanel.json/image", timeout=5)
            self.fail("path outside the photo folder was served")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def _send_image(self, method, path, data: bytes, content_type="image/tiff"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1{path}", data=data, method=method,
                                     headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_wallpaper_from_a_mac_tiff(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1200, 675), (20, 10, 60)).save(buf, "TIFF")      # like a picture pasted on a Mac
        status, w = self._send_image("POST", "/wallpapers?name=Pasted.tiff", buf.getvalue())
        self.assertEqual((status, w["width"], w["height"]), (200, 1200, 675))
        _, listing = self.call("GET", "/wallpapers")
        self.assertIn(w["id"], [x["id"] for x in listing["wallpapers"]])
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{w['url']}", timeout=5) as r:
            self.assertEqual(r.headers["Content-Type"], "image/jpeg")      # browsers can't show TIFF
            self.assertIn("private", r.headers["Cache-Control"])
        status, s = self.call("PUT", "/settings", {"background": "wallpaper", "wallpaper": w["id"], "wallpaper_dim": 30})
        self.assertEqual((status, s["background"], s["wallpaper"], s["wallpaper_dim"]), (200, "wallpaper", w["id"], 30))
        self.assertEqual(self.call("DELETE", f"/wallpapers/{w['id']}")[0], 200)
        _, s = self.call("GET", "/state")
        self.assertEqual(s["settings"]["wallpaper"], "shuffle")              # the one shown was removed
        self.call("PUT", "/settings", {"background": "sky"})

    def test_device_picture_put_get_delete(self):
        import io
        from PIL import Image
        img = Image.new("RGBA", (800, 500), (0, 0, 0, 0))
        img.paste((40, 60, 200, 255), (50, 50, 750, 450))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        status, d = self._send_image("PUT", "/devices/kt-kettle/picture", buf.getvalue(), "image/png")
        self.assertEqual(status, 200)
        self.assertTrue(d["picture_url"].endswith(".png"))
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{d['picture_url']}", timeout=5) as r:
            self.assertEqual(r.headers["Content-Type"], "image/png")
        status, d = self.call("DELETE", "/devices/kt-kettle/picture")
        self.assertEqual((status, d["picture_url"]), (200, ""))
        self.assertEqual(self.call("GET", "/devices/kt-kettle/picture")[0], 404)
        status, err = self._send_image("PUT", "/devices/kt-kettle/picture", b"nope", "image/png")
        self.assertEqual(status, 400)

    def test_tv_mac_address_can_be_set(self):
        status, d = self.call("PATCH", "/devices/bd-tv", {"mac": "a4:36:c7:1:2:3"})
        self.assertEqual((status, d["mac"]), (200, "A4:36:C7:01:02:03"))
        status, err = self.call("PATCH", "/devices/bd-tv", {"mac": "12345"})
        self.assertEqual(status, 400)
        self.assertIn("MAC", err["error"])
        _, state = self.call("GET", "/state")
        for dev in state["devices"]:
            self.assertNotIn("config", dev)            # only the MAC is exposed, never the rest

    def test_ui_files_are_never_served_stale(self):
        for path in ("/", "/app.css", "/js/app.js"):
            with self.subTest(path=path), urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
                self.assertEqual(r.headers.get("Cache-Control"), "no-cache")
                self.assertTrue(r.headers.get("ETag") or r.headers.get("Last-Modified") or path == "/")

    def test_ui_served(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as r:
            self.assertIn(b"HomePanel", r.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/js/app.js", timeout=5) as r:
            self.assertEqual(r.status, 200)

    def test_add_to_home_screen_files(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as r:
            html = r.read().decode()
        for tag in ('name="apple-mobile-web-app-capable"', 'viewport-fit=cover', 'rel="apple-touch-icon"', 'rel="manifest"'):
            self.assertIn(tag, html)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/manifest.webmanifest", timeout=5) as r:
            manifest = json.loads(r.read())
        self.assertEqual(manifest["display"], "standalone")
        for path in ["/icon-180.png", *(i["src"] for i in manifest["icons"])]:
            with self.subTest(path=path), urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
                self.assertEqual(r.headers.get("Content-Type"), "image/png")
                self.assertEqual(r.read(8), b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
