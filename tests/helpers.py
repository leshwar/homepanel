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
