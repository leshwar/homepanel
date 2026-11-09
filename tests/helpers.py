"""Shared helpers for the test suites."""
import socket
import threading
import time

from app.main import create_app, make_server


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class DemoServer:
    """Runs the real HomePanel server (demo mode) in a background thread.
    sign_in=True shows the profile picker (Owner password: homepanel; Sam: one tap)."""

    def __init__(self, data_dir: str, sign_in: bool = False):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.app = create_app(data_dir, demo=True, port=self.port, sign_in=sign_in)
        self.server = make_server(self.app, "127.0.0.1", self.port, log_config=None)
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


class FakeJsonServer:
    """A tiny local web service answering fixed JSON per path, e.g. to stand in for the
    location lookup services. routes = {"/json/": (200, {...}), ...}; unknown paths get 404.
    `requests` records each path asked for (with its query string)."""

    def __init__(self, routes: dict):
        import json
        from http.server import BaseHTTPRequestHandler, HTTPServer

        server = self
        self.routes = routes
        self.requests: list[str] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                server.requests.append(self.path)
                status, data = server.routes.get(self.path.split("?")[0], (404, {"error": "not found"}))
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# Sample answers in the shape the real location services send.
IPAPI_SEATTLE = {"ip": "203.0.113.7", "city": "Seattle", "region": "Washington", "region_code": "WA",
                 "country_name": "United States", "country_code": "US", "latitude": 47.6062, "longitude": -122.3321}
IPWHOIS_LYON = {"ip": "203.0.113.8", "success": True, "city": "Lyon", "region": "Auvergne-Rhône-Alpes",
                "region_code": "ARA", "country": "France", "country_code": "FR", "latitude": 45.764, "longitude": 4.8357}
REVERSE_SEATTLE = {"latitude": 47.61, "longitude": -122.33, "city": "Seattle", "locality": "Seattle",
                   "principalSubdivision": "Washington", "principalSubdivisionCode": "US-WA",
                   "countryName": "United States of America (the)", "countryCode": "US"}
