"""Current weather and the next hours, for the resting clock and the weather tile.

Off unless the user turns it on (Settings → Location and presence), because it is
the panel's only call to the internet that isn't for a device: it sends the saved
location, rounded to about 1 km, to Open-Meteo (free, no account or key). Results
are cached, and when there's no location, no internet or the source fails, the
panel just doesn't show weather.

The rest of HomePanel only sees the neutral shape returned by `current()`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

from .net import http

log = logging.getLogger("homepanel.weather")

SOURCE_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_SECONDS = 20 * 60          # fresh weather at most every 20 minutes
RETRY_SECONDS = 5 * 60           # after a failure, wait before asking again
STALE_SECONDS = 3 * 60 * 60      # keep showing the last good reading this long if the source is down
HOURS_AHEAD = 12                 # how many coming hours the tile gets

# WMO weather codes → (condition, label). Conditions are what the UI draws icons for.
_CODES: list[tuple[tuple[int, ...], str, str]] = [
    ((0,), "clear", "Clear"),
    ((1, 2), "partly-cloudy", "Partly cloudy"),
    ((3,), "cloudy", "Cloudy"),
    ((45, 48), "fog", "Fog"),
    ((51, 53, 55, 56, 57), "drizzle", "Drizzle"),
    ((61, 63, 65, 66, 67, 80, 81, 82), "rain", "Rain"),
    ((71, 73, 75, 77, 85, 86), "snow", "Snow"),
    ((95, 96, 99), "storm", "Thunderstorm"),
]
CONDITIONS = tuple(c for _, c, _ in _CODES)


def describe(code: Any) -> tuple[str, str]:
    """WMO weather code → (condition, label). Unknown codes count as cloudy."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "cloudy", "Cloudy"
    for codes, cond, label in _CODES:
        if code in codes:
            return cond, label
    return "cloudy", "Cloudy"


def _num(v: Any) -> int | None:
    return None if v is None else round(float(v))


def parse_hours(data: Any) -> list[dict]:
    """The hourly part of the forecast → [{at, hour, temperature, rain, condition, label, is_day}].

    `at` is when the hour starts (seconds since 1970), `hour` its hour of the day where the
    weather is (0–23), `rain` the chance of rain or snow in percent, or None if not given.
    Hours the source left incomplete are skipped; a forecast without hours gives []."""
    hourly = data.get("hourly") if isinstance(data, dict) else None
    if not isinstance(hourly, dict):
        return []
    try:
        offset = int(data.get("utc_offset_seconds") or 0)
    except (TypeError, ValueError):
        offset = 0
    times = hourly.get("time") or []
    def column(name):
        values = hourly.get(name) or []
        return lambda i: values[i] if i < len(values) else None
    temp, rain, code, day = (column(n) for n in ("temperature_2m", "precipitation_probability", "weather_code", "is_day"))
    hours = []
    for i, t in enumerate(times):
        try:
            at = int(t)
            if temp(i) is None:
                continue
            cond, label = describe(code(i))
            chance = _num(rain(i))
            hours.append({"at": at, "hour": ((at + offset) // 3600) % 24, "temperature": _num(temp(i)),
                          "rain": None if chance is None else max(0, min(100, chance)),
                          "condition": cond, "label": label, "is_day": bool(1 if day(i) is None else day(i))})
        except (TypeError, ValueError):
            continue                # times not given as seconds, or a broken hour: leave it out
    return hours


def parse(data: Any, unit: str) -> dict:
    """Open-Meteo forecast JSON → the panel's neutral weather shape. Raises ValueError if malformed."""
    try:
        cur = data["current"]
        daily = data.get("daily") or {}
        cond, label = describe(cur.get("weather_code"))
        highs, lows = daily.get("temperature_2m_max") or [None], daily.get("temperature_2m_min") or [None]
        return {
            "available": True,
            "temperature": _num(cur["temperature_2m"]),
            "feels_like": _num(cur.get("apparent_temperature")),
            "high": _num(highs[0]),
            "low": _num(lows[0]),
            "unit": unit,
            "condition": cond,
            "label": label,
            "is_day": bool(cur.get("is_day", 1)),
            "hours": parse_hours(data),
        }
    except (KeyError, TypeError, ValueError, IndexError) as e:
        raise ValueError(f"unexpected weather data: {e}") from None


Fetch = Callable[[str], Awaitable[Any]]


async def _default_fetch(url: str) -> Any:
    return await http("GET", url, timeout=8.0)


class Weather:
    def __init__(self, settings: Callable[[], dict], fetch: Fetch | None = None,
                 clock: Callable[[], float] = time.time):
        self._settings = settings
        self._fetch = fetch or _default_fetch
        self._clock = clock
        self._key: tuple | None = None
        self._data: dict | None = None
        self._fetched_at = 0.0       # last good reading
        self._tried_at = 0.0         # last attempt (good or bad)
        self._lock = asyncio.Lock()

    def _request(self) -> tuple[tuple, str] | None:
        s = self._settings()
        if not s.get("weather_enabled") or s.get("latitude") is None or s.get("longitude") is None:
            return None
        unit = "C" if str(s.get("temperature_unit", "F")).upper() == "C" else "F"
        lat, lon = round(float(s["latitude"]), 2), round(float(s["longitude"]), 2)
        base = os.environ.get("HOMEPANEL_WEATHER_URL", SOURCE_URL)
        query = urlencode({
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code,is_day",
            "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": "celsius" if unit == "C" else "fahrenheit",
            "timezone": "auto", "timeformat": "unixtime",
            "forecast_days": 2,             # the next hours can run past midnight; "daily" [0] is still today
        })
        return (lat, lon, unit, base), f"{base}?{query}"

    async def current(self) -> dict:
        """The latest weather, or {"available": False, "reason": ...}. Never raises."""
        req = self._request()
        if req is None:
            return {"available": False, "reason": "off"}
        key, url = req
        async with self._lock:          # several screens asking at once share one request
            now = self._clock()
            if key != self._key:        # location, unit or source changed: start over
                self._key, self._data, self._fetched_at, self._tried_at = key, None, 0.0, 0.0
            stale = self._data is None or now - self._fetched_at >= CACHE_SECONDS
            if stale and (not self._tried_at or now - self._tried_at >= RETRY_SECONDS):
                self._tried_at = now
                try:
                    self._data, self._fetched_at = parse(await self._fetch(url), key[2]), now
                except Exception as e:  # offline, DNS, HTTP error, bad JSON: just hide the weather
                    log.info("Weather unavailable: %s", e)
        if self._data is not None and now - self._fetched_at < STALE_SECONDS:
            ahead = [h for h in self._data.get("hours", []) if h["at"] > now][:HOURS_AHEAD]   # never an hour that has begun
            return {**self._data, "hours": ahead, "updated": self._fetched_at}
        return {"available": False, "reason": "unavailable"}
