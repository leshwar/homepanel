"""Voice commands end to end: POST /api/v1/voice on the real demo server, and the mic sheet in a real
browser (Playwright), with the browser's speech recogniser faked so no microphone or internet is needed.
These tests have their own server, so the commands they run don't change other tests' devices."""
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    if os.environ.get("REQUIRE_UI_TESTS"):
        raise
    sync_playwright = None

from tests.helpers import DemoServer


def call(port, method, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def device_state(port, did):
    _, s = call(port, "GET", "/state")
    return next(d for d in s["devices"] if d["id"] == did)["state"]


class VoiceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir).start()
        cls.port = cls.server.port

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def voice(self, text, **kw):
        return call(self.port, "POST", "/voice", {"text": text, **kw})

    def test_a_sentence_runs_commands(self):
        status, r = self.voice("Turn on the kettle and set the bedside lamp to 40%")
        self.assertEqual(status, 200)
        self.assertEqual(r["say"], "Turned on the Kettle plug and set the Bedside lamp to 40%.")
        self.assertEqual(r["heard"], "Turn on the kettle and set the bedside lamp to 40%")
        self.assertTrue(r["understood"])
        self.assertEqual([(d["device_id"], d["action"], d["value"]) for d in r["done"]],
                         [("kt-kettle", "power", True), ("bd-lamp", "brightness", 40)])
        self.assertTrue(device_state(self.port, "kt-kettle")["on"])
        self.assertEqual(device_state(self.port, "bd-lamp")["brightness"], 40)
        self.voice("turn off the kettle")

    def test_ambiguous_sentence_offers_choices(self):
        status, r = self.voice("set the lamp to 30 percent")
        self.assertEqual((status, r["question"]), (200, "Which lamp?"))
        self.assertEqual([(c["label"], c["detail"]) for c in r["choices"]],
                         [("Floor lamp", "Living room"), ("Bedside lamp", "Bedroom")])
        self.assertEqual(r["done"], [])
        _, r = self.voice(r["choices"][0]["text"])
        self.assertEqual(r["say"], "Set the Floor lamp to 30%.")
        self.assertEqual(device_state(self.port, "lr-lamp")["brightness"], 30)

    def test_everything_off_asks_first(self):
        status, r = self.voice("turn everything off")
        self.assertEqual(status, 200)
        self.assertRegex(r["confirm"], r"^Turn off everything\? \d+ devices are on\.$")
        self.assertEqual(r["done"], [])
        self.assertTrue(device_state(self.port, "lr-ceiling")["on"])          # nothing happened
        _, r = self.voice("turn everything off", confirm=True)
        self.assertRegex(r["say"], r"^Turned off \d+ devices\.$")
        self.assertFalse(device_state(self.port, "lr-ceiling")["on"])
        call(self.port, "POST", "/devices/lr-ceiling/command", {"action": "power", "value": True})

    def test_tv_vacuum_scene_and_question(self):
        _, r = self.voice("open YouTube on the living room TV")
        self.assertEqual(r["say"], "Opened YouTube on the Samsung TV.")
        self.assertEqual(device_state(self.port, "lr-tv")["app"], "youtube")
        _, r = self.voice("vacuum the kitchen and the hall")
        self.assertEqual(r["say"], "Sent the Robot vacuum to clean the Kitchen and the Hall.")
        _, r = self.voice("send the vacuum home")
        self.assertEqual(r["say"], "Sent the Robot vacuum home.")
        _, r = self.voice("run good morning")
        self.assertEqual(r["say"], "Ran Good morning.")
        _, r = self.voice("is the kettle on?")
        self.assertIn("The Kettle plug is", r["say"])

    def test_not_understood_and_bad_requests(self):
        status, r = self.voice("sing me a song")
        self.assertEqual((status, r["understood"]), (200, False))
        self.assertIn("don't know how", r["say"])
        status, r = call(self.port, "POST", "/voice", {})
        self.assertEqual(status, 400)
        self.assertIn("Say or type a command", r["error"])
        status, r = self.voice("   ")
        self.assertEqual(status, 400)
        status, r = self.voice("turn on the kettle " + "x" * 400)     # long input is cut, not an error
        self.assertEqual(status, 200)
        self.assertLessEqual(len(r["heard"]), 300)


