"""Unit tests: the Ecovacs adapter against a small fake of the deebot-client library.

The real library only installs on Python 3.14 and talks to the Ecovacs cloud, so these
tests replace it (in sys.modules) with just enough of its API to run the adapter.
"""
import asyncio
import enum
import json
import os
import sys
import tempfile
import types
import unittest

from app.core.adapter import Action, Activity, AdapterError, Cap, Clean, Device, Kind


# ---- the fake library ----------------------------------------------------------------

class State(enum.IntEnum):
    IDLE, CLEANING, RETURNING, DOCKED, ERROR, PAUSED = 1, 2, 3, 4, 5, 6


class CleanAction(str, enum.Enum):
    START, PAUSE, RESUME, STOP = "start", "pause", "resume", "stop"


class FanSpeedLevel(enum.IntEnum):
    QUIET, NORMAL, MAX, MAX_PLUS = 1000, 0, 1, 2


class WorkMode(enum.IntEnum):
    VACUUM_AND_MOP, VACUUM, MOP, MOP_AFTER_VACUUM = 0, 1, 2, 3


class StationAction(enum.IntEnum):
    EMPTY_DUSTBIN, DRY_MOP, WASH_MOP = 1, 2, 4


class LifeSpan(str, enum.Enum):
    BRUSH, FILTER = "brush", "heap"


class CleanMode(str, enum.Enum):
    SPOT_AREA = "spotArea"


class DeebotError(Exception): ...
class AuthenticationError(DeebotError): ...
class InvalidAuthenticationError(AuthenticationError): ...
class DeviceVerificationRequiredError(AuthenticationError): ...
class InvalidVerificationCodeError(InvalidAuthenticationError): ...


class AccountCredentials:
    def __init__(self, access_token, user_id):
        self.access_token, self.user_id = access_token, user_id


class StateEvent:
    def __init__(self, state): self.state = state
class BatteryEvent:
    def __init__(self, value): self.value = value
class ErrorEvent:
    def __init__(self, code, description=None): self.code, self.description = code, description
class AvailabilityEvent:
    def __init__(self, available): self.available = available
class FanSpeedEvent:
    def __init__(self, speed): self.speed = speed
class WorkModeEvent:
    def __init__(self, mode): self.mode = mode
class LifeSpanEvent:
    def __init__(self, type, percent, remaining=0): self.type, self.percent, self.remaining = type, percent, remaining
class RoomsEvent:
    def __init__(self, map_id, rooms): self.map_id, self.rooms = map_id, rooms
class StatsEvent:
    def __init__(self, area, time, type=None): self.area, self.time, self.type = area, time, type
class MapChangedEvent:
    def __init__(self, when=None): self.when = when
class Room:
    def __init__(self, name, id, coordinates=""): self.name, self.id, self.coordinates = name, id, coordinates


class Cloud:
    """What the fake Ecovacs cloud knows. Tests change this."""
    def reset(self):
        self.login_error = None
        self.devices = [{"did": "bot1", "class": "x", "company": "eco-ng", "name": "E0001",
                         "nick": "Hall bot", "deviceName": "DEEBOT T8", "resource": "r"}]
        self.legacy = []
        self.state, self.battery, self.available = State.DOCKED, 87, True
        self.commands, self.logins, self.codes_sent, self.verified = [], [], 0, []
        self.reply = lambda cmd: {"ret": "ok", "resp": {"body": {"code": 0, "msg": "ok"}}}
        self.full = True           # False = a basic model: clean and dock only
        self.svg = "<svg xmlns='http://www.w3.org/2000/svg'><rect width='10' height='10'/></svg>"
        self.rooms = [Room("Kitchen", 1), Room("Living room", 2), Room("", 7)]


cloud = Cloud()


class Authenticator:
    def __init__(self, config, account_id, password_hash, *, account_credentials=None):
        self.config, self.account_id, self.password_hash = config, account_id, password_hash
        self.known = account_credentials
        self._subs = []

    def subscribe_account_credentials(self, cb):
        self._subs.append(cb)
        return lambda: None

    async def _issue(self):
        for cb in self._subs:
            await cb(AccountCredentials("token-1", "user-1"))

    async def authenticate(self, force=False):
        cloud.logins.append({"device_id": self.config["device_id"], "known": self.known,
                             "password_hash": self.password_hash})
        if cloud.login_error:
            raise cloud.login_error
        await self._issue()

    async def request_device_verification_code(self):
        cloud.codes_sent += 1

    async def verify_device(self, code):
        if code != "123456":
            raise InvalidVerificationCodeError("bad code")
        cloud.verified.append(code)
        await self._issue()

    async def teardown(self):
        pass


