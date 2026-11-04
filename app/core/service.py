"""
Service layer. The API layer calls only this class; it never imports an adapter.

Commands flow through a middleware pipeline before reaching the adapter:

    API ─► validate ─► normalize ─► log ─► timeout+retry ─► adapter.command()
                                                           │
             state cache ◄── optimistic merge ◄────────────┘ ─► live event to UI

Add your own middleware (rate limits, permissions, automation hooks …) with
service.use(fn). Each middleware is `async def mw(ctx, call_next)`.

Profiles (app/core/profiles.py): who is asking comes from `current_viewer`, set by
the API's auth middleware. `mw_access` refuses commands to devices the viewer's
profile can't see, and snapshot() / the event stream leave those devices out, so
a hidden device never reaches that browser.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import Counter
from dataclasses import asdict
from typing import Any, Awaitable, Callable

from .adapter import (ADAPTERS, Action, AdapterError, Cap, Clean, Device, DeviceAdapter, Found,
                      Key, PairingRequired, Pointer, missing_requirements, unsupported_reason)
from .automations import Automations
from .history import History
from .layout import LayoutError, clean_layout, default_layout, migrate_layout
from .net import in_container, normalize_mac, parse_color
from .photos import PhotoLibrary
from .presence import Presence
from .profiles import ADMIN, MEMBER, Profiles, Sessions, Viewer, current_viewer, hash_secret, sees
from .geolocate import Geolocator
from .weather import Weather
from .store import Store
from .voice import Voice

log = logging.getLogger("homepanel")

COMMAND_TIMEOUT = 10.0
BACKGROUNDS = ("sky", "ocean", "aurora", "night")   # sky: follows the weather and time of day
IDLE_SCREENS = ("clock", "photos")
CLOCK_FACES = ("digital", "analog", "words", "date", "night")
REFRESH_TIMEOUT = 8.0
OFFLINE_AFTER_FAILURES = 2


class CommandContext:
    def __init__(self, device: Device, adapter: DeviceAdapter, action: str, value: Any):
        self.device = device
        self.adapter = adapter
        self.action = action
        self.value = value
        self.started = time.monotonic()


Middleware = Callable[[CommandContext, Callable[[CommandContext], Awaitable[dict | None]]], Awaitable[dict | None]]


# ---------------------------------------------------------------------------
# Built-in middleware
# ---------------------------------------------------------------------------

async def mw_access(ctx: CommandContext, call_next):
    """Members only control the devices their profile can see. A hidden device answers
    exactly like one that doesn't exist (KeyError → 404), so it can't be probed."""
    if not sees(ctx.device.id):
        raise KeyError(ctx.device.id)
    return await call_next(ctx)


async def mw_validate(ctx: CommandContext, call_next):
    if ctx.action not in Action.ALL:
        raise AdapterError(f"Unknown action '{ctx.action}'")
    if ctx.action == Action.KEY:
        if ctx.value not in Key.ALL:
            raise AdapterError(f"Unknown remote key '{ctx.value}'")
        media_ok = ctx.value in Key.MEDIA and Cap.MEDIA in ctx.device.caps
        if Cap.REMOTE not in ctx.device.caps and not media_ok:
            raise AdapterError(f"{ctx.device.name} can't do '{ctx.value}'")
        return await call_next(ctx)
    if ctx.action == Action.CLEAN and ctx.value not in Clean.ALL:
        raise AdapterError(f"Unknown cleaning command '{ctx.value}'")
    if ctx.action in Action.OPTIONS:
        ids = {str(o.get("id")) for o in ctx.device.meta.get(Action.OPTIONS[ctx.action], [])}
        if str(ctx.value) not in ids:
            raise AdapterError(f"{ctx.device.name} doesn't have the option '{ctx.value}'")
    if ctx.action == Action.CLEAN_ROOMS:
        rooms = {str(r.get("id")) for r in ctx.device.meta.get("rooms", [])}
        picked = ctx.value if isinstance(ctx.value, list) else []
        if not picked or not {str(v) for v in picked} <= rooms:
            raise AdapterError("Pick at least one room from the list.")
    needed = Action.REQUIRES.get(ctx.action)
    if needed and needed not in ctx.device.caps:
        raise AdapterError(f"{ctx.device.name} can't do '{ctx.action}'")
    return await call_next(ctx)


def normalize_pointer(value: Any) -> dict:
    """Turn a pointer command into exactly one of {"dx","dy"}, {"click": True} or {"scroll": n}."""
    if not isinstance(value, dict):
        raise AdapterError("Pointer commands need a move, a click or a scroll.")

    def num(v: Any, limit: int) -> int:
        try:
            n = int(round(float(v)))
        except (TypeError, ValueError):
            raise AdapterError("Pointer moves must be numbers.") from None
        return max(-limit, min(limit, n))

    if value.get("click"):
        return {"click": True}
    if "scroll" in value:
        return {"scroll": num(value["scroll"], Pointer.MAX_SCROLL)}
    if "dx" in value or "dy" in value:
        return {"dx": num(value.get("dx", 0), Pointer.MAX_MOVE), "dy": num(value.get("dy", 0), Pointer.MAX_MOVE)}
    raise AdapterError("Pointer commands need a move, a click or a scroll.")


async def mw_normalize(ctx: CommandContext, call_next):
    a, v = ctx.action, ctx.value
    if a == Action.TOGGLE:  # adapters only ever see POWER
        ctx.action, ctx.value = Action.POWER, not bool(ctx.device.state.get("on"))
    elif a == Action.POWER:
        ctx.value = bool(v)
    elif a == Action.BRIGHTNESS:
        ctx.value = max(1, min(100, int(round(float(v)))))
    elif a == Action.VOLUME:
        ctx.value = max(0, min(100, int(round(float(v)))))
    elif a == Action.COLOR_TEMP:
        ctx.value = max(1500, min(9000, int(v)))
    elif a == Action.COLOR:
        ctx.value = parse_color(v)
    elif a == Action.MUTE:
        ctx.value = (not ctx.device.state.get("muted")) if v is None else bool(v)
    elif a == Action.POINTER:
        ctx.value = normalize_pointer(v)
    return await call_next(ctx)


async def mw_log(ctx: CommandContext, call_next):
    try:
        result = await call_next(ctx)
        (log.debug if ctx.action in Action.QUIET else log.info)("%s %s=%r ok (%.0f ms)", ctx.device.name, ctx.action, ctx.value,
                 (time.monotonic() - ctx.started) * 1000)
        return result
    except Exception as e:
        log.warning("%s %s=%r failed: %s", ctx.device.name, ctx.action, ctx.value, e)
        raise


async def mw_timeout_retry(ctx: CommandContext, call_next):
    last: Exception | None = None
    # A late pointer move is worse than a lost one, so those get one quick try.
    attempts, limit = (1, 3.0) if ctx.action in Action.QUIET else (2, COMMAND_TIMEOUT)
    for _attempt in range(attempts):
        try:
            return await asyncio.wait_for(call_next(ctx), limit)
        except (AdapterError, ValueError):
            raise                      # meaningful errors: don't retry
        except (asyncio.TimeoutError, OSError, ConnectionError) as e:
            last = e
            await asyncio.sleep(0.4)
    if isinstance(last, asyncio.TimeoutError):
        raise AdapterError(f"{ctx.device.name} didn't respond. Is it powered and on Wi-Fi?")
    raise AdapterError(f"Couldn't reach {ctx.device.name}: {last}")


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------

class HomeService:
    def __init__(self, data_dir: str, demo: bool = False):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.demo = demo
        self.store = Store(os.path.join(data_dir, "demo.json" if demo else "homepanel.json"))
        self.adapters: dict[str, DeviceAdapter] = {}
        self.unavailable: dict[str, list[str]] = {}   # adapter id -> missing python modules
        self.unsupported: dict[str, str] = {}         # adapter id -> why it can't run on this Python
        self._subscribers: dict[asyncio.Queue, Callable[[dict], bool] | None] = {}
        self._pollers: dict[str, asyncio.Task] = {}
        self._soon: dict[str, asyncio.TimerHandle] = {}   # pushed changes waiting to refresh
        self._failures: dict[str, int] = {}
        self._found: dict[tuple[str, str], Found] = {}
        self._found_ips: dict[str, Counter] = {}     # per brand: how many results the last search found at each address
        self._middleware: list[Middleware] = [mw_access, mw_validate, mw_normalize, mw_log, mw_timeout_retry]
        self.profiles = Profiles(self.store, Sessions(os.path.join(data_dir, "demo-sessions.json" if demo else "sessions.json")))
        self.history = History(os.path.join(data_dir, "demo-history.db" if demo else "history.db"))
        self.automations = Automations(self)
        self.photos = PhotoLibrary(os.path.join(data_dir, "demo-photos" if demo else "photos"))
        self.weather = Weather(lambda: self.store.settings)
        self.geo = Geolocator()          # only used when the user taps "Use my location"
        self.presence = Presence(lambda: self.store.settings.get("presence") or [], self.automations.on_presence)
        self.voice = Voice(self)                      # spoken/typed commands → the same command pipeline
        self._background: list[asyncio.Task] = []

    # --- middleware ---------------------------------------------------------
    def use(self, middleware: Middleware, index: int | None = None) -> None:
        """Insert custom middleware. Default: just before the adapter call."""
        self._middleware.insert(len(self._middleware) if index is None else index, middleware)

    async def _run_pipeline(self, ctx: CommandContext):
        async def terminal(c: CommandContext):
            return await c.adapter.command(c.device, c.action, c.value)

        handler = terminal
        for mw in reversed(self._middleware):
            handler = (lambda m, nxt: (lambda c: m(c, nxt)))(mw, handler)
        return await handler(ctx)

    # --- lifecycle ----------------------------------------------------------
    async def start(self) -> None:
        from .. import adapters  # noqa: F401  (imports every adapter module → @register)
        for aid, cls in ADAPTERS.items():
            if cls.hidden and not self.demo:
                continue
            reason = unsupported_reason(cls)
            if reason:
                self.unsupported[aid] = reason
                continue
            missing = missing_requirements(cls)
            if missing:
                self.unavailable[aid] = missing
                continue
            inst = cls(self.store.accounts.get(aid, {}), self.data_dir)
            try:
                await inst.start()
            except Exception as e:  # one broken adapter must not stop the panel
                log.exception("Adapter %s failed to start: %s", aid, e)
                continue
            inst.on_change = (lambda uid, aid=aid: self._changed(aid, uid))
            self.adapters[aid] = inst
        if self.demo and not self.store.devices:
            await self._seed_demo()
        self.profiles.migrate(self.store.settings)        # upgrading: one Owner who sees everything
        self._migrate_layouts()
        if self.demo and not self.photos.list():
            await asyncio.to_thread(self.photos.seed_demo)
        if self.demo and not self.history.has_data():
            await asyncio.to_thread(self._seed_demo_history)
        await asyncio.to_thread(self.history.prune)
        for d in self.store.devices.values():
            d.state = {"online": None}
            self._start_poller(d)
        self._background = [asyncio.create_task(self.automations.run()),
                            asyncio.create_task(self.presence.run())]

    async def stop(self) -> None:
        for t in [*self._pollers.values(), *self._background]:
            t.cancel()
        for h in self._soon.values():
            h.cancel()
        self._soon.clear()
        for a in self.adapters.values():
            try:
                await a.stop()
            except Exception:
                pass

    # --- events -------------------------------------------------------------
    def subscribe(self, allow: Callable[[dict], bool] | None = None) -> asyncio.Queue:
        """A queue of live events. `allow(event)` decides per event whether this listener
        gets it (the API passes one that checks the listener's profile each time)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers[q] = allow
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.pop(q, None)

    def publish(self, event: dict) -> None:
        for q, allow in list(self._subscribers.items()):
            try:
                if allow is not None and not allow(event):
                    continue
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
            except Exception:
                log.exception("Event filter failed")

    @staticmethod
    def event_visible(viewer: Viewer | None, event: dict) -> bool:
        """Device events only for profiles that can see the device; automation results only for admins."""
        if viewer is None:
            return True
        if event.get("type") == "device":
            return viewer.sees(event.get("device", {}).get("id", ""))
        if event.get("type") == "automation":
            return viewer.is_admin
        return True

    def _publish_device(self, d: Device) -> None:
        self.publish({"type": "device", "device": self.public_device(d)})

    def _publish_layout(self) -> None:
        self.publish({"type": "layout"})   # UI reloads the full snapshot

    # --- read models (what the API returns) ---------------------------------
    def public_device(self, d: Device) -> dict:
        out = asdict(d)
        out.pop("config", None)
        out["adapter_name"] = self.adapter_meta(d.adapter).get("name", d.adapter)
        out["pairing"] = bool(d.state.get("needs_pairing"))
        if d.kind == "tv":
            out["mac"] = d.config.get("mac") or ""   # not secret; shown so it can be checked or entered
        return out

    def adapter_meta(self, aid: str) -> dict:
        cls = ADAPTERS.get(aid)
        if not cls:
            return {}
        return {
            "id": cls.id, "name": cls.name, "brands": cls.brands, "kinds": list(cls.kinds),
            "description": cls.description, "can_discover": cls.can_discover,
            "account_fields": [f.to_dict() for f in cls.account_fields],
            "account_actions": cls.account_actions,
            "manual_fields": [f.to_dict() for f in cls.manual_fields],
            "account_set": bool(self.store.accounts.get(aid)),
            "available": aid in self.adapters,
            "missing": self.unavailable.get(aid, []),
            "unsupported": self.unsupported.get(aid, ""),
            "hidden": cls.hidden,
        }

    def snapshot(self) -> dict:
        """Everything the UI needs, for the person asking: a member gets only the devices
        (and scenes) their profile can see, and none of the admin-only lists."""
        viewer = current_viewer.get()
        admin = viewer is None or viewer.is_admin
        return {
            "devices": [self.public_device(d) for d in self.visible_devices()],
            "rooms": self.store.rooms,
            "scenes": [s for s in self.store.scenes if self.scene_visible(s)],
            "settings": self.settings(),
            "adapters": [self.adapter_meta(a) for a in ADAPTERS if not ADAPTERS[a].hidden or self.demo] if admin else [],
            "automations": self.automations.list() if admin else [],
            "presence": self.presence.snapshot() if admin else [],
            "me": self.profiles.public(viewer.profile) if viewer else None,
            "profiles": [self.profiles.public(p) for p in self.profiles.items] if viewer and viewer.is_admin else [],
            "demo": self.demo,
            "in_container": in_container(),
        }

    def visible_devices(self) -> list[Device]:
        return [d for d in self.store.devices.values() if sees(d.id)]

    def scene_visible(self, scene: dict) -> bool:
        """A member sees a scene only if they can see every device in it."""
        return all(sees(a["device_id"]) for a in scene.get("actions", []) if a["device_id"] in self.store.devices)

    def settings(self) -> dict:
        """Panel settings as the UI sees them. `home_layout` is the viewer's own Home page:
        their saved one, else the shared default, else the built-in default. There are no
        devices on Home (they're on the Rooms pages), so nothing in it can leak a hidden one."""
        viewer = current_viewer.get()
        s = dict(self.store.settings)
        if viewer is not None and not viewer.is_admin:
            s.pop("presence", None)          # phones' addresses: admins only
        s["home_layout"] = self.layout_for(viewer)
        return s

    def layout_for(self, viewer: Viewer | None) -> dict:
        layout = (viewer.profile.get("home_layout") if viewer else None) or self.store.settings.get("home_layout")
        return migrate_layout(layout) if layout else default_layout()

    def _migrate_layouts(self) -> None:
        """Home layouts saved before devices moved off the Home page: drop their device
        widgets, in the shared default and in every profile, and save once."""
        changed = False
        holders = [self.store.settings, *self.store.profiles]
        for h in holders:
            old = h.get("home_layout")
            new = migrate_layout(old)
            if new != old:
                h["home_layout"] = new
                changed = True
        if changed:
            self.store.save()
            log.info("Home pages updated: devices are on the Rooms pages now")

    def save_my_layout(self, layout: Any) -> dict:
        """Save the signed-in person's own Home page (None = back to the default)."""
        viewer = current_viewer.get()
        if viewer is None:
            raise AdapterError("Sign in to save your Home page.")
        try:
            clean = clean_layout(layout) if layout else None
        except LayoutError as e:
            raise AdapterError(str(e)) from None
        self.profiles.set_layout(viewer.id, clean)
        self._publish_layout()
        return {"home_layout": self.layout_for(viewer)}

    def get(self, device_id: str) -> Device:
        d = self.store.devices.get(device_id)
        if not d:
            raise KeyError(device_id)
        return d

    def _adapter_for(self, d: Device) -> DeviceAdapter:
        a = self.adapters.get(d.adapter)
        if not a:
            missing = self.unavailable.get(d.adapter)
            if missing:
                raise AdapterError(f"Support for this brand isn't installed (needs {', '.join(missing)}).")
            raise AdapterError(f"Unknown device type '{d.adapter}'")
        return a

    # --- commands -----------------------------------------------------------
    async def command(self, device_id: str, action: str, value: Any = None) -> dict:
        d = self.get(device_id)
        if not sees(d.id):                 # before anything below can mention the device
            raise KeyError(device_id)
        adapter = self._adapter_for(d)
        if d.state.get("needs_pairing"):
            raise AdapterError(f"{d.name} needs pairing first. Open it in Settings and choose Pair.")
        ctx = CommandContext(d, adapter, action, value)
        config_before = dict(d.config)
        changed = await self._run_pipeline(ctx) or {}
        if d.config != config_before:
            self.store.save()
        self._failures[d.id] = 0
        if action in Action.QUIET:          # nothing changed; don't flood the live events
            return self.public_device(d)
        d.state.update({"online": True, **changed})
        self._publish_device(d)
        # confirm the real state shortly after (devices sometimes ignore commands)
        asyncio.get_running_loop().call_later(1.5, lambda: asyncio.ensure_future(self.refresh(d.id)))
        return self.public_device(d)

    async def all_off(self, room: str | None = None) -> int:
        """Turn off what's on. room=None: everywhere; room="": devices that aren't in a room
        (no room, or a room that was deleted), which the UI shows as "Other"."""
        def in_room(d: Device) -> bool:
            if room is None:
                return True
            return d.room not in self.store.rooms if room == "" else d.room == room
        targets = [d for d in self.visible_devices()
                   if Cap.POWER in d.caps and d.state.get("on") and not d.keep_on and in_room(d)]
        results = await asyncio.gather(*(self.command(d.id, Action.POWER, False) for d in targets),
                                       return_exceptions=True)
        return sum(1 for r in results if not isinstance(r, Exception))

    def _changed(self, adapter_id: str, uid: str) -> None:
        """An adapter says a device changed on its own: refresh it shortly (bursts are merged)."""
        loop = asyncio.get_running_loop()
        for d in self.store.devices.values():
            if d.adapter == adapter_id and d.config.get("_uid") == uid:
                if (h := self._soon.pop(d.id, None)) is not None:
                    h.cancel()
                self._soon[d.id] = loop.call_later(
                    0.3, lambda i=d.id: (self._soon.pop(i, None), asyncio.ensure_future(self.refresh(i))))

    # --- polling ------------------------------------------------------------
    def _start_poller(self, d: Device) -> None:
        if d.id in self._pollers:
            self._pollers[d.id].cancel()
        self._pollers[d.id] = asyncio.create_task(self._poll_loop(d.id))

    async def _poll_loop(self, device_id: str) -> None:
        await asyncio.sleep(0.2)
        while device_id in self.store.devices:
            d = self.store.devices[device_id]
            await self.refresh(device_id)
            cls = ADAPTERS.get(d.adapter)
            interval = cls.poll_interval if cls else 30
            if d.state.get("online") is False:
                interval = max(interval, 20)
            await asyncio.sleep(interval)

    async def refresh(self, device_id: str) -> None:
        d = self.store.devices.get(device_id)
        if not d:
            return
        try:
            adapter = self._adapter_for(d)
        except AdapterError as e:
            d.state = {"online": False, "error": str(e)}
            self._publish_device(d)
            return
        before = dict(d.state)
        config_before = dict(d.config)
        shape_before = (list(d.caps), dict(d.meta))
        try:
            state = await asyncio.wait_for(adapter.refresh(d), REFRESH_TIMEOUT)
            self._failures[d.id] = 0
            d.state = {"online": True, **(state or {})}
        except PairingRequired as e:
            d.state = {"online": True, "needs_pairing": True, "error": str(e)}
        except Exception as e:
            n = self._failures.get(d.id, 0) + 1
            self._failures[d.id] = n
            if n >= OFFLINE_AFTER_FAILURES or before.get("online") is None:
                d.state = {**before, "online": False, "error": _friendly(e)}
        if d.state.get("power_w") is not None and d.state.get("online"):
            await asyncio.to_thread(self.history.record, d.id, d.state["power_w"])
        shape_changed = (list(d.caps), dict(d.meta)) != shape_before   # e.g. a vacuum's rooms arrived
        if d.config != config_before or shape_changed:
            self.store.save()              # the adapter learned something (e.g. a TV's MAC address)
        if d.state != before or shape_changed:
            self._publish_device(d)

    async def map_image(self, device_id: str) -> tuple[str, bytes]:
        d = self.get(device_id)
        if Cap.MAP not in d.caps:
            raise AdapterError(f"{d.name} doesn't have a map.")
        img = await asyncio.wait_for(self._adapter_for(d).map_image(d), REFRESH_TIMEOUT)
        if not img:
            raise AdapterError("The map isn't ready yet. Try again in a minute.")
        return img

    async def energy(self, device_id: str, days: int = 7) -> dict:
        self.get(device_id)
        return await self.history.summary(device_id, max(1, min(31, days)))

    # --- discovery & adding -------------------------------------------------
    async def discover(self, adapter_id: str) -> list[dict]:
        a = self.adapters.get(adapter_id)
        if not a:
            raise AdapterError("This brand isn't available.")
        found = await asyncio.wait_for(a.discover(), 25)
        self._found_ips[adapter_id] = Counter(f.config.get("ip") for f in found if f.config.get("ip"))
        out = []
        for f in found:
            self._found[(adapter_id, f.uid)] = f
            item = f.to_dict()
            item["added"] = self._already_added(adapter_id, f, by_ip=True) is not None
            out.append(item)
        return out

    def _already_added(self, adapter_id: str, f: Found, *, by_ip: bool) -> Device | None:
        """The saved device a search result (or manual entry) is, if any.
        Matches the result's uid and aliases against every id the device is known by. With by_ip,
        a saved device of the same brand at the same address also counts (a safety net for when a
        brand reports a different uid depending on how it found the device) — but only when that
        address belongs to one device on each side, so hubs and multi-channel devices aren't hidden,
        and not when both sides know a MAC and the MACs differ (a new device on a reused address)."""
        a = self.adapters[adapter_id]
        ids = {f.uid, *f.aliases}
        mine = [d for d in self.store.devices.values() if d.adapter == adapter_id]
        for d in mine:
            if ids & a.known_ids(d):
                return d
        ip = f.config.get("ip")
        if not by_ip or not ip or self._found_ips.get(adapter_id, Counter())[ip] > 1:
            return None
        at_ip = [d for d in mine if d.config.get("ip") == ip]
        if len(at_ip) != 1:
            return None
        mac, saved_mac = normalize_mac(f.config.get("mac")), normalize_mac(at_ip[0].config.get("mac"))
        if mac and saved_mac and mac != saved_mac:
            return None
        return at_ip[0]

    def _searchable(self) -> tuple[list[str], list[str]]:
        """Brands that "Search all brands" can search now, and brands that need an account first.
        In demo mode only the pretend (hidden) brands are searched, so nothing touches the real network."""
        ready, needs_account = [], []
        for aid, a in self.adapters.items():
            cls = type(a)
            if not cls.can_discover or cls.hidden != self.demo:
                continue
            if any(f.required for f in cls.account_fields) and not self.store.accounts.get(aid):
                needs_account.append(aid)
            else:
                ready.append(aid)
        return ready, needs_account

    async def discover_all(self) -> dict:
        """Search every brand at once. One slow or broken brand never stops the others."""
        ready, needs_account = self._searchable()

        async def one(aid: str):
            try:
                return aid, await self.discover(aid), None
            except asyncio.TimeoutError:
                return aid, [], "Took too long to answer."
            except Exception as e:
                log.warning("Search all: %s failed: %s", aid, e)
                return aid, [], _friendly(e)

        def name(aid: str) -> str:
            return type(self.adapters[aid]).name or aid

        found, failed = [], []
        for aid, items, err in await asyncio.gather(*(one(a) for a in ready)):
            if err:
                failed.append({"adapter": aid, "adapter_name": name(aid), "error": err})
            for item in items:
                found.append({**item, "adapter": aid, "adapter_name": name(aid)})
        found.sort(key=lambda f: (f["added"], f["adapter_name"], f["name"].lower()))
        return {
            "found": found,
            "searched": ready,
            "failed": failed,
            "needs_account": [{"adapter": a, "adapter_name": name(a)} for a in needs_account],
        }

    async def add_device(self, adapter_id: str, *, uid: str | None = None, manual: dict | None = None,
                         name: str | None = None, room: str = "") -> dict:
        a = self.adapters.get(adapter_id)
        if not a:
            raise AdapterError("This brand isn't available.")
        if uid:
            f = self._found.get((adapter_id, uid))
            if not f:
                raise AdapterError("That device isn't in the latest search. Search again.")
        else:
            f = a.from_manual(manual or {})
        # The address safety net only for search results: a hand-entered device may share an
        # address on purpose (e.g. the second channel of a two-channel relay).
        dup = self._already_added(adapter_id, f, by_ip=bool(uid))
        if dup:
            raise AdapterError(f"Already added as '{dup.name}'.")
        room = room or f.room
        config = {**f.config, "_uid": f.uid}
        if f.aliases:
            config["_aliases"] = list(f.aliases)
        d = Device(id=uuid.uuid4().hex[:10], adapter=adapter_id, name=(name or f.name).strip(),
                   kind=f.kind, room=room, config=config, caps=list(f.caps))
        self.store.devices[d.id] = d
        if room and room not in self.store.rooms:
            self.store.rooms.append(room)
        d.state = {"online": None}
        await self._setup(d, a)
        self.store.save()
        self._start_poller(d)
        self._publish_layout()
        return self.public_device(d)

    async def _setup(self, d: Device, a: DeviceAdapter) -> None:
        try:
            await asyncio.wait_for(a.setup(d), 45)
            d.state.pop("needs_pairing", None)
            d.state["online"] = True
        except PairingRequired as e:
            d.state = {"online": True, "needs_pairing": True, "error": str(e)}
        except asyncio.TimeoutError:
            d.state = {"online": True, "needs_pairing": True,
                       "error": "No answer from the TV. Choose Pair and accept the prompt on screen."}
        except Exception as e:
            d.state = {"online": False, "error": _friendly(e)}

    async def pair(self, device_id: str) -> dict:
        d = self.get(device_id)
        await self._setup(d, self._adapter_for(d))
        self.store.save()
        self._publish_device(d)
        if d.state.get("needs_pairing"):
            raise AdapterError(d.state.get("error") or "Pairing didn't finish.")
        return self.public_device(d)

    def update_device(self, device_id: str, changes: dict) -> dict:
        d = self.get(device_id)
        for k in ("name", "room", "icon", "kind", "keep_on"):
            if k in changes:
                setattr(d, k, changes[k])
        if "mac" in changes:
            raw = str(changes["mac"] or "").strip()
            if raw:
                mac = normalize_mac(raw)
                if not mac:
                    raise AdapterError("MAC address should look like AA:BB:CC:DD:EE:FF.")
                d.config["mac"] = mac
            else:
                d.config.pop("mac", None)
        if d.room and d.room not in self.store.rooms:
            self.store.rooms.append(d.room)
        self.store.save()
        self._publish_layout()
        return self.public_device(d)

    async def remove_device(self, device_id: str) -> None:
        d = self.store.devices.pop(device_id, None)
        if not d:
            raise KeyError(device_id)
        t = self._pollers.pop(device_id, None)
        if t:
            t.cancel()
        a = self.adapters.get(d.adapter)
        if a:
            try:
                await a.forget(d)
            except Exception:
                pass
        for s in self.store.scenes:
            s["actions"] = [x for x in s["actions"] if x["device_id"] != device_id]
        self.store.automations = [a for a in self.store.automations if a["do"].get("device_id") != device_id]
        self.profiles.forget_device(device_id)
        await asyncio.to_thread(self.history.forget, device_id)
        self.store.save()
        self._publish_layout()

    # --- accounts -----------------------------------------------------------
    def set_account(self, adapter_id: str, values: dict) -> dict:
        cls = ADAPTERS.get(adapter_id)
        if not cls:
            raise KeyError(adapter_id)
        current = dict(self.store.accounts.get(adapter_id, {}))
        for f in cls.account_fields:
            if f.key in values:
                v = values[f.key]
                if f.type == "password" and v in ("", None) and current.get(f.key):
                    continue  # blank password field = keep the saved one
                current[f.key] = v
        self.store.accounts[adapter_id] = current
        self.store.save()
        if adapter_id in self.adapters:
            self.adapters[adapter_id].account_changed(current)
        return self.account_public(adapter_id)

    def account_public(self, adapter_id: str) -> dict:
        cls = ADAPTERS[adapter_id]
        acc = self.store.accounts.get(adapter_id, {})
        return {f.key: ("••••••" if f.type == "password" and acc.get(f.key) else acc.get(f.key, ""))
                for f in cls.account_fields}

    async def account_action(self, adapter_id: str, action: str) -> dict:
        a = self.adapters.get(adapter_id)
        if not a:
            raise AdapterError("This brand isn't available.")
        result = await a.run_account_action(action) or {}
        updates = result.get("account") or {}
        if updates:
            self.store.accounts[adapter_id] = {**self.store.accounts.get(adapter_id, {}), **updates}
            self.store.save()
            a.account_changed(self.store.accounts[adapter_id])
        return {"message": result.get("message", "Done"), "account": self.account_public(adapter_id)}

    # --- rooms, scenes, settings -------------------------------------------
    def set_rooms(self, rooms: list[str]) -> list[str]:
        clean = []
        for r in rooms:
            r = str(r).strip()
            if r and r not in clean:
                clean.append(r)
        self.store.rooms = clean
        for d in self.store.devices.values():
            if d.room and d.room not in clean:
                d.room = ""
        self.store.save()
        self._publish_layout()
        return clean

    def save_scene(self, scene: dict) -> dict:
        """scene = {id?, name, icon, actions:[{device_id, action, value}]}
        or {name, icon, capture:[device_id …]} to snapshot those devices as they are now."""
        actions = scene.get("actions")
        if actions is None:
            actions = []
            for did in scene.get("capture", []):
                d = self.store.devices.get(did)
                if not d:
                    continue
                if not d.state.get("on"):
                    actions.append({"device_id": did, "action": Action.POWER, "value": False})
                    continue
                actions.append({"device_id": did, "action": Action.POWER, "value": True})
                if Cap.BRIGHTNESS in d.caps and d.state.get("brightness"):
                    actions.append({"device_id": did, "action": Action.BRIGHTNESS, "value": d.state["brightness"]})
                if d.state.get("color_mode") == "color" and d.state.get("color"):
                    actions.append({"device_id": did, "action": Action.COLOR, "value": d.state["color"]})
                elif d.state.get("color_mode") == "temp" and d.state.get("color_temp"):
                    actions.append({"device_id": did, "action": Action.COLOR_TEMP, "value": d.state["color_temp"]})
        sid = scene.get("id") or uuid.uuid4().hex[:8]
        item = {"id": sid, "name": scene.get("name", "Scene").strip() or "Scene",
                "icon": scene.get("icon", "sparkle"), "actions": actions}
        self.store.scenes = [s for s in self.store.scenes if s["id"] != sid] + [item]
        self.store.save()
        self._publish_layout()
        return item

    def delete_scene(self, scene_id: str) -> None:
        self.store.scenes = [s for s in self.store.scenes if s["id"] != scene_id]
        self.store.save()
        self._publish_layout()

    async def run_scene(self, scene_id: str) -> dict:
        scene = next((s for s in self.store.scenes if s["id"] == scene_id), None)
        if not scene or not self.scene_visible(scene):
            raise KeyError(scene_id)
        by_device: dict[str, list] = {}
        for a in scene["actions"]:
            by_device.setdefault(a["device_id"], []).append(a)

        async def run_for(did, acts):   # same device: in order; devices: in parallel
            for a in acts:
                await self.command(did, a["action"], a.get("value"))

        results = await asyncio.gather(*(run_for(k, v) for k, v in by_device.items()
                                         if k in self.store.devices), return_exceptions=True)
        failed = [str(r) for r in results if isinstance(r, Exception)]
        return {"ok": len(results) - len(failed), "failed": failed}

    def update_settings(self, changes: dict) -> dict:
        changes = {k: v for k, v in changes.items() if k in self.store.settings}
        for key, lo, hi in (("latitude", -90, 90), ("longitude", -180, 180)):
            if key in changes and changes[key] not in (None, ""):
                try:
                    v = float(changes[key])
                    assert lo <= v <= hi
                except Exception:
                    raise AdapterError(f"{key.title()} should be a number between {lo} and {hi}.")
                changes[key] = round(v, 4)
            elif key in changes:
                changes[key] = None
        if "background" in changes and changes["background"] not in BACKGROUNDS:
            raise AdapterError(f"Background should be one of: {', '.join(BACKGROUNDS)}.")
        if "glass_transparency" in changes:
            try:
                changes["glass_transparency"] = max(0, min(100, int(float(changes["glass_transparency"]))))
            except (TypeError, ValueError):
                raise AdapterError("Glass transparency should be a number from 0 to 100.")
        if "idle_screen" in changes and changes["idle_screen"] not in IDLE_SCREENS:
            raise AdapterError("Idle screen should be 'clock' or 'photos'.")
        if "place_name" in changes:
            changes["place_name"] = " ".join(str(changes["place_name"] or "").split())[:40]
        if "temperature_unit" in changes:
            unit = str(changes["temperature_unit"] or "").upper()
            if unit not in ("C", "F"):
                raise AdapterError("Temperature unit should be C or F.")
            changes["temperature_unit"] = unit
        if "clock_face" in changes and changes["clock_face"] not in CLOCK_FACES:
            raise AdapterError(f"Clock face should be one of: {', '.join(CLOCK_FACES)}.")
        if "lock_after_minutes" in changes:
            try:
                changes["lock_after_minutes"] = max(0, min(240, int(float(changes["lock_after_minutes"]))))
            except (TypeError, ValueError):
                raise AdapterError("Lock after should be a number of minutes.")
        if "frame_seconds" in changes:
            try:
                changes["frame_seconds"] = max(5, min(300, int(float(changes["frame_seconds"]))))
            except (TypeError, ValueError):
                raise AdapterError("Seconds per photo should be a number.")
        for key in ("glass_effect", "clock_24h", "frame_shuffle", "frame_clock", "frame_night_clock",
                    "weather_enabled"):
            if key in changes:
                changes[key] = changes[key] in (True, 1, "1", "true", "on")
        if "home_layout" in changes:
            try:
                changes["home_layout"] = clean_layout(changes["home_layout"]) if changes["home_layout"] else None
            except LayoutError as e:
                raise AdapterError(str(e)) from None
        if "presence" in changes:
            people = []
            for p in changes["presence"] or []:
                name, ip = str(p.get("name", "")).strip(), str(p.get("ip", "")).strip()
                if name and ip:
                    people.append({"name": name[:24], "ip": ip})
            changes["presence"] = people
        self.store.settings.update(changes)
        self.store.save()
        self._publish_layout()
        return self.settings()

    # --- profiles -----------------------------------------------------------
    # Admin-only at the API (app/api/auth.py). Hashing is slow on purpose, so it runs in a thread.
    def _profile_input(self, data: dict) -> dict:
        data = dict(data or {})
        if isinstance(data.get("devices"), list):     # only devices that exist
            data["devices"] = [d for d in data["devices"] if d in self.store.devices]
        return data

    def list_profiles(self) -> list[dict]:
        return [self.profiles.public(p) for p in self.profiles.items]

    async def add_profile(self, data: dict) -> dict:
        p = await asyncio.to_thread(self.profiles.create, self._profile_input(data))
        self._publish_layout()
        return self.profiles.public(p)

    async def update_profile(self, profile_id: str, data: dict) -> dict:
        p = await asyncio.to_thread(self.profiles.update, profile_id, self._profile_input(data))
        self._publish_layout()               # their screens reload with the new device list
        return self.profiles.public(p)

    async def update_me(self, data: dict) -> dict:
        """Change your own name, colour, email, PIN or password (not your role or devices)."""
        viewer = current_viewer.get()
        if viewer is None:
            raise AdapterError("Sign in first.")
        mine = {k: data[k] for k in ("name", "color", "email", "pin", "password") if k in data}
        return await self.update_profile(viewer.id, mine)

    def delete_profile(self, profile_id: str) -> None:
        viewer = current_viewer.get()
        if viewer is not None and viewer.id == profile_id:
            raise AdapterError("You can't remove the profile you're signed in with. Sign in as another admin first.")
        self.profiles.delete(profile_id)
        self._publish_layout()

    def display_settings(self, with_location: bool = False) -> dict:
        """The look of the panel, for the sign-in screen and a locked wall panel's clock.
        Nothing private: no location unless asked (a locked panel), no people, no layout."""
        keys = ("home_name", "background", "glass_effect", "glass_transparency", "clock_24h", "clock_face",
                "dim_after_seconds", "idle_screen", "frame_seconds", "frame_shuffle", "frame_clock",
                "frame_night_clock", "temperature_unit", "lock_after_minutes")
        out = {k: self.store.settings.get(k) for k in keys}
        if with_location:
            out.update({k: self.store.settings.get(k) for k in ("latitude", "longitude", "place_name", "weather_enabled")})
        return out

    # --- demo ---------------------------------------------------------------
    async def _seed_demo(self) -> None:
        a = self.adapters.get("demo")
        if not a:
            return
        for f in await a.discover():
            d = Device(id=f.uid, adapter="demo", name=f.name, kind=f.kind,
                       room=f.config.get("room", ""), config={**f.config, "_uid": f.uid}, caps=f.caps)
            await a.setup(d)                       # like adding a device: fills in meta (TV apps, vacuum rooms)
            self.store.devices[d.id] = d
        self.store.scenes = [
            {"id": "movie", "name": "Movie night", "icon": "film", "actions": [
                {"device_id": "lr-lamp", "action": "brightness", "value": 20},
                {"device_id": "lr-strip", "action": "color", "value": {"r": 90, "g": 60, "b": 255}},
                {"device_id": "lr-ceiling", "action": "power", "value": False},
                {"device_id": "lr-tv", "action": "power", "value": True}]},
            {"id": "morning", "name": "Good morning", "icon": "sun", "actions": [
                {"device_id": "kt-pendant", "action": "power", "value": True},
                {"device_id": "kt-kettle", "action": "power", "value": True},
                {"device_id": "lr-ceiling", "action": "color_temp", "value": 4500}]},
            {"id": "night", "name": "Bedtime", "icon": "moon", "actions": [
                {"device_id": "lr-ceiling", "action": "power", "value": False},
                {"device_id": "lr-lamp", "action": "power", "value": False},
                {"device_id": "lr-tv", "action": "power", "value": False},
                {"device_id": "bd-lamp", "action": "brightness", "value": 10}]},
        ]
        # Two pretend people. Owner: PIN 1234, or owner@example.com / homepanel. Sam: PIN 2468.
        self.store.profiles = [
            {"id": "owner", "name": "Owner", "color": "#f2b35b", "email": "owner@example.com", "role": ADMIN,
             "pin_hash": hash_secret("1234"), "password_hash": hash_secret("homepanel"), "devices": "all",
             "home_layout": None, "created": time.time()},
            {"id": "sam", "name": "Sam", "color": "#7cc7a5", "email": "", "role": MEMBER,
             "pin_hash": hash_secret("2468"), "password_hash": None,
             "devices": ["bd-fan", "bd-lamp", "bd-tv", "kt-pendant"], "home_layout": None, "created": time.time()},
        ]
        self.store.automations = [
            {"id": "wake", "name": "Good morning on weekdays", "enabled": True,
             "when": {"type": "time", "at": "07:00", "days": [0, 1, 2, 3, 4]},
             "do": {"type": "scene", "scene_id": "morning"}},
            {"id": "away", "name": "All off when everyone leaves", "enabled": True,
             "when": {"type": "presence", "event": "all_away"}, "do": {"type": "all_off"}},
        ]
        self.store.save()

    def _seed_demo_history(self) -> None:
        """Seven days of believable power readings so the energy chart has something to show."""
        import math
        import random
        rng = random.Random(42)
        now = time.time()
        rows = []
        for i in range(7 * 24 * 12):                      # every 5 minutes
            ts = now - i * 300
            hour = time.localtime(ts).tm_hour + time.localtime(ts).tm_min / 60
            fridge = 118 + rng.uniform(-6, 6) if (ts // 60) % 45 < 20 else 3.2
            speaker = 7.4 + rng.uniform(-0.5, 0.5) if 17 <= hour < 23 else 0.6
            kettle = 1500.0 if (6.95 <= hour < 7.05 or 18.95 <= hour < 19.05) else 0.0
            fan = 38 + 4 * math.sin(i) if (hour >= 22 or hour < 7) else 0.0
            for did, w in (("kt-fridge", fridge), ("lr-plug", speaker), ("kt-kettle", kettle), ("bd-fan", fan)):
                rows.append((did, ts, round(w, 1)))
        self.history.bulk_insert(rows)


def _friendly(e: Exception) -> str:
    if isinstance(e, AdapterError):
        return str(e)
    if isinstance(e, asyncio.TimeoutError):
        return "Not responding"
    if isinstance(e, (ConnectionRefusedError, OSError)):
        return "Can't reach it on the network"
    return str(e) or e.__class__.__name__
