"""Ecovacs Deebot robot vacuums, through the Ecovacs cloud (the same account as the Ecovacs Home app).

Uses the deebot-client library (the one Home Assistant uses). It only installs on
Python 3.14, so on other versions this brand shows as "not installed" and the rest
of the panel works as usual.

Flow:
  1. Account: email + password + country. The panel logs in like a phone would.
  2. The first time, Ecovacs may want to confirm the new "phone" by email:
     "Email me a code" sends it, "Confirm code" uses what was typed in Email code.
  3. Search lists every Deebot on the account. Each one keeps a live MQTT
     connection: state and battery arrive as events and are cached here.

Login tokens and this panel's device id are kept in <data>/ecovacs.json (git-ignored
data folder, like the rest of the account data), so the password isn't needed for
every start and Ecovacs doesn't ask to confirm the panel again.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid

from ..core.adapter import (Action, Activity, AdapterError, Cap, Clean, Device, DeviceAdapter, Field,
                            Found, Kind, register)

log = logging.getLogger("homepanel")
# The library's debug output includes short-lived login tokens, and the panel's log is
# shown in Settings → Diagnostics. Keep it to warnings, even when running with --debug.
logging.getLogger("deebot_client").setLevel(logging.WARNING)

COUNTRIES = [("US", "United States"), ("CA", "Canada"), ("GB", "United Kingdom"), ("IE", "Ireland"),
             ("DE", "Germany"), ("FR", "France"), ("ES", "Spain"), ("IT", "Italy"), ("NL", "Netherlands"),
             ("AU", "Australia"), ("NZ", "New Zealand"), ("IN", "India"), ("JP", "Japan"),
             ("SG", "Singapore"), ("CN", "China")]

NEEDS_CODE = ("Ecovacs wants to confirm this panel. Tap Email me a code, type the code from the email "
              "into Email code, then tap Confirm code.")

# deebot_client State names → our generic Activity values.
STATE_TO_ACTIVITY = {"IDLE": Activity.IDLE, "CLEANING": Activity.CLEANING, "RETURNING": Activity.RETURNING,
                     "DOCKED": Activity.DOCKED, "ERROR": Activity.ERROR, "PAUSED": Activity.PAUSED}
RUNNING = (Activity.CLEANING, Activity.RETURNING)

# Friendly names for the library's option enums (matched by enum member name).
OPTION_NAMES = {
    "QUIET": "Quiet", "NORMAL": "Standard", "MAX": "Strong", "MAX_PLUS": "Max+",
    "VACUUM": "Vacuum", "MOP": "Mop", "VACUUM_AND_MOP": "Vacuum and mop", "MOP_AFTER_VACUUM": "Vacuum, then mop",
    "EMPTY_DUSTBIN": "Empty dustbin", "WASH_MOP": "Wash mop", "DRY_MOP": "Dry mop", "CLEAN_BASE": "Clean station",
}
PART_NAMES = {
    "BRUSH": "Main brush", "SIDE_BRUSH": "Side brush", "FILTER": "Filter", "ROUND_MOP": "Mop pads",
    "DUST_BAG": "Dust bag", "DUST_BUCKET": "Dust bin", "DUST_CONTAINER_FILTER": "Dust bin filter",
    "MOP_WASHING_TRAY": "Mop washing tray", "STRAINER": "Station strainer", "UNIT_CARE": "General care",
    "CLEANING_SOLUTION": "Cleaning solution", "HEAVY_DUTY_CLEANING_SOLUTION": "Heavy-duty solution",
}


def _nice(name: str) -> str:
    return OPTION_NAMES.get(name) or name.replace("_", " ").capitalize()


def _options(types) -> list[dict]:
    """The library's enum members → [{id, name}] for device.meta."""
    return [{"id": t.name.lower(), "name": _nice(t.name)} for t in types or ()]


def _pick(types, option_id: str):
    for t in types or ():
        if t.name.lower() == str(option_id):
            return t
    raise AdapterError(f"Unknown option '{option_id}'")


def _caps_for(c) -> list[str]:
    """Generic capabilities from what the library says this model can do."""
    caps = [Cap.CLEAN, Cap.DOCK]
    m = getattr(c, "map", None)
    if m is not None:
        caps.append(Cap.MAP)
        if getattr(m, "rooms", None) is not None and getattr(c.clean.action, "area", None) is not None:
            caps.append(Cap.ROOMS)
    if getattr(c, "fan_speed", None) is not None:
        caps.append(Cap.SUCTION)
    if getattr(c.clean, "work_mode", None) is not None:
        caps.append(Cap.CLEAN_MODE)
    if getattr(c, "station", None) is not None:
        caps.append(Cap.STATION)
    if getattr(c, "play_sound", None) is not None:
        caps.append(Cap.LOCATE)
    return caps


