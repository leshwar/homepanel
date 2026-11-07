"""
The adapter layer: the one interface every device brand implements.

    ┌───────────────────────────────┐
    │  API layer   (app/api)        │  stable HTTP + live-events API used by the UI
    ├───────────────────────────────┤
    │  Service layer (app/core)     │  registry, state cache, polling, scenes,
    │                               │  validation, timeouts, retries, events
    ├───────────────────────────────┤
    │  Adapter interface (this file)│  DeviceAdapter: discover / refresh / command
    ├───────────────────────────────┤
    │  Adapters (app/adapters/*.py) │  Tuya, Govee, Kasa, Shelly, WiZ, Hue,
    │                               │  Samsung TV, LG TV, Demo …
    └───────────────────────────────┘

The UI and the API never talk to a brand directly. They send generic commands
("power", "brightness", "volume_up", "key: UP" …) and the service routes them to
the adapter that owns the device. To support a new brand, add one file in
app/adapters/ that subclasses DeviceAdapter and decorate it with @register.
Nothing above this layer changes.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar


# ---------------------------------------------------------------------------
# Generic vocabulary shared by every adapter
# ---------------------------------------------------------------------------

class Kind:
    LIGHT = "light"
    PLUG = "plug"
    SWITCH = "switch"
    TV = "tv"
    FAN = "fan"
    PURIFIER = "purifier"
    VACUUM = "vacuum"
    SPEAKER = "speaker"        # sound bars and speakers: volume, inputs, sound modes
    OTHER = "other"

    ALL = (LIGHT, PLUG, SWITCH, TV, FAN, PURIFIER, VACUUM, SPEAKER, OTHER)


class Cap:
    """Capabilities a device can advertise. The UI draws controls from these."""
    POWER = "power"            # on / off
    BRIGHTNESS = "brightness"  # 0-100
    COLOR = "color"            # {"r","g","b"} 0-255
    COLOR_TEMP = "color_temp"  # kelvin
    VOLUME = "volume"          # volume_up / volume_down (and level when readable)
    VOLUME_LEVEL = "volume_level"  # can set an exact 0-100 level
    MUTE = "mute"
    CHANNEL = "channel"        # channel_up / channel_down
    REMOTE = "remote"          # navigation keys (see Key)
    MEDIA = "media"            # play / pause / stop / forward / rewind keys only
    APPS = "apps"              # launch_app
    INPUTS = "inputs"          # set_input
    CLEAN = "clean"            # robot vacuum: start / pause / resume / stop cleaning
    DOCK = "dock"              # robot vacuum: go back to the charging dock
    ROOMS = "rooms"            # clean chosen rooms (meta["rooms"])
    SUCTION = "suction"        # suction power levels (meta["suction_levels"])
    CLEAN_MODE = "clean_mode"  # vacuum / mop / both (meta["clean_modes"])
    STATION = "station"        # dock station jobs, e.g. empty dustbin (meta["station_actions"])
    LOCATE = "locate"          # play a sound to find the device
    MAP = "map"                # a picture of the floor plan: GET /devices/{id}/map
    POINTER = "pointer"        # an on-screen pointer the panel can move, click and scroll (touchpad)
    SOUND_MODE = "sound_mode"  # set_sound_mode (meta["sound_modes"])
    FAN_SPEED = "fan_speed"    # meta["fan_speeds"]
    FAN_MODE = "fan_mode"      # meta["fan_modes"]
    AIR_QUALITY = "air_quality"  # read-only device-reported PM2.5 / quality
    FILTER_LIFE = "filter_life"  # read-only remaining filter percentage
    # Light effects. The device lists what it has in meta; the UI draws one section per cap.
    EFFECTS = "effects"        # set_effect: meta["effects"] = [{"id","name","group"}] (group: Effect.GROUPS)
    MUSIC = "music"            # set_music: meta["music_modes"] = [{"id","name"}]; light follows sound
    SEGMENTS = "segments"      # set_segments: meta["segments"] = how many parts of a strip can be colored apart
    TOGGLES = "toggles"        # set_toggle: meta["toggles"] = [{"id","name"}] (Effect.TOGGLES), e.g. night light


class Action:
    """Commands the API accepts. Adapters implement the ones they support."""
    POWER = "power"            # value: bool
    TOGGLE = "toggle"          # no value; handled by the service layer
    BRIGHTNESS = "brightness"  # value: 1-100
    COLOR = "color"            # value: {"r","g","b"} or "#rrggbb"
    COLOR_TEMP = "color_temp"  # value: kelvin
    VOLUME = "volume"          # value: 0-100
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"              # value: bool
    CHANNEL_UP = "channel_up"
    CHANNEL_DOWN = "channel_down"
    KEY = "key"                # value: one of Key.ALL
    LAUNCH_APP = "launch_app"  # value: app id
    SET_INPUT = "set_input"    # value: input id
    CLEAN = "clean"            # value: one of Clean.ALL
    DOCK = "dock"              # no value
    CLEAN_ROOMS = "clean_rooms"        # value: list of room ids from meta["rooms"]
    SET_SUCTION = "set_suction"        # value: id from meta["suction_levels"]
    SET_CLEAN_MODE = "set_clean_mode"  # value: id from meta["clean_modes"]
    STATION = "station"                # value: id from meta["station_actions"]
    LOCATE = "locate"                  # no value
    SET_SOUND_MODE = "set_sound_mode"  # value: id from meta["sound_modes"]
    SET_FAN_SPEED = "set_fan_speed"
    SET_FAN_MODE = "set_fan_mode"
    SET_EFFECT = "set_effect"          # value: id from meta["effects"]
    SET_MUSIC = "set_music"            # value: {"mode": id from meta["music_modes"], "sensitivity": 0-100}
    # value: {"segments": [0-based indexes < meta["segments"]], "color": rgb, and/or "brightness": 0-100}
    SET_SEGMENTS = "set_segments"
    SET_TOGGLE = "set_toggle"          # value: {"id": id from meta["toggles"], "on": bool}
    UPDATE_EFFECTS = "update_effects"  # no value: read the device's effect lists again (they're cached)
    # value: {"dx": int, "dy": int} to move, {"click": true} to click, {"scroll": int} to scroll
    # (positive = down). The service normalizes it to exactly one of those three shapes.
    POINTER = "pointer"

    ALL = (POWER, TOGGLE, BRIGHTNESS, COLOR, COLOR_TEMP, VOLUME, VOLUME_UP,
           VOLUME_DOWN, MUTE, CHANNEL_UP, CHANNEL_DOWN, KEY, LAUNCH_APP, SET_INPUT,
           CLEAN, DOCK, CLEAN_ROOMS, SET_SUCTION, SET_CLEAN_MODE, STATION, LOCATE, SET_SOUND_MODE,
           POINTER, SET_EFFECT, SET_MUSIC, SET_SEGMENTS, SET_TOGGLE, UPDATE_EFFECTS, SET_FAN_SPEED, SET_FAN_MODE)

    # Fire-and-forget actions that don't change the device's state: the service doesn't
    # broadcast or re-read the device after them, and logs them only in debug mode.
    QUIET = (POINTER,)

    # Which capability each action needs (service layer checks this).
    REQUIRES = {
        POWER: Cap.POWER, TOGGLE: Cap.POWER, BRIGHTNESS: Cap.BRIGHTNESS,
        COLOR: Cap.COLOR, COLOR_TEMP: Cap.COLOR_TEMP, VOLUME: Cap.VOLUME_LEVEL,
        VOLUME_UP: Cap.VOLUME, VOLUME_DOWN: Cap.VOLUME, MUTE: Cap.MUTE,
        CHANNEL_UP: Cap.CHANNEL, CHANNEL_DOWN: Cap.CHANNEL, KEY: Cap.REMOTE,
        LAUNCH_APP: Cap.APPS, SET_INPUT: Cap.INPUTS, CLEAN: Cap.CLEAN, DOCK: Cap.DOCK,
        CLEAN_ROOMS: Cap.ROOMS, SET_SUCTION: Cap.SUCTION, SET_CLEAN_MODE: Cap.CLEAN_MODE,
        STATION: Cap.STATION, LOCATE: Cap.LOCATE, SET_SOUND_MODE: Cap.SOUND_MODE, POINTER: Cap.POINTER,
        SET_EFFECT: Cap.EFFECTS, SET_MUSIC: Cap.MUSIC, SET_SEGMENTS: Cap.SEGMENTS, SET_TOGGLE: Cap.TOGGLES,
        UPDATE_EFFECTS: Cap.EFFECTS,
        SET_FAN_SPEED: Cap.FAN_SPEED, SET_FAN_MODE: Cap.FAN_MODE,
    }

    # What each action is, for "<device> can't …" messages.
    WORDS = {SET_EFFECT: "play scenes", SET_MUSIC: "follow music", SET_SEGMENTS: "color parts of the strip",
             SET_TOGGLE: "switch that feature", UPDATE_EFFECTS: "play scenes"}

    # Actions whose value must be one of the ids the device lists in device.meta[...].
    OPTIONS = {SET_SUCTION: "suction_levels", SET_CLEAN_MODE: "clean_modes", STATION: "station_actions",
               SET_SOUND_MODE: "sound_modes", SET_EFFECT: "effects",
               SET_FAN_SPEED: "fan_speeds", SET_FAN_MODE: "fan_modes"}


class Key:
    """Brand-neutral remote keys. TV adapters translate them to their own codes."""
    UP, DOWN, LEFT, RIGHT, OK = "UP", "DOWN", "LEFT", "RIGHT", "OK"
    BACK, HOME, MENU, SOURCE = "BACK", "HOME", "MENU", "SOURCE"
    PLAY, PAUSE, STOP = "PLAY", "PAUSE", "STOP"
    REWIND, FORWARD = "REWIND", "FORWARD"
    EXIT, CHANNEL_LIST, INFO = "EXIT", "CHANNEL_LIST", "INFO"
    DIGITS = tuple(str(n) for n in range(10))    # "0" … "9" for the number pad

    ALL = (UP, DOWN, LEFT, RIGHT, OK, BACK, HOME, MENU, SOURCE,
           PLAY, PAUSE, STOP, REWIND, FORWARD, EXIT, CHANNEL_LIST, INFO, *DIGITS)
    MEDIA = (PLAY, PAUSE, STOP, REWIND, FORWARD)   # allowed with Cap.MEDIA alone


class Effect:
    """Shared words for light effects (Cap.EFFECTS, Cap.MUSIC, Cap.TOGGLES)."""
    SCENES, DIY, SNAPSHOTS = "Scenes", "DIY", "Snapshots"     # meta["effects"][i]["group"], in display order
    GROUPS = (SCENES, DIY, SNAPSHOTS)
    NIGHT_LIGHT, GRADIENT, SYNC = "night_light", "gradient", "sync"   # meta["toggles"] ids
    TOGGLES = (NIGHT_LIGHT, GRADIENT, SYNC)
    # state["color_mode"] is "color" or "temp" for plain light; these mean an effect is showing:
    MODES = ("effect", "music", "segments")


class Pointer:
    """Limits for Action.POINTER values (pixels per message)."""
    MAX_MOVE = 400
    MAX_SCROLL = 400


class Clean:
    """Values for Action.CLEAN."""
    START, PAUSE, RESUME, STOP = "start", "pause", "resume", "stop"
    ALL = (START, PAUSE, RESUME, STOP)


class Activity:
    """What a robot vacuum is doing: the `activity` state key."""
    CLEANING, PAUSED, RETURNING = "cleaning", "paused", "returning"
    DOCKED, IDLE, ERROR = "docked", "idle", "error"
    ALL = (CLEANING, PAUSED, RETURNING, DOCKED, IDLE, ERROR)


# ---------------------------------------------------------------------------
# Data passed between the service and adapters
# ---------------------------------------------------------------------------

@dataclass
class Field:
    """A setup field the UI renders as a form input (for accounts or manual add)."""
    key: str
    label: str
    type: str = "text"          # text | password | number | select
    required: bool = False
    placeholder: str = ""
    help: str = ""
    options: list[dict] = field(default_factory=list)   # for select: [{value,label}]
    default: Any = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "", [])}


@dataclass
class Device:
    """One device the user added. `config` is adapter-private (IPs, keys, tokens)."""
    id: str
    adapter: str
    name: str
    kind: str = Kind.OTHER
    room: str = ""
    icon: str = ""
    config: dict = field(default_factory=dict)
    caps: list[str] = field(default_factory=list)
    keep_on: bool = False          # skip this device in "All off" (e.g. a fridge plug)
    picture: str = ""              # the user's own photo of it (file in data/device-pictures/), or ""
    # Live state – owned by the service, filled from adapter.refresh()/command()
    state: dict = field(default_factory=dict)
    # Extra info for the UI: available apps/inputs, model name …
    meta: dict = field(default_factory=dict)


@dataclass
class Found:
    """Something an adapter discovered on the network but the user hasn't added yet."""
    adapter: str
    uid: str                 # stable unique id (MAC, device id …) used to avoid duplicates
    name: str
    kind: str
    config: dict
    caps: list[str] = field(default_factory=list)
    detail: str = ""         # e.g. "192.168.1.40 · H5083"
    needs_pairing: bool = False
    room: str = ""           # suggested room, if the source knows one (e.g. a Home Assistant area)
    # Other ids the same device may have been saved under (e.g. an SSDP uuid when uid is the MAC,
    # or the uid an older version of the adapter used). Matched like uid to avoid duplicates.
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d.pop("config", None)  # never send secrets to the browser
        d.pop("aliases", None)
        return d


