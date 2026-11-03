"""Schedules and automations: "when X, do Y".

An automation is stored as:

    {
      "id": "a1b2c3", "name": "Porch light at sunset", "enabled": true,
      "when": {"type": "time", "at": "07:00", "days": [0,1,2,3,4]}      # 0 = Monday
           |  {"type": "sun", "event": "sunset", "offset_min": -15}
           |  {"type": "presence", "event": "all_away" | "someone_home"},
      "do":   {"type": "scene", "scene_id": "movie"}
           |  {"type": "all_off"}
           |  {"type": "command", "device_id": "...", "action": "power", "value": true},
      "last_run": 1730000000.0, "last_result": "ok"
    }

Everything runs through HomeService, so automations use the same middleware,
logging and retries as taps on the screen.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta

from .adapter import AdapterError
from .sun import sun_event

log = logging.getLogger("homepanel.automations")

CHECK_EVERY = 15
WINDOW = 120          # fire if we're within 2 minutes after the target (survives restarts)
WHEN_TYPES = ("time", "sun", "presence")
DO_TYPES = ("scene", "all_off", "command")


class Automations:
    def __init__(self, service):
        self.svc = service

    @property
    def items(self) -> list[dict]:
        return self.svc.store.automations

    # --- editing ------------------------------------------------------------
    def save(self, data: dict) -> dict:
        when, do = data.get("when") or {}, data.get("do") or {}
        if when.get("type") not in WHEN_TYPES:
            raise AdapterError("Choose when it should run.")
        if do.get("type") not in DO_TYPES:
            raise AdapterError("Choose what it should do.")
        if when["type"] == "time":
            try:
                hh, mm = (int(x) for x in str(when.get("at", "")).split(":"))
                assert 0 <= hh < 24 and 0 <= mm < 60
            except Exception:
                raise AdapterError("Time should look like 07:30.")
            when["at"] = f"{hh:02d}:{mm:02d}"
            when["days"] = sorted({int(d) for d in when.get("days", range(7)) if 0 <= int(d) <= 6}) or list(range(7))
        if when["type"] == "sun":
            if when.get("event") not in ("sunrise", "sunset"):
                raise AdapterError("Choose sunrise or sunset.")
            when["offset_min"] = int(when.get("offset_min") or 0)
            if self._location() is None:
                raise AdapterError("Set your location first (Settings → Location and presence).")
        if when["type"] == "presence" and when.get("event") not in ("all_away", "someone_home"):
            raise AdapterError("Choose 'everyone leaves' or 'someone comes home'.")
        if do["type"] == "scene" and not any(s["id"] == do.get("scene_id") for s in self.svc.store.scenes):
            raise AdapterError("Choose a scene.")
        if do["type"] == "command" and do.get("device_id") not in self.svc.store.devices:
            raise AdapterError("Choose a device.")

        aid = data.get("id") or uuid.uuid4().hex[:8]
        old = next((a for a in self.items if a["id"] == aid), {})
        item = {"id": aid, "name": (data.get("name") or "").strip() or self.describe(when, do),
                "enabled": bool(data.get("enabled", True)), "when": when, "do": do,
                "last_run": old.get("last_run"), "last_result": old.get("last_result"),
                "last_key": old.get("last_key")}
        self.svc.store.automations = [a for a in self.items if a["id"] != aid] + [item]
        self.svc.store.save()
        return self.public(item)

    def delete(self, aid: str) -> None:
        self.svc.store.automations = [a for a in self.items if a["id"] != aid]
        self.svc.store.save()

    # --- describing ---------------------------------------------------------
    def describe(self, when: dict, do: dict) -> str:
        if do["type"] == "scene":
            what = next((s["name"] for s in self.svc.store.scenes if s["id"] == do.get("scene_id")), "Scene")
        elif do["type"] == "all_off":
            what = "All off"
        else:
            d = self.svc.store.devices.get(do.get("device_id"))
            what = f"{d.name if d else 'Device'} {'on' if do.get('value') else 'off'}"
        if when["type"] == "time":
            return f"{what} at {when['at']}"
        if when["type"] == "sun":
            return f"{what} at {when['event']}"
        return f"{what} when {'everyone leaves' if when['event'] == 'all_away' else 'someone comes home'}"

    def public(self, a: dict) -> dict:
        out = {k: v for k, v in a.items() if k != "last_key"}
        nxt = self.next_run(a)
        out["next_run"] = nxt.timestamp() if nxt else None
        return out

    def list(self) -> list[dict]:
        return [self.public(a) for a in self.items]

    # --- timing -------------------------------------------------------------
    def _location(self):
        s = self.svc.store.settings
        try:
            return float(s["latitude"]), float(s["longitude"])
        except (KeyError, TypeError, ValueError):
            return None

    def _target_on(self, a: dict, day) -> datetime | None:
        when = a["when"]
        if when["type"] == "time":
            if day.weekday() not in when.get("days", range(7)):
                return None
            hh, mm = (int(x) for x in when["at"].split(":"))
            return datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm).astimezone()
        if when["type"] == "sun":
            loc = self._location()
            if not loc:
                return None
            t = sun_event(day, loc[0], loc[1], when["event"])
            return t + timedelta(minutes=when.get("offset_min", 0)) if t else None
        return None

    def next_run(self, a: dict, now: datetime | None = None) -> datetime | None:
        if not a.get("enabled") or a["when"]["type"] == "presence":
            return None
        now = now or datetime.now().astimezone()
        for i in range(8):
            t = self._target_on(a, (now + timedelta(days=i)).date())
            if t and t > now:
                return t
        return None

    def due(self, a: dict, now: datetime) -> str | None:
        """A unique key for the occurrence that should fire now, or None."""
        if not a.get("enabled"):
            return None
        for day in (now.date(), (now - timedelta(days=1)).date()):   # handles just-after-midnight
            t = self._target_on(a, day)
            if t and 0 <= (now - t).total_seconds() < WINDOW:
                return t.isoformat()
        return None

    # --- running ------------------------------------------------------------
    async def execute(self, a: dict, reason: str = "") -> str:
        do = a["do"]
        try:
            if do["type"] == "scene":
                r = await self.svc.run_scene(do["scene_id"])
                result = "ok" if not r["failed"] else f"{len(r['failed'])} device(s) didn't respond"
            elif do["type"] == "all_off":
                n = await self.svc.all_off()
                result = f"ok, turned off {n}"
            else:
                await self.svc.command(do["device_id"], do.get("action", "power"), do.get("value"))
                result = "ok"
        except Exception as e:
            result = f"failed: {e}"
        a["last_run"], a["last_result"] = time.time(), result
        self.svc.store.save()
        log.info("Automation '%s' ran%s: %s", a["name"], f" ({reason})" if reason else "", result)
        self.svc.publish({"type": "automation", "name": a["name"], "result": result})
        return result

    async def run_now(self, aid: str) -> dict:
        a = next((x for x in self.items if x["id"] == aid), None)
        if not a:
            raise KeyError(aid)
        await self.execute(a, "run by hand")
        return self.public(a)

    async def on_presence(self, event: str) -> None:
        for a in list(self.items):
            if a.get("enabled") and a["when"]["type"] == "presence" and a["when"].get("event") == event:
                await self.execute(a, event.replace("_", " "))

    async def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now().astimezone()
        for a in list(self.items):
            key = self.due(a, now)
            if key and a.get("last_key") != key:
                a["last_key"] = key
                await self.execute(a, "scheduled")

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("Automation check failed")
            await asyncio.sleep(CHECK_EVERY)
