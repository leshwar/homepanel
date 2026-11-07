"""Unit tests for app/main.py helpers."""
import unittest
import contextlib
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.main import GRACEFUL_SHUTDOWN_SECONDS, create_app, main, make_server, ui_cache_header


class NativeEntryPointTests(unittest.TestCase):
    def test_public_help_has_no_separate_demo_workflow(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as result:
            main(["--help"])
        self.assertEqual(result.exception.code, 0)
        self.assertNotIn("--demo", out.getvalue())
        self.assertNotIn("--sign-in", out.getvalue())
        self.assertIn("--data", out.getvalue())

    def test_internal_fixtures_cannot_use_8080_public_interfaces_or_live_data(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "homepanel.json").write_text("{}")
            for args in (["--demo"],
                         ["--demo", "--host", "127.0.0.1", "--port", "18080"],
                         ["--demo", "--host", "0.0.0.0", "--port", "18080", "--data", directory],
                         ["--demo", "--host", "127.0.0.1", "--port", "18080", "--data", directory]):
                with self.subTest(args=args), patch("app.main.setup_logging") as logging, contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as result:
                        main(args)
                    self.assertEqual(result.exception.code, 2)
                    logging.assert_not_called()


class ServerShutdown(unittest.IsolatedAsyncioTestCase):
    async def test_server_gives_up_on_open_connections_after_a_few_seconds(self):
        import tempfile
        server = make_server(create_app(tempfile.mkdtemp(), demo=True), "127.0.0.1", 0)
        self.assertEqual(server.config.timeout_graceful_shutdown, GRACEFUL_SHUTDOWN_SECONDS)
        self.assertLessEqual(GRACEFUL_SHUTDOWN_SECONDS, 5)

    async def test_shutdown_ends_live_event_streams_first(self):
        import tempfile
        app = create_app(tempfile.mkdtemp(), demo=True)
        server = make_server(app, "127.0.0.1", 0)
        calls = []

        class FakeService:
            def end_streams(self):
                calls.append("end_streams")

        app.state.service = FakeService()
        server.servers = []                       # not serving: nothing to close
        server.lifespan = type("L", (), {"shutdown": staticmethod(lambda: _done(calls))})()
        await server.shutdown()
        self.assertEqual(calls, ["end_streams", "lifespan shutdown"])


async def _done(calls):
    calls.append("lifespan shutdown")


class CachePolicy(unittest.TestCase):
    def test_ui_files_are_always_revalidated(self):
        for path in ("/", "/index.html", "/app.css", "/js/app.js", "/js/glass.js"):
            with self.subTest(path=path):
                self.assertEqual(ui_cache_header(path), "no-cache")

    def test_api_and_images_are_left_alone(self):
        for path in ("/api/v1/state", "/api/v1/photos/abc.jpg/image", "/favicon.png"):
            with self.subTest(path=path):
                self.assertIsNone(ui_cache_header(path))


if __name__ == "__main__":
    unittest.main()
