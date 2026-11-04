"""Shared helpers for the test suites."""
import socket
import threading
import time

import uvicorn

from app.main import create_app


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class DemoServer:
    """Runs the real HomePanel server (demo mode) in a background thread."""

    def __init__(self, data_dir: str):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(uvicorn.Config(create_app(data_dir, demo=True), host="127.0.0.1",
                                                   port=self.port, log_config=None))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> "DemoServer":
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("Demo server didn't start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(5)


class FakeWeatherSource:
    """A tiny local stand-in for the weather source (Open-Meteo's response shape).
    Point the server at it with the HOMEPANEL_WEATHER_URL environment variable."""

    def __init__(self, temperature=53.6, code=61, high=58.2, low=44.9):
        import json
        from http.server import BaseHTTPRequestHandler, HTTPServer

        body = json.dumps({"current": {"temperature_2m": temperature, "weather_code": code, "is_day": 1},
                           "daily": {"temperature_2m_max": [high], "temperature_2m_min": [low]}}).encode()
        source = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                source.requests.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.requests: list[str] = []
        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1/forecast"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
