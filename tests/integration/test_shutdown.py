"""Integration tests: the server shuts down promptly while a browser has the panel open.

The UI keeps /api/v1/events open all the time (on a kiosk, forever). The server must still
exit within a few seconds on SIGTERM / `systemctl restart`, and run its own shutdown
(which disconnects the adapters) instead of waiting for that stream to close."""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

from tests.helpers import DemoServer, free_port

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def open_event_stream(url: str) -> tuple[threading.Thread, dict]:
    """Opens the live event stream like the UI does and reads it until the server ends it."""
    seen: dict = {"opened": threading.Event(), "ended": False, "error": None}

    def read():
        try:
            with urllib.request.urlopen(f"{url}/api/v1/events", timeout=30) as r:
                seen["opened"].set()
                while r.readline():
                    pass
            seen["ended"] = True
        except Exception as e:   # noqa: BLE001 - recorded for the assertion message
            seen["error"] = repr(e)
            seen["opened"].set()

    t = threading.Thread(target=read, daemon=True)
    t.start()
    if not seen["opened"].wait(5):
        raise RuntimeError("The event stream didn't open")
    return t, seen


class ShutdownWithOpenPanel(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_cli_refuses_fixture_mode_on_canonical_port_without_creating_data(self):
        data = os.path.join(self.dir, "refused")
        result = subprocess.run([sys.executable, "-m", "app.main", "--demo", "--host", "127.0.0.1",
                                 "--port", "8080", "--data", data], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("internal tests", result.stderr)
        self.assertFalse(os.path.exists(data))

    def test_stop_ends_event_streams_and_runs_service_shutdown(self):
        server = DemoServer(self.dir).start()
        service = server.app.state.service
        stopped = threading.Event()
        real_stop = service.stop

        async def stop():
            stopped.set()
            await real_stop()
        service.stop = stop

        streams = [open_event_stream(server.url) for _ in range(2)]   # e.g. the kiosk and a phone
        started = time.monotonic()
        server.stop()
        took = time.monotonic() - started

        self.assertFalse(server.thread.is_alive(), "the server is still waiting for connections")
        self.assertLess(took, 3)
        self.assertTrue(stopped.is_set(), "service.stop() didn't run")
        for t, seen in streams:
            t.join(3)
            self.assertIsNone(seen["error"])
            self.assertTrue(seen["ended"], "the event stream wasn't ended by the server")

    @unittest.skipIf(sys.platform == "win32", "SIGTERM is POSIX-only")
    def test_sigterm_exits_within_seconds_while_the_panel_is_open(self):
        port = free_port()
        logs = os.path.join(self.dir, "logs")
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.main", "--demo", "--host", "127.0.0.1", "--port", str(port),
             "--data", os.path.join(self.dir, "data"), "--logs", logs],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            url = f"http://127.0.0.1:{port}"
            for _ in range(200):
                try:
                    urllib.request.urlopen(f"{url}/api/v1/state", timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                self.fail("The server didn't start")
            t, seen = open_event_stream(url)

            started = time.monotonic()
            proc.send_signal(signal.SIGTERM)
            code = proc.wait(timeout=10)
            took = time.monotonic() - started

            # uvicorn re-raises SIGTERM once it has shut down cleanly (systemd counts that as a clean stop)
            self.assertIn(code, (0, -signal.SIGTERM))
            self.assertLess(took, 5)
            t.join(3)
            self.assertTrue(seen["ended"], seen["error"])
            with open(os.path.join(logs, "homepanel.log"), encoding="utf-8") as f:
                log = f.read()
            self.assertIn("Application shutdown complete", log)
            self.assertNotIn("timeout graceful shutdown exceeded", log)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    unittest.main()