# A stand-in for the browser's SpeechRecognition. window.__speech says what it "hears":
#   text  – the words, delivered one at a time as interim results, then as a final result
#   hold  – keep listening after the last word until stop() (push-to-talk)
#   error – fail with this error code instead (e.g. "network", like Chromium without Google)
FAKE_SPEECH = """
window.__speech = { text: "turn on the bedside lamp", hold: false, error: "", started: 0 };
class FakeRecognition {
  start() {
    const cfg = window.__speech; cfg.started++;
    setTimeout(() => {
      if (cfg.error) { this.onerror?.({ error: cfg.error }); this.onend?.(); return; }
      this.onsoundstart?.();
      const words = cfg.text.split(" ");
      let i = 0;
      const next = () => {
        i++;
        const r = [{ transcript: words.slice(0, i).join(" ") }];
        r.isFinal = i === words.length;
        this.onresult?.({ results: [r] });
        if (i < words.length) this._t = setTimeout(next, 60);
        else if (!cfg.hold) setTimeout(() => this.onend?.(), 30);
      };
      next();
    }, 80);
  }
  stop() { clearTimeout(this._t); setTimeout(() => this.onend?.(), 10); }
  abort() {}
}
window.SpeechRecognition = FakeRecognition;
window.webkitSpeechRecognition = FakeRecognition;
"""
NO_SPEECH = "delete window.SpeechRecognition; delete window.webkitSpeechRecognition;"


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class VoiceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.server = DemoServer(cls.dir).start()
        cls.port = cls.server.port
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:  # browser binaries not downloaded
            cls.pw.stop()
            cls.server.stop()
            if os.environ.get("REQUIRE_UI_TESTS"):
                raise
            raise unittest.SkipTest(f"chromium not available: {e}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.errors = []
        self.pages = []

    def tearDown(self):
        for p in self.pages:
            p.close()
        self.assertEqual(self.errors, [])

    def open(self, script, width=393, height=852, notice_seen=False):
        page = self.browser.new_page(viewport={"width": width, "height": height}, has_touch=True,
                                     reduced_motion="reduce")
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.add_init_script(script + ("localStorage.setItem('voice_notice_seen', 'true');" if notice_seen else ""))
        page.goto(f"http://127.0.0.1:{self.port}/")
        page.wait_for_selector("#voice-btn")
        self.pages.append(page)
        return page

    def toast(self, page, text):
        page.wait_for_function("t => { const el = document.querySelector('#toast'); return !el.hidden && el.textContent === t; }",
                               arg=text)

    def test_typed_box_where_the_browser_cant_listen(self):
        page = self.open(NO_SPEECH)
        page.click("#voice-btn")
        page.wait_for_selector("#voice-text")
        self.assertEqual(page.locator(".voice-notice").count(), 0)      # no speech, so nothing to warn about
        self.assertGreater(page.locator("[data-voice-say]").count(), 0)  # suggestions from this home
        page.fill("#voice-text", "turn on the kettle")
        page.press("#voice-text", "Enter")
        self.toast(page, "Turned on the Kettle plug.")
        self.assertTrue(page.locator("#voice").is_hidden())
        self.assertTrue(device_state(self.port, "kt-kettle")["on"])
        call(self.port, "POST", "/voice", {"text": "turn off the kettle"})

    def test_typed_box_choices_confirm_and_cancel(self):
        page = self.open(NO_SPEECH)
        page.click("#voice-btn")
        page.fill("#voice-text", "set the lamp to 30 percent")
        page.click(".voice-form button[type=submit]")
        page.wait_for_selector("text=Which lamp?")
        page.click("[data-voice-choice]:has-text('Bedside lamp')")
        self.toast(page, "Set the Bedside lamp to 30%.")
        self.assertEqual(device_state(self.port, "bd-lamp")["brightness"], 30)

        page.click("#voice-btn")
        page.fill("#voice-text", "turn everything off")
        page.press("#voice-text", "Enter")
        page.wait_for_selector("[data-voice-confirm]")
        self.assertIn("Turn off everything?", page.text_content("#voice"))
        page.click("#voice [data-voice-close]:has-text('Cancel')")
        self.assertTrue(page.locator("#voice").is_hidden())
        self.assertTrue(device_state(self.port, "lr-ceiling")["on"])     # cancelled: still on

        page.click("#voice-btn")
        page.fill("#voice-text", "sing me a song")
        page.press("#voice-text", "Enter")
        page.wait_for_selector(".voice-bubble.panel.error")
        self.assertTrue(page.locator("#voice").is_visible())             # not understood: stays open to try again

    def test_speech_tap_shows_notice_once_then_live_words(self):
        page = self.open(FAKE_SPEECH)
        page.click("#voice-btn")
        page.wait_for_selector(".voice-notice")
        self.assertIn("Google", page.text_content(".voice-notice"))
        self.assertIn("Apple", page.text_content(".voice-notice"))
        page.click("[data-voice-ok]")
        page.wait_for_selector("#voice-heard:has-text('turn on')")         # interim words appear as they come
        self.toast(page, "Turned on the Bedside lamp.")
        self.assertTrue(device_state(self.port, "bd-lamp")["on"])
        # second time: straight to listening, no notice
        page.evaluate("window.__speech.text = 'turn off the bedside lamp'")
        page.click("#voice-btn")
        self.toast(page, "Turned off the Bedside lamp.")
        self.assertEqual(page.evaluate("window.__speech.started"), 2)
        self.assertFalse(device_state(self.port, "bd-lamp")["on"])

    def test_push_to_talk_listens_until_let_go(self):
        page = self.open(FAKE_SPEECH, width=820, height=1180, notice_seen=True)
        page.evaluate("Object.assign(window.__speech, {text: 'start the vacuum', hold: true})")
        box = page.locator("#voice-btn").bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.wait_for_selector(".voice-sheet.listening #voice-heard:has-text('start the vacuum')")
        page.wait_for_timeout(500)                                        # still holding: still listening
        self.assertTrue(page.locator(".voice-mic.live").is_visible())
        page.mouse.up()
        self.toast(page, "Started the Robot vacuum.")
        self.assertEqual(device_state(self.port, "lr-vacuum")["activity"], "cleaning")
        call(self.port, "POST", "/voice", {"text": "send the vacuum home"})

    def test_speech_that_fails_falls_back_to_typing(self):
        page = self.open(FAKE_SPEECH + "window.__speech.error = 'network';", width=1280, height=720, notice_seen=True)
        page.click("#voice-btn")
        page.wait_for_selector("#voice-text")
        self.assertIn("isn't working on this screen", page.text_content("#voice"))
        page.fill("#voice-text", "what's on in the bedroom?")
        page.press("#voice-text", "Enter")
        # the answer to a question is a toast too
        page.wait_for_function("() => { const t = document.querySelector('#toast'); "
                               "return !t.hidden && /in the Bedroom/.test(t.textContent); }")

    def test_mic_fits_the_header_at_every_size(self):
        for w, h in ((393, 852), (820, 1180), (1280, 720), (720, 1280)):
            with self.subTest(size=f"{w}x{h}"):
                page = self.open(NO_SPEECH, width=w, height=h)
                box = page.locator("#voice-btn").bounding_box()
                self.assertGreaterEqual(min(box["width"], box["height"]), 48)
                self.assertLessEqual(box["x"] + box["width"], w)
                self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                page.click("#voice-btn")
                sheet = page.locator("#voice").bounding_box()
                self.assertLessEqual(sheet["x"] + sheet["width"], w + 1)
                for b in page.locator("#voice button:visible").all():
                    bb = b.bounding_box()
                    self.assertGreaterEqual(bb["height"], 48, b.inner_text())


if __name__ == "__main__":
    unittest.main()
