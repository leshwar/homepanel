"""Unit tests for app/main.py helpers."""
import unittest

from app.main import GRACEFUL_SHUTDOWN_SECONDS, create_app, make_server, ui_cache_header


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