def _option_meta(c) -> dict:
    meta = {}
    if getattr(c, "fan_speed", None) is not None:
        meta["suction_levels"] = _options(c.fan_speed.types)
    if getattr(c.clean, "work_mode", None) is not None:
        meta["clean_modes"] = _options(c.clean.work_mode.types)
    if getattr(c, "station", None) is not None:
        meta["station_actions"] = _options(c.station.action.types)
    return meta


@register
class EcovacsAdapter(DeviceAdapter):
    id = "ecovacs"
    name = "Ecovacs Deebot"
    brands = "Ecovacs Deebot robot vacuums"
    kinds = (Kind.VACUUM,)
    description = ("Uses your Ecovacs Home app account and works through the Ecovacs cloud, "
                   "so the panel needs internet.")
    requires = ("deebot_client",)
    python_versions = ((3, 14),)   # the library is only published for 3.14
    poll_interval = 30          # live updates arrive over MQTT; polling is only a safety net
    account_fields = [
        Field("email", "Email or phone number", required=True, placeholder="you@example.com",
              help="The one you use in the Ecovacs Home app."),
        Field("password", "Password", "password", required=True),
        Field("country", "Country", "select", required=True, default="US",
              options=[{"value": c, "label": n} for c, n in COUNTRIES]),
        Field("code", "Email code", placeholder="Only if Ecovacs asks",
              help="Only needed the first time, if Ecovacs asks to confirm this panel."),
    ]
    account_actions = [
        {"id": "send_code", "label": "Email me a code",
         "help": "Sends a one-time code to your Ecovacs email."},
        {"id": "verify", "label": "Confirm code",
         "help": "After typing the code from the email into Email code."},
    ]

    def __init__(self, account, data_dir):
        super().__init__(account, data_dir)
        self._lock = asyncio.Lock()
        self._session = None
        self._auth = None
        self._api = None
        self._mqtt = None
        self._infos: dict[str, object] = {}     # did → DeviceInfo
        self._bots: dict[str, object] = {}      # did → deebot_client.device.Device
        self._state: dict[str, dict] = {}       # did → latest state from events
        self._tasks: set[asyncio.Task] = set()

    # --- saved login (device id + token) -----------------------------------
    def _saved_path(self) -> str:
        return os.path.join(self.data_dir, "ecovacs.json")

    def _saved(self) -> dict:
        try:
            with open(self._saved_path()) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        if saved.get("email") != self.account.get("email"):   # another account: start over
            saved = {"email": self.account.get("email")}
        if not saved.get("device_id"):
            saved["device_id"] = uuid.uuid4().hex
            self._write_saved(saved)
        return saved

    def _write_saved(self, saved: dict) -> None:
        path = self._saved_path()
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(saved, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    # --- connection ----------------------------------------------------------
    def _check_account(self) -> None:
        if not self.account.get("email") or not self.account.get("password"):
            raise AdapterError("Add your Ecovacs email and password first: Settings → Ecovacs Deebot.")

    async def _connect(self) -> None:
        """Log in once and keep the session. Raises AdapterError with what to do."""
        self._check_account()
        async with self._lock:
            if self._auth is not None:
                return
            import aiohttp
            from deebot_client.api_client import ApiClient
            from deebot_client.authentication import Authenticator, create_rest_config
            from deebot_client.models import AccountCredentials
            from deebot_client.util import md5

            saved = self._saved()
            country = (self.account.get("country") or "US").upper()
            session = aiohttp.ClientSession()
            rest = create_rest_config(session, device_id=saved["device_id"], alpha_2_country=country)
            known = (AccountCredentials(saved["access_token"], saved["user_id"])
                     if saved.get("access_token") and saved.get("user_id") else None)
            auth = Authenticator(rest, self.account["email"], md5(self.account["password"]),
                                 account_credentials=known)

            async def remember(creds) -> None:
                s = self._saved()
                s.update(access_token=creds.access_token, user_id=creds.user_id)
                self._write_saved(s)
            auth.subscribe_account_credentials(remember)

            try:
                await auth.authenticate()
            except Exception as e:
                await _quietly(auth.teardown())
                await session.close()
                raise _friendly(e) from e
            self._session, self._auth, self._api = session, auth, ApiClient(auth)

    async def _mqtt_client(self):
        if self._mqtt is None:
            from deebot_client.mqtt_client import MqttClient, create_mqtt_config
            cfg = create_mqtt_config(device_id=self._saved()["device_id"],
                                     country=(self.account.get("country") or "US").upper())
            self._mqtt = MqttClient(cfg, self._auth)
        return self._mqtt

    async def _disconnect(self) -> None:
        bots, self._bots = list(self._bots.values()), {}
        for bot in bots:
            await _quietly(bot.teardown())
        if self._mqtt is not None:
            await _quietly(self._mqtt.disconnect())
        if self._auth is not None:
            await _quietly(self._auth.teardown())
        if self._session is not None:
            await _quietly(self._session.close())
        self._session = self._auth = self._api = self._mqtt = None
        self._infos = {}

    def account_changed(self, account):
        super().account_changed(account)
        task = asyncio.ensure_future(self._disconnect())    # log in again with the new details
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def stop(self):
        await self._disconnect()

    # --- account actions (email verification) --------------------------------
    async def run_account_action(self, action):
        self._check_account()
        if action not in ("send_code", "verify"):
            raise AdapterError("Unknown action")
        await self._disconnect()
        import aiohttp
        from deebot_client.authentication import Authenticator, create_rest_config
        from deebot_client.util import md5

        saved = self._saved()
        async with aiohttp.ClientSession() as session:
            rest = create_rest_config(session, device_id=saved["device_id"],
                                      alpha_2_country=(self.account.get("country") or "US").upper())
            auth = Authenticator(rest, self.account["email"], md5(self.account["password"]))
            got: list = []

            async def remember(creds) -> None:
                got.append(creds)
            auth.subscribe_account_credentials(remember)
            try:
                if action == "send_code":
                    await auth.request_device_verification_code()
                    return {"message": "Code sent. Check your email, type the code into Email code, "
                                       "then tap Confirm code."}
                code = (self.account.get("code") or "").strip()
                if not code:
                    raise AdapterError("Type the code from the Ecovacs email into Email code first.")
                await auth.verify_device(code)
                await asyncio.sleep(0)            # let the credentials callback run
                if got:
                    saved.update(access_token=got[-1].access_token, user_id=got[-1].user_id)
                    self._write_saved(saved)
                return {"message": "Panel confirmed. Now tap Search my Wi-Fi to find your vacuum.",
                        "account": {"code": ""}}
            except AdapterError:
                raise
            except Exception as e:
                raise _friendly(e) from e
            finally:
                await _quietly(auth.teardown())

    # --- devices -------------------------------------------------------------
    async def _load_devices(self) -> list:
        await self._connect()
        try:
            devices = await self._api.get_devices()
        except Exception as e:
            raise _friendly(e) from e
        self._infos = {info.api["did"]: info for info in devices.mqtt}
        if not devices.mqtt and (devices.xmpp or devices.not_supported):
            names = ", ".join(d.get("deviceName") or d.get("name", "?") for d in [*devices.xmpp, *devices.not_supported])
            raise AdapterError(f"Found {names} on your Ecovacs account, but that model isn't supported yet.")
        return devices.mqtt

    async def discover(self, timeout=6.0):
        out = []
        for info in await self._load_devices():
            api = info.api
            out.append(Found(adapter=self.id, uid=api["did"], name=api.get("nick") or api.get("deviceName") or "Deebot",
                             kind=Kind.VACUUM, caps=_caps_for(info.static.capabilities), config={"did": api["did"]},
                             detail=api.get("deviceName") or "Ecovacs cloud"))
        return out

    async def _bot(self, device: Device):
        did = device.config["did"]
        if did in self._bots:
            return self._bots[did]
        await self._connect()
        if did not in self._infos:
            await self._load_devices()
        info = self._infos.get(did)
        if info is None:
            raise AdapterError(f"{device.name} isn't on your Ecovacs account any more. Remove it and search again.")
        from deebot_client.device import Device as Bot
        from deebot_client import events as ev

        bot = Bot(info, self._auth)
        st = self._state.setdefault(did, {})
        c = bot.capabilities

        async def on_state(e):
            st["activity"] = STATE_TO_ACTIVITY.get(getattr(e.state, "name", str(e.state)), Activity.IDLE)
            self.changed(did)

        async def on_battery(e):
            st["battery"] = int(e.value)
            self.changed(did)

        async def on_error(e):
            st["problem"] = (e.description or f"Error {e.code}") if e.code else ""
            self.changed(did)

        async def on_available(e):
            st["available"] = bool(e.available)
            self.changed(did)

        async def on_suction(e):
            st["suction"] = e.speed.name.lower()
            self.changed(did)

        async def on_mode(e):
            st["clean_mode"] = e.mode.name.lower()
            self.changed(did)

        async def on_part(e):
            st.setdefault("parts", {})[e.type.name] = {
                "id": e.type.name.lower(), "name": PART_NAMES.get(e.type.name) or _nice(e.type.name),
                "percent": max(0, min(100, round(e.percent)))}
            self.changed(did)

        async def on_rooms(e):
            st["rooms"] = [{"id": r.id, "name": r.name or f"Room {r.id}"} for r in e.rooms]
            self.changed(did)

        async def on_stats(e):
            if e.area is not None or e.time is not None:
                st["last_clean"] = {"area_m2": e.area, "minutes": round(e.time / 60) if e.time else None}
                self.changed(did)

        async def on_map(e):
            st["map_rev"] = int(time.time())
            self.changed(did)

        bot.events.subscribe(ev.StateEvent, on_state)
        bot.events.subscribe(ev.BatteryEvent, on_battery)
        bot.events.subscribe(ev.ErrorEvent, on_error)
        bot.events.subscribe(ev.AvailabilityEvent, on_available)
        # Extras, only when this model has them.
        if getattr(c, "fan_speed", None) is not None:
            bot.events.subscribe(ev.FanSpeedEvent, on_suction)
        if getattr(c.clean, "work_mode", None) is not None:
            bot.events.subscribe(ev.WorkModeEvent, on_mode)
        if getattr(c, "life_span", None) is not None:
            bot.events.subscribe(ev.LifeSpanEvent, on_part)
        if getattr(c, "stats", None) is not None:
            bot.events.subscribe(ev.StatsEvent, on_stats)
        if getattr(c, "map", None) is not None:
            bot.events.subscribe(ev.RoomsEvent, on_rooms)
            bot.events.subscribe(ev.MapChangedEvent, on_map)     # also switches the map on
        await bot.initialize(await self._mqtt_client())
        self._bots[did] = bot
        return bot

    async def setup(self, device: Device):
        await self._bot(device)

    async def refresh(self, device: Device) -> dict:
        bot = await self._bot(device)
        from deebot_client.events import BatteryEvent, StateEvent
        st = self._state.setdefault(device.config["did"], {})
        if "activity" not in st:          # first time: wait a moment for the answer
            bot.events.request_refresh(StateEvent)
            bot.events.request_refresh(BatteryEvent)
            for _ in range(30):
                if "activity" in st:
                    break
                await asyncio.sleep(0.1)
        if st.get("available") is False:
            raise ConnectionError("The vacuum isn't connected to Ecovacs. Check it's switched on and on Wi-Fi.")
        # What it can do and its option lists (rooms arrive a little after connecting).
        device.caps = _caps_for(bot.capabilities)
        device.meta.update(_option_meta(bot.capabilities))
        if "rooms" in st:
            device.meta["rooms"] = st["rooms"]
        return _public(st)

    async def _send(self, device: Device, bot, command, v2=None) -> None:
        """Run one command and make sure the vacuum really accepted it.

        Some models answer the classic clean command with "not supported" (code 20003)
        even though the library lists it for them; they want clean_V2. `v2` builds that
        command. Once it worked, this vacuum always gets V2 (saved in its config)."""
        if v2 is not None and device.config.get("clean_v2"):
            command = v2()
        problem = _reply_problem(await bot.execute_command(command))
        if problem and problem[0] == NOT_SUPPORTED and v2 is not None and not device.config.get("clean_v2"):
            log.info("%s: classic clean command not supported, using clean_V2", device.name)
            problem = _reply_problem(await bot.execute_command(v2()))
            if not problem:
                device.config["clean_v2"] = True
        if problem:
            raise AdapterError(_problem_text(device.name, problem))

    async def command(self, device: Device, action: str, value=None):
        bot = await self._bot(device)
        caps = bot.capabilities
        from deebot_client.commands.json.clean import CleanAreaV2, CleanV2
        from deebot_client.events import StateEvent
        from deebot_client.models import CleanAction, CleanMode
        st = self._state.setdefault(device.config["did"], {})
        if action == Action.CLEAN:
            act = CleanAction(value)
            await self._send(device, bot, caps.clean.action.command(act), v2=lambda: CleanV2(act))
            st["activity"] = {Clean.START: Activity.CLEANING, Clean.RESUME: Activity.CLEANING,
                              Clean.PAUSE: Activity.PAUSED, Clean.STOP: Activity.IDLE}[value]
        elif action == Action.DOCK:
            await self._send(device, bot, caps.charge.execute())
            st["activity"] = Activity.RETURNING
        elif action == Action.CLEAN_ROOMS:
            rooms = [int(r) for r in value]
            await self._send(device, bot, caps.clean.action.area(CleanMode.SPOT_AREA, rooms, 1),
                             v2=lambda: CleanAreaV2(CleanMode.SPOT_AREA, rooms, 1))
            st["activity"] = Activity.CLEANING
        elif action == Action.SET_SUCTION:
            await self._send(device, bot, caps.fan_speed.set(_pick(caps.fan_speed.types, value)))
            st["suction"] = value
        elif action == Action.SET_CLEAN_MODE:
            await self._send(device, bot, caps.clean.work_mode.set(_pick(caps.clean.work_mode.types, value)))
            st["clean_mode"] = value
        elif action == Action.STATION:
            await self._send(device, bot, caps.station.action.execute(_pick(caps.station.action.types, value)))
        elif action == Action.LOCATE:
            await self._send(device, bot, caps.play_sound.execute())
        else:
            raise AdapterError("Not supported")
        # Ask what it's really doing now; the answer replaces the guess above when it arrives.
        bot.events.request_refresh(StateEvent)
        return _public(st)

    async def map_image(self, device: Device):
        bot = await self._bot(device)
        if getattr(bot, "map", None) is None:
            return None
        svg = bot.map.get_svg_map()
        if not svg:
            bot.map.refresh()                  # ask the vacuum for its map; ready on the next try
            return None
        return "image/svg+xml", svg.encode()

    async def forget(self, device: Device):
        bot = self._bots.pop(device.config.get("did"), None)
        if bot is not None:
            await _quietly(bot.teardown())


NOT_SUPPORTED = 20003      # Ecovacs: "rcp not support"


def _reply_problem(resp) -> tuple | None:
    """(code, message) if the vacuum or Ecovacs refused a command, None if it was accepted."""
    if not isinstance(resp, dict) or not resp:
        return None                                   # nothing to judge (e.g. a fake in tests)
    if resp.get("ret") not in (None, "ok"):
        return (f"errno {resp.get('errno')}", resp.get("error") or resp.get("debug") or "")
    body = (resp.get("resp") or resp).get("body")
    if isinstance(body, dict) and body.get("code") not in (None, 0):
        return (body.get("code"), body.get("msg") or "")
    return None


def _problem_text(name: str, problem: tuple) -> str:
    code, msg = problem
    if code == NOT_SUPPORTED:
        return f"{name} didn't accept that command: it says it isn't supported on this model."
    if code == "errno 4200":
        return f"{name} is offline. Check it's switched on and on Wi-Fi."
    if code == "errno 500":
        return f"No answer from {name}. Check it's on Wi-Fi, then try again."
    return f"{name} didn't do that (Ecovacs said: {msg or 'no reason given'}, code {code})."


def _public(st: dict) -> dict:
    """The generic state keys the UI understands. No activity yet = still waiting for Ecovacs."""
    activity = st.get("activity")
    out = {"on": activity in RUNNING}
    if activity:
        out["activity"] = activity
    for key in ("battery", "suction", "clean_mode", "last_clean", "map_rev"):
        if st.get(key) is not None:
            out[key] = st[key]
    if st.get("parts"):
        out["parts"] = sorted(st["parts"].values(), key=lambda p: p["percent"])   # most worn first
    if st.get("problem"):
        out["problem"] = st["problem"]
    return out


def _friendly(e: Exception) -> AdapterError:
    """Turn library errors into plain messages (checked by class name: the library is optional)."""
    if isinstance(e, AdapterError):
        return e
    names = {c.__name__ for c in type(e).__mro__}
    if "InvalidVerificationCodeError" in names:
        return AdapterError("That code didn't work or has expired. Tap Email me a code to get a new one.")
    if "DeviceVerificationRequiredError" in names:
        return AdapterError(NEEDS_CODE)
    if "InvalidAuthenticationError" in names:
        return AdapterError("Ecovacs didn't accept that email and password. Check them in the Ecovacs Home app "
                            "and that the country matches your account.")
    if "ApiTimeoutError" in names or isinstance(e, (asyncio.TimeoutError, OSError)):
        return AdapterError("Couldn't reach Ecovacs. Check the panel's internet connection and try again.")
    log.warning("Ecovacs error: %s: %s", type(e).__name__, e)
    return AdapterError(f"Ecovacs said: {e}")


async def _quietly(coro, timeout: float = 5) -> None:
    """Run a clean-up step; never let a stuck library call hold up shutting down."""
    try:
        await asyncio.wait_for(coro, timeout)
    except Exception:
        pass