class AdapterError(Exception):
    """Raised by adapters with a message that is safe to show to the user."""


class PairingRequired(AdapterError):
    """The device needs the user to approve this panel (e.g. 'Allow' prompt on a TV)."""


class AdapterBackoff(AdapterError):
    """A safe provider error requesting a service-managed cooldown."""
    def __init__(self, message: str, seconds: int = 60):
        super().__init__(message)
        self.seconds = max(1, min(900, seconds))


# ---------------------------------------------------------------------------
# The interface
# ---------------------------------------------------------------------------

class DeviceAdapter(abc.ABC):
    """Base class for a brand / protocol. One instance per adapter type."""

    # --- describe yourself (shown on the "Add device" screen) ---
    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    brands: ClassVar[str] = ""            # e.g. "Globe, Feit, Gosund, Smart Life"
    kinds: ClassVar[tuple] = ()
    description: ClassVar[str] = ""
    # Python packages this adapter needs; missing ones disable it gracefully.
    requires: ClassVar[tuple] = ()
    # Python versions the brand's library works on, e.g. ((3, 14),). None = any.
    # Elsewhere the brand is "not supported on this Python" rather than "not installed".
    python_versions: ClassVar[tuple | None] = None
    # Account-level settings (API keys, logins) shared by all devices of this adapter.
    account_fields: ClassVar[list[Field]] = []
    # Fields to add a device by hand when discovery can't find it.
    manual_fields: ClassVar[list[Field]] = []
    can_discover: ClassVar[bool] = True
    # Seconds between state refreshes. Cloud APIs should poll slowly.
    poll_interval: ClassVar[float] = 15.0
    failure_backoff: ClassVar[int] = 0  # optional service-managed cooldown after provider failures
    # Hidden from the Add screen (used by the demo adapter).
    hidden: ClassVar[bool] = False

    def __init__(self, account: dict, data_dir: str):
        self.account = account or {}
        self.data_dir = data_dir

    # --- lifecycle ---
    async def start(self) -> None:
        """Called once when the server starts (open sockets, etc.)."""

    async def stop(self) -> None:
        """Called on shutdown."""

    def account_changed(self, account: dict) -> None:
        self.account = account or {}

    # --- push updates ---
    # The service sets this. Adapters that hear about changes on their own (live
    # connections, events) call changed(uid) so the panel refreshes that device now
    # instead of waiting for the next poll.
    on_change: Callable[[str], None] | None = None

    def changed(self, uid: str) -> None:
        if self.on_change:
            self.on_change(uid)

    # --- account-level actions (e.g. "Pair with Hue bridge") ---
    account_actions: ClassVar[list[dict]] = []   # [{"id","label","help"}]

    async def run_account_action(self, action: str) -> dict:
        """Returns account fields to merge and save, plus an optional message."""
        raise AdapterError("Not supported")

    # --- devices ---
    async def discover(self, timeout: float = 6.0) -> list[Found]:
        """Look for devices on the network or in the brand's cloud account."""
        return []

    async def map_image(self, device: Device) -> tuple[str, bytes] | None:
        """For Cap.MAP: (content type, image bytes) of the device's floor plan, or None if not ready."""
        return None

    def from_manual(self, values: dict) -> Found:
        """Build a device from the manual-add form."""
        raise AdapterError("This brand can't be added by hand. Use Search.")

    def known_ids(self, device: Device) -> set[str]:
        """Every id a saved device may turn up under in discovery (its uid and aliases).
        Override to add ids the adapter learns later, e.g. a MAC address found after pairing."""
        ids = {device.config.get("_uid"), *device.config.get("_aliases", [])}
        return {i for i in ids if i}

    async def setup(self, device: Device) -> None:
        """First connection after adding. May raise PairingRequired.
        May update device.config (tokens), device.caps and device.meta."""
        await self.refresh(device)

    @abc.abstractmethod
    async def refresh(self, device: Device) -> dict:
        """Return the current state dict, e.g. {"online": True, "on": True, "brightness": 40}."""

    @abc.abstractmethod
    async def command(self, device: Device, action: str, value: Any = None) -> dict | None:
        """Carry out a generic Action. Return the state keys that changed (optimistic)."""

    async def forget(self, device: Device) -> None:
        """Clean up when the user removes a device."""


# ---------------------------------------------------------------------------
# Registry — adapters register themselves with @register
# ---------------------------------------------------------------------------

ADAPTERS: dict[str, type[DeviceAdapter]] = {}


def register(cls: type[DeviceAdapter]) -> type[DeviceAdapter]:
    if not cls.id:
        raise ValueError(f"{cls.__name__} needs an id")
    ADAPTERS[cls.id] = cls
    return cls


def unsupported_reason(cls: type[DeviceAdapter]) -> str:
    """Why this brand can't run on this Python at all ("" if it can)."""
    import sys
    if cls.python_versions and tuple(sys.version_info[:2]) not in cls.python_versions:
        want = " or ".join(".".join(map(str, v)) for v in cls.python_versions)
        return f"Needs Python {want} (this panel has {sys.version_info[0]}.{sys.version_info[1]})"
    return ""


def missing_requirements(cls: type[DeviceAdapter]) -> list[str]:
    import importlib.util
    missing = []
    for mod in cls.requires:
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    return missing