class Devices:
    def __init__(self, mqtt, xmpp, not_supported):
        self.mqtt, self.xmpp, self.not_supported = mqtt, xmpp, not_supported


def make_caps():
    ns = types.SimpleNamespace
    clean = ns(action=ns(command=lambda a: Command("clean", a),
                         area=(lambda mode, ids, n: Command("clean_area", (mode, ids, n))) if cloud.full else None),
               work_mode=ns(types=tuple(WorkMode), set=lambda m: Command("mode", m)) if cloud.full else None)
    caps = ns(clean=clean, charge=ns(execute=lambda: Command("charge")),
              fan_speed=None, station=None, play_sound=None, map=None, life_span=None, stats=None)
    if cloud.full:
        caps.fan_speed = ns(types=tuple(FanSpeedLevel), set=lambda lvl: Command("suction", lvl))
        caps.station = ns(action=ns(types=tuple(StationAction), execute=lambda a: Command("station", a)))
        caps.play_sound = ns(execute=lambda: Command("sound"))
        caps.map = ns(rooms=object())
        caps.life_span, caps.stats = object(), object()
    return caps


class DeviceInfo:
    def __init__(self, api):
        self.api = api
        self.static = types.SimpleNamespace(capabilities=make_caps())


class FakeMap:
    def __init__(self): self.refreshed = 0
    def get_svg_map(self): return cloud.svg
    def refresh(self): self.refreshed += 1


class ApiClient:
    def __init__(self, auth): self.auth = auth

    async def get_devices(self):
        return Devices([DeviceInfo(d) for d in cloud.devices], list(cloud.legacy), [])


class Command:
    def __init__(self, name, arg=None): self.name, self.arg = name, arg


class Bus:
    def __init__(self): self.subs = {}

    def subscribe(self, cls, cb):
        self.subs.setdefault(cls, []).append(cb)

    async def fire(self, event):
        for cb in self.subs.get(type(event), []):
            await cb(event)

    def request_refresh(self, cls):
        event = {StateEvent: lambda: StateEvent(cloud.state), BatteryEvent: lambda: BatteryEvent(cloud.battery)}[cls]()
        asyncio.ensure_future(self.fire(event))


class Bot:
    def __init__(self, info, auth):
        self.info, self.events = info, Bus()
        self.capabilities = make_caps()
        self.map = FakeMap() if cloud.full else None

    async def initialize(self, mqtt):
        await self.events.fire(AvailabilityEvent(cloud.available))
        if cloud.full:
            await self.events.fire(RoomsEvent("m1", cloud.rooms))
            await self.events.fire(MapChangedEvent())

    async def execute_command(self, cmd):
        cloud.commands.append((cmd.name, cmd.arg))
        return cloud.reply(cmd)

    async def teardown(self):
        pass


class MqttClient:
    def __init__(self, config, auth): self.config = config
    async def disconnect(self): pass


def install_fake_library():
    mods = {
        "deebot_client": {},
        "deebot_client.api_client": {"ApiClient": ApiClient},
        "deebot_client.authentication": {"Authenticator": Authenticator,
                                         "create_rest_config": lambda s, **k: dict(k)},
        "deebot_client.models": {"AccountCredentials": AccountCredentials, "CleanAction": CleanAction,
                                 "State": State, "CleanMode": CleanMode},
        "deebot_client.util": {"md5": lambda t: f"md5:{len(t)}"},
        "deebot_client.mqtt_client": {"MqttClient": MqttClient, "create_mqtt_config": lambda **k: dict(k)},
        "deebot_client.device": {"Device": Bot},
        "deebot_client.commands": {},
        "deebot_client.commands.json": {},
        "deebot_client.commands.json.clean": {
            "CleanV2": lambda act: Command("clean_v2", act),
            "CleanAreaV2": lambda mode, ids, n: Command("clean_area_v2", (mode, ids, n))},
        "deebot_client.events": {"StateEvent": StateEvent, "BatteryEvent": BatteryEvent,
                                 "ErrorEvent": ErrorEvent, "AvailabilityEvent": AvailabilityEvent,
                                 "FanSpeedEvent": FanSpeedEvent, "WorkModeEvent": WorkModeEvent,
                                 "LifeSpanEvent": LifeSpanEvent, "RoomsEvent": RoomsEvent,
                                 "StatsEvent": StatsEvent, "MapChangedEvent": MapChangedEvent},
    }
    saved = {n: sys.modules.get(n) for n in mods}
    for name, attrs in mods.items():
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
    sys.modules["deebot_client"].events = sys.modules["deebot_client.events"]   # "from deebot_client import events"
    return saved


