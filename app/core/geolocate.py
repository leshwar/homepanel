"""Find the home's location for sunrise/sunset and weather, only when the user taps
"Use my location" in Settings.

Two ways, both returned in one neutral shape {latitude, longitude, place_name, source}:

- "device": the browser gave coordinates (it asks the user first). We only turn them
  into a place name, by asking BigDataCloud's free reverse-geocoding service.
- "approximate": no device location (plain-HTTP pages can't ask for it). We look up
  the home's public internet address at ipapi.co, then ipwho.is as a backup. Both are
  free, need no key, and see only the address the request comes from.

Coordinates are rounded to 2 decimals (about 1 km) before they're sent or saved.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

from .adapter import AdapterError
from .net import HttpError, http

log = logging.getLogger("homepanel.geolocate")

IP_SOURCES = ("https://ipapi.co/json/", "https://ipwho.is/")
REVERSE_URL = "https://api.bigdatacloud.net/data/reverse-geocode-client"

Fetch = Callable[[str], Awaitable[Any]]


class SourceError(Exception):
    """One source didn't give a usable answer. `busy` = it said we asked too often."""

    def __init__(self, msg: str, busy: bool = False):
        super().__init__(msg)
        self.busy = busy


def round2(v: Any) -> float:
    return round(float(v), 2)


def check_coords(lat: Any, lon: Any) -> tuple[float, float]:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise AdapterError("The location should be two numbers: latitude and longitude.") from None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise AdapterError("Latitude should be between -90 and 90 and longitude between -180 and 180.")
    return round2(lat), round2(lon)


def place_label(city: str | None, region_code: str | None, region: str | None,
                country: str | None, country_code: str | None) -> str:
    """'Seattle, WA' in the US, 'Lyon, France' elsewhere; falls back to region or country."""
    city = (city or "").strip()
    rc = (region_code or "").strip()
    if "-" in rc:                      # BigDataCloud gives 'US-WA'
        rc = rc.split("-", 1)[1]
    if (country_code or "").upper() == "US" and rc:
        second = rc
    else:
        second = (country or "").strip()
    first = city or (region or "").strip()
    parts = [p for p in (first, second) if p]
    if len(parts) == 2 and parts[0] == parts[1]:
        parts = parts[:1]
    return ", ".join(parts)[:40]


def parse_ipapi(d: Any) -> dict:
    if not isinstance(d, dict):
        raise SourceError("unexpected answer")
    if d.get("error"):
        reason = str(d.get("reason") or d.get("message") or "error")
        raise SourceError(reason, busy="rate" in reason.lower() or "quota" in reason.lower())
    try:
        lat, lon = round2(d["latitude"]), round2(d["longitude"])
    except (KeyError, TypeError, ValueError):
        raise SourceError("no coordinates in answer") from None
    return {"latitude": lat, "longitude": lon,
            "place_name": place_label(d.get("city"), d.get("region_code"), d.get("region"),
                                      d.get("country_name"), d.get("country_code"))}


def parse_ipwhois(d: Any) -> dict:
    if not isinstance(d, dict):
        raise SourceError("unexpected answer")
    if d.get("success") is False:
        msg = str(d.get("message") or "error")
        raise SourceError(msg, busy="limit" in msg.lower())
    try:
        lat, lon = round2(d["latitude"]), round2(d["longitude"])
    except (KeyError, TypeError, ValueError):
        raise SourceError("no coordinates in answer") from None
    return {"latitude": lat, "longitude": lon,
            "place_name": place_label(d.get("city"), d.get("region_code"), d.get("region"),
                                      d.get("country"), d.get("country_code"))}


def parse_reverse(d: Any) -> str:
    if not isinstance(d, dict):
        return ""
    return place_label(d.get("city") or d.get("locality"), d.get("principalSubdivisionCode"),
                       d.get("principalSubdivision"), d.get("countryName"), d.get("countryCode"))


async def _default_fetch(url: str) -> Any:
    return await http("GET", url, timeout=8.0)


class Geolocator:
    def __init__(self, fetch: Fetch | None = None):
        self._fetch = fetch or _default_fetch

    def _ip_sources(self) -> list[tuple[str, Callable[[Any], dict]]]:
        urls = os.environ.get("HOMEPANEL_GEO_IP_URLS")
        urls = [u.strip() for u in urls.split(",") if u.strip()] if urls else list(IP_SOURCES)
        parsers = [parse_ipapi, parse_ipwhois]
        return [(u, parsers[min(i, len(parsers) - 1)]) for i, u in enumerate(urls)]

    async def _get(self, url: str) -> Any:
        try:
            return await self._fetch(url)
        except HttpError as e:
            raise SourceError(f"HTTP {e.status}", busy=e.status == 429) from None
        except Exception as e:          # offline, DNS, timeout, TLS
            raise SourceError(f"{type(e).__name__}: {e}") from None

    async def place_name(self, lat: float, lon: float) -> str:
        base = os.environ.get("HOMEPANEL_GEO_REVERSE_URL", REVERSE_URL)
        url = f"{base}?{urlencode({'latitude': lat, 'longitude': lon, 'localityLanguage': 'en'})}"
        try:
            return parse_reverse(await self._get(url))
        except SourceError as e:
            log.info("Place name lookup failed: %s", e)
            return ""                    # the coordinates are still useful without a name

    async def lookup(self, latitude: Any = None, longitude: Any = None) -> dict:
        if latitude is not None and longitude is not None:
            lat, lon = check_coords(latitude, longitude)
            return {"latitude": lat, "longitude": lon, "place_name": await self.place_name(lat, lon),
                    "source": "device"}
        busy = False
        for url, parse in self._ip_sources():
            try:
                found = parse(await self._get(url))
                return {**found, "source": "approximate"}
            except SourceError as e:
                busy = busy or e.busy
                log.info("Location lookup at %s failed: %s", url.split("/")[2], e)
        if busy:
            raise AdapterError("The location services are busy right now. Try again in a few minutes, "
                               "or enter your location by hand.")
        raise AdapterError("Couldn't look up your location. Check the panel's internet connection, "
                           "or enter your location by hand.")
