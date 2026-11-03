"""Power history for plugs that report watts, stored in SQLite (data/history.db).

Samples are kept for 60 days. Energy (kWh) is computed by integrating power over
time, ignoring gaps longer than 10 minutes (when the plug or the panel was off).
"""
from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
import time
from datetime import datetime, timedelta

MIN_INTERVAL = 60          # seconds between stored samples per device
MAX_GAP = 600              # don't integrate across gaps longer than this
KEEP_DAYS = 60


class History:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS samples (device_id TEXT, ts REAL, watts REAL)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_samples ON samples (device_id, ts)")

    @contextlib.contextmanager
    def _conn(self):
        """A connection that commits on success and is always closed."""
        c = sqlite3.connect(self.path, timeout=5)
        try:
            with c:
                yield c
        finally:
            c.close()

    # --- writing ------------------------------------------------------------
    def record(self, device_id: str, watts: float, ts: float | None = None) -> bool:
        ts = ts or time.time()
        if ts - self._last.get(device_id, 0) < MIN_INTERVAL:
            return False
        self._last[device_id] = ts
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO samples VALUES (?, ?, ?)", (device_id, ts, float(watts)))
        return True

    def bulk_insert(self, rows: list[tuple[str, float, float]]) -> None:
        with self._lock, self._conn() as c:
            c.executemany("INSERT INTO samples VALUES (?, ?, ?)", rows)

    def has_data(self) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM samples LIMIT 1").fetchone() is not None

    def prune(self) -> None:
        cutoff = time.time() - KEEP_DAYS * 86400
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))

    def forget(self, device_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM samples WHERE device_id = ?", (device_id,))

    # --- reading ------------------------------------------------------------
    def _samples(self, device_id: str, since: float) -> list[tuple[float, float]]:
        with self._conn() as c:
            return c.execute("SELECT ts, watts FROM samples WHERE device_id = ? AND ts >= ? ORDER BY ts",
                             (device_id, since)).fetchall()

    def energy_by_day(self, device_id: str, days: int = 7) -> list[dict]:
        """kWh per local calendar day, oldest first, including today."""
        today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=days - 1)
        buckets = {(start + timedelta(days=i)).date().isoformat(): 0.0 for i in range(days)}
        rows = self._samples(device_id, start.timestamp())
        for (t0, w0), (t1, _w1) in zip(rows, rows[1:]):
            dt = t1 - t0
            if dt <= 0 or dt > MAX_GAP:
                continue
            day = datetime.fromtimestamp(t0).astimezone().date().isoformat()
            if day in buckets:
                buckets[day] += w0 * dt / 3_600_000      # W·s → kWh
        return [{"date": d, "kwh": round(v, 3)} for d, v in buckets.items()]

    def power_series(self, device_id: str, hours: int = 24, points: int = 96) -> list[dict]:
        """Average watts in evenly sized buckets over the last `hours`."""
        now = time.time()
        since = now - hours * 3600
        size = hours * 3600 / points
        sums = [0.0] * points
        counts = [0] * points
        for ts, w in self._samples(device_id, since):
            i = min(points - 1, int((ts - since) / size))
            sums[i] += w
            counts[i] += 1
        return [{"t": round(since + (i + 0.5) * size), "w": round(sums[i] / counts[i], 1) if counts[i] else None}
                for i in range(points)]

    async def summary(self, device_id: str, days: int = 7) -> dict:
        def work():
            daily = self.energy_by_day(device_id, days)
            return {"days": daily, "today_kwh": daily[-1]["kwh"] if daily else 0,
                    "week_kwh": round(sum(d["kwh"] for d in daily), 3),
                    "power": self.power_series(device_id)}
        return await asyncio.to_thread(work)