# ---- tests ---------------------------------------------------------------------------

ACCOUNT = {"email": "me@example.com", "password": "hunter22", "country": "us"}


class EcovacsAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved_modules = install_fake_library()
        cloud.reset()
        self.dir = tempfile.mkdtemp()
        from app.adapters.ecovacs import EcovacsAdapter
        self.cls = EcovacsAdapter
        self.a = EcovacsAdapter(dict(ACCOUNT), self.dir)

    async def asyncTearDown(self):
        await self.a.stop()
        for name, mod in self.saved_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def device(self):
        return Device(id="v1", adapter="ecovacs", name="Hall bot", kind=Kind.VACUUM,
                      caps=[Cap.CLEAN, Cap.DOCK], config={"did": "bot1", "_uid": "bot1"})

    def test_only_offered_on_supported_python(self):
        from unittest import mock
        from app.core.adapter import unsupported_reason
        with mock.patch("sys.version_info", (3, 13, 1, "final", 0)):
            self.assertIn("Needs Python 3.14", unsupported_reason(self.cls))
            self.assertIn("this panel has 3.13", unsupported_reason(self.cls))
        with mock.patch("sys.version_info", (3, 14, 0, "final", 0)):
            self.assertEqual(unsupported_reason(self.cls), "")

    def test_metadata(self):
        self.assertEqual(self.cls.kinds, (Kind.VACUUM,))
        self.assertIn("deebot_client", self.cls.requires)
        self.assertEqual({f.key for f in self.cls.account_fields if f.required}, {"email", "password", "country"})

    async def test_discover_lists_vacuums_without_secrets(self):
        found = await self.a.discover()
        self.assertEqual(len(found), 1)
        f = found[0]
        self.assertEqual((f.uid, f.name, f.kind, f.detail), ("bot1", "Hall bot", Kind.VACUUM, "DEEBOT T8"))
        self.assertEqual(f.caps, [Cap.CLEAN, Cap.DOCK, Cap.MAP, Cap.ROOMS, Cap.SUCTION, Cap.CLEAN_MODE,
                                  Cap.STATION, Cap.LOCATE])
        self.assertNotIn("config", f.to_dict())
        self.assertEqual(cloud.logins[0]["password_hash"], "md5:8")     # the password itself is never sent

    async def test_refresh_reports_activity_and_battery(self):
        st = await self.a.refresh(self.device())
        self.assertEqual((st["activity"], st["on"], st["battery"]), (Activity.DOCKED, False, 87))
        cloud.state = State.CLEANING
        self.a._bots["bot1"].events.request_refresh(StateEvent)
        await asyncio.sleep(0.01)
        st = await self.a.refresh(self.device())
        self.assertEqual((st["activity"], st["on"]), (Activity.CLEANING, True))

    async def test_rooms_options_and_parts_reach_the_panel(self):
        d = self.device()
        st = await self.a.refresh(d)
        self.assertIn(Cap.ROOMS, d.caps)
        self.assertEqual(d.meta["rooms"], [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living room"},
                                           {"id": 7, "name": "Room 7"}])          # unnamed rooms get a name
        self.assertEqual([o["id"] for o in d.meta["suction_levels"]], ["quiet", "normal", "max", "max_plus"])
        self.assertEqual(d.meta["suction_levels"][1]["name"], "Standard")
        self.assertEqual(d.meta["station_actions"][0], {"id": "empty_dustbin", "name": "Empty dustbin"})
        self.assertIn("map_rev", st)
        bus = self.a._bots["bot1"].events
        await bus.fire(LifeSpanEvent(LifeSpan.BRUSH, 81.6))
        await bus.fire(LifeSpanEvent(LifeSpan.FILTER, 12.2))
        await bus.fire(StatsEvent(area=42, time=2100))
        await bus.fire(FanSpeedEvent(FanSpeedLevel.MAX))
        st = await self.a.refresh(d)
        self.assertEqual(st["parts"], [{"id": "filter", "name": "Filter", "percent": 12},     # most worn first
                                       {"id": "brush", "name": "Main brush", "percent": 82}])
        self.assertEqual(st["last_clean"], {"area_m2": 42, "minutes": 35})
        self.assertEqual(st["suction"], "max")

    async def test_model_that_wants_clean_v2(self):
        """The T90 Pro Omni answers the classic clean command with 20003 "rcp not support"."""
        # like deebot-client: a refused command (here 20003 "rcp not support") comes back empty
        refuse_classic = lambda cmd: ({} if cmd.name in ("clean", "clean_area") else
                                      {"ret": "ok", "resp": {"body": {"code": 0, "msg": "ok"}}})
        cloud.reply = refuse_classic
        d = self.device()
        st = await self.a.command(d, Action.CLEAN, Clean.START)
        self.assertEqual(st["activity"], Activity.CLEANING)
        self.assertTrue(d.config["clean_v2"])                       # remembered (saved with the device)
        cloud.commands.clear()
        await self.a.command(d, Action.CLEAN, Clean.PAUSE)          # goes straight to V2 now
        await self.a.command(d, Action.CLEAN_ROOMS, [1, 2])
        self.assertEqual(cloud.commands, [("clean_v2", CleanAction.PAUSE),
                                          ("clean_area_v2", (CleanMode.SPOT_AREA, [1, 2], 1))])

    async def test_refused_command_is_an_error_not_a_guess(self):
        d = self.device()
        await self.a.refresh(d)                                     # docked
        cloud.reply = lambda cmd: {"ret": "ok", "resp": {"body": {"code": 30007, "msg": "bin full"}}}
        with self.assertRaises(AdapterError) as e:
            await self.a.command(d, Action.CLEAN, Clean.START)
        self.assertIn("bin full", str(e.exception))
        self.assertEqual(self.a._state["bot1"]["activity"], Activity.DOCKED)   # not shown as cleaning
        cloud.reply = lambda cmd: {"ret": "fail", "errno": 4200, "error": "offline"}
        with self.assertRaises(AdapterError) as e:
            await self.a.command(d, Action.DOCK)
        self.assertIn("offline", str(e.exception))

    async def test_refused_by_both_forms_is_an_error(self):
        cloud.reply = lambda cmd: {} if cmd.name.startswith("clean") else {"ret": "ok", "resp": {"body": {"code": 0}}}
        d = self.device()
        await self.a.refresh(d)
        with self.assertRaises(AdapterError) as e:
            await self.a.command(d, Action.CLEAN, Clean.START)
        self.assertIn("didn't do that", str(e.exception))
        self.assertNotIn("clean_v2", d.config)                              # nothing worked: nothing remembered
        self.assertEqual(self.a._state["bot1"]["activity"], Activity.DOCKED)

    async def test_extra_commands(self):
        d = self.device()
        await self.a.refresh(d)
        st = await self.a.command(d, Action.CLEAN_ROOMS, [1, "2"])
        self.assertEqual(st["activity"], Activity.CLEANING)
        st = await self.a.command(d, Action.SET_SUCTION, "quiet")
        self.assertEqual(st["suction"], "quiet")
        await self.a.command(d, Action.SET_CLEAN_MODE, "mop_after_vacuum")
        await self.a.command(d, Action.STATION, "empty_dustbin")
        await self.a.command(d, Action.LOCATE)
        self.assertEqual(cloud.commands, [
            ("clean_area", (CleanMode.SPOT_AREA, [1, 2], 1)), ("suction", FanSpeedLevel.QUIET),
            ("mode", WorkMode.MOP_AFTER_VACUUM), ("station", StationAction.EMPTY_DUSTBIN), ("sound", None)])
        with self.assertRaises(AdapterError):
            await self.a.command(d, Action.SET_SUCTION, "turbo")

    async def test_map_image(self):
        d = self.device()
        content_type, body = await self.a.map_image(d)
        self.assertEqual(content_type, "image/svg+xml")
        self.assertTrue(body.startswith(b"<svg"))
        cloud.svg = None                                     # not drawn yet: ask the vacuum, try later
        self.assertIsNone(await self.a.map_image(d))
        self.assertEqual(self.a._bots["bot1"].map.refreshed, 1)

    async def test_basic_model_gets_only_basic_controls(self):
        cloud.full = False
        d = self.device()
        st = await self.a.refresh(d)
        self.assertEqual(d.caps, [Cap.CLEAN, Cap.DOCK])
        self.assertNotIn("rooms", d.meta)
        self.assertNotIn("map_rev", st)
        self.assertIsNone(await self.a.map_image(d))

    async def test_events_are_pushed_to_the_panel(self):
        pushed = []
        self.a.on_change = pushed.append
        await self.a.refresh(self.device())
        pushed.clear()
        await self.a._bots["bot1"].events.fire(BatteryEvent(42))
        self.assertEqual(pushed, ["bot1"])                 # the device's uid
        self.assertEqual((await self.a.refresh(self.device()))["battery"], 42)

    async def test_no_answer_yet_is_not_reported_as_idle(self):
        from app.adapters.ecovacs import _public
        self.assertEqual(_public({}), {"on": False})       # the UI shows "Connecting…"

    def test_library_debug_logging_is_capped(self):
        import logging
        import app.adapters.ecovacs  # noqa: F401
        self.assertGreaterEqual(logging.getLogger("deebot_client").getEffectiveLevel(), logging.WARNING)

    async def test_offline_vacuum_raises(self):
        cloud.available = False
        with self.assertRaises(ConnectionError):
            await self.a.refresh(self.device())

    async def test_commands(self):
        d = self.device()
        st = await self.a.command(d, Action.CLEAN, Clean.START)
        self.assertEqual((st["activity"], st["on"]), (Activity.CLEANING, True))
        await self.a.command(d, Action.CLEAN, Clean.PAUSE)
        st = await self.a.command(d, Action.DOCK)
        self.assertEqual(st["activity"], Activity.RETURNING)
        self.assertEqual(cloud.commands, [("clean", CleanAction.START), ("clean", CleanAction.PAUSE), ("charge", None)])

    async def test_login_is_remembered(self):
        await self.a.discover()
        with open(os.path.join(self.dir, "ecovacs.json")) as f:
            saved = json.load(f)
        self.assertEqual((saved["access_token"], saved["user_id"]), ("token-1", "user-1"))
        await self.a.stop()
        b = self.cls(dict(ACCOUNT), self.dir)
        await b.discover()
        await b.stop()
        self.assertEqual(cloud.logins[0]["device_id"], cloud.logins[1]["device_id"])   # same "phone" each time
        self.assertEqual(cloud.logins[1]["known"].access_token, "token-1")

    async def test_needs_email_code(self):
        cloud.login_error = DeviceVerificationRequiredError()
        with self.assertRaises(AdapterError) as e:
            await self.a.discover()
        self.assertIn("Email me a code", str(e.exception))
        r = await self.a.run_account_action("send_code")
        self.assertEqual(cloud.codes_sent, 1)
        self.assertIn("Check your email", r["message"])
        self.a.account["code"] = "000000"
        with self.assertRaises(AdapterError) as e:
            await self.a.run_account_action("verify")
        self.assertIn("didn't work", str(e.exception))
        self.a.account["code"] = " 123456 "
        r = await self.a.run_account_action("verify")
        self.assertEqual(r["account"], {"code": ""})                  # the used code is cleared
        self.assertEqual(cloud.verified, ["123456"])

    async def test_wrong_password_and_missing_account(self):
        cloud.login_error = InvalidAuthenticationError("1005")
        with self.assertRaises(AdapterError) as e:
            await self.a.discover()
        self.assertIn("didn't accept that email and password", str(e.exception))
        empty = self.cls({}, self.dir)
        with self.assertRaises(AdapterError) as e:
            await empty.discover()
        self.assertIn("Add your Ecovacs email", str(e.exception))

    async def test_old_model_is_explained(self):
        cloud.devices, cloud.legacy = [], [{"did": "old", "deviceName": "DEEBOT N79"}]
        with self.assertRaises(AdapterError) as e:
            await self.a.discover()
        self.assertIn("DEEBOT N79", str(e.exception))
        self.assertIn("isn't supported yet", str(e.exception))


if __name__ == "__main__":
    unittest.main()
