"""Who's home? Detects family phones on the Wi-Fi.

Each person is a name + their phone's IP address (reserve a fixed IP for each
phone in your router). Someone counts as away only after their phone hasn't been
seen for AWAY_AFTER seconds, because phones sleep their Wi-Fi to save battery.

Events (used by automations):
  "all_away"     — the last person left
  "someone_home" — the first person came back
"""
from __future__ import annotations

import asyncio
import logging
import time

from .net import mac_from_arp

log = logging.getLogger("homepanel.presence")

CHECK_EVERY = 30
AWAY_AFTER = 10 * 60
PROBE_PORTS = (62078, 5353, 80, 443, 8009)   # iPhone sync port, mDNS, web, Chromecast


async def probe(ip: str) -> bool:
    """True if the phone answers. A refused connection still proves it's there."""
    for port in PROBE_PORTS:
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(ip, port), 1.0)
            w.close()
            return True
        except ConnectionRefusedError:
            return True
        except (OSError, asyncio.TimeoutError):
            continue
    return mac_from_arp(ip) is not None   # the connect attempts refresh the ARP cache


class Presence:
    def __init__(self, get_people, on_event):
        self._get_people = get_people        # () -> [{"name","ip"}]
        self._on_event = on_event            # async (event: str) -> None
        self.status: dict[str, dict] = {}    # name -> {"home": bool|None, "last_seen": ts}
        self._anyone_home: bool | None = None

    def snapshot(self) -> list[dict]:
        people = self._get_people() or []
        return [{"name": p["name"], "ip": p.get("ip", ""), **self.status.get(p["name"], {"home": None, "last_seen": None})}
                for p in people]

    async def check_once(self, prober=probe, now: float | None = None) -> None:
        now = now or time.time()
        people = [p for p in (self._get_people() or []) if p.get("ip")]
        if not people:
            self._anyone_home = None
            return
        seen = await asyncio.gather(*(prober(p["ip"]) for p in people))
        for p, ok in zip(people, seen, strict=True):
            st = self.status.setdefault(p["name"], {"home": None, "last_seen": None})
            if ok:
                st.update(home=True, last_seen=now)
            elif st["last_seen"] is None or now - st["last_seen"] > AWAY_AFTER:
                st["home"] = False
        anyone = any(self.status.get(p["name"], {}).get("home") for p in people)
        before, self._anyone_home = self._anyone_home, anyone
        if before is None:
            return   # first check after start-up: learn, don't trigger
        if before and not anyone:
            log.info("Everyone has left")
            await self._on_event("all_away")
        elif not before and anyone:
            log.info("Someone came home")
            await self._on_event("someone_home")

    async def run(self) -> None:
        while True:
            try:
                await self.check_once()
            except Exception:
                log.exception("Presence check failed")
            await asyncio.sleep(CHECK_EVERY)
