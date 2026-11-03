"""Sunrise and sunset times, computed locally (no internet).

Uses the well-known "Almanac for Computers" sunrise equation (US Naval
Observatory, 1990); accurate to about a minute, which is plenty for
"turn the porch light on at sunset".
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone, tzinfo

ZENITH = 90.833  # official sunrise/sunset: sun's upper edge on the horizon, with refraction


def _event_utc_hours(day: date, lat: float, lon: float, rising: bool) -> float | None:
    n = day.timetuple().tm_yday
    lng_hour = lon / 15
    t = n + ((6 if rising else 18) - lng_hour) / 24
    m = 0.9856 * t - 3.289
    rad = math.radians
    sun_l = (m + 1.916 * math.sin(rad(m)) + 0.020 * math.sin(rad(2 * m)) + 282.634) % 360
    ra = math.degrees(math.atan(0.91764 * math.tan(rad(sun_l)))) % 360
    ra += (math.floor(sun_l / 90) * 90) - (math.floor(ra / 90) * 90)   # same quadrant as L
    ra /= 15
    sin_dec = 0.39782 * math.sin(rad(sun_l))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(rad(ZENITH)) - sin_dec * math.sin(rad(lat))) / (cos_dec * math.cos(rad(lat)))
    if cos_h > 1 or cos_h < -1:
        return None   # polar day/night: the sun doesn't rise or set that day
    h = (360 - math.degrees(math.acos(cos_h))) if rising else math.degrees(math.acos(cos_h))
    h /= 15
    local_mean = h + ra - 0.06571 * t - 6.622
    return (local_mean - lng_hour) % 24


def sun_event(day: date, lat: float, lon: float, event: str, tz: tzinfo | None = None) -> datetime | None:
    """Time of 'sunrise' or 'sunset' on the given local day, as an aware datetime in tz."""
    tz = tz or datetime.now().astimezone().tzinfo
    ut = _event_utc_hours(day, lat, lon, rising=(event == "sunrise"))
    if ut is None:
        return None
    result = datetime.combine(day, time(0), tzinfo=timezone.utc) + timedelta(hours=ut)
    local = result.astimezone(tz)
    # The UTC calendar day can differ from the local one (e.g. US west coast sunsets are after 00:00 UTC).
    if local.date() < day:
        local += timedelta(days=1)
    elif local.date() > day:
        local -= timedelta(days=1)
    return local
