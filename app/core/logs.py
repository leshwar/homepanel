"""Logging: console + rotating file + an in-memory buffer the Diagnostics screen reads."""
from __future__ import annotations

import collections
import logging
import logging.handlers
import os

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class RingBuffer(logging.Handler):
    def __init__(self, size: int = 500):
        super().__init__()
        self.records: collections.deque = collections.deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append({"time": record.created, "level": record.levelname,
                                 "logger": record.name, "message": self.format(record)})
        except Exception:
            pass


ring = RingBuffer()
LOG_PATH: str | None = None


def setup_logging(log_dir: str, debug: bool = False) -> str:
    os.makedirs(log_dir, exist_ok=True)
    global LOG_PATH
    path = os.path.join(log_dir, "homepanel.log")
    LOG_PATH = path
    level = logging.DEBUG if debug else logging.INFO
    fmt = logging.Formatter(FORMAT)

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # 5 files x 2 MB keeps about a week of normal use without filling the SD card
    filelog = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=5)
    filelog.setFormatter(fmt)
    root.addHandler(filelog)

    ring.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(ring)

    # Chatty libraries: only warnings unless --debug
    for noisy in ("uvicorn.access", "asyncio", "websockets", "aiowebostv", "kasa", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.DEBUG if debug else logging.WARNING)
    return path
