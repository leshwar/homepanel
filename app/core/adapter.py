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
from typing import Any, ClassVar


# ---------------------------------------------------------------------------
# Generic vocabulary shared by every adapter
# ---------------------------------------------------------------------------

class Kind:
    LIGHT = "light"
    PLUG = "plug"
    SWITCH = "switch"
    TV = "tv"
    FAN = "fan"
    OTHER = "other"

    ALL = (LIGHT, PLUG, SWITCH, TV, FAN, OTHER)


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

    ALL = (POWER, TOGGLE, BRIGHTNESS, COLOR, COLOR_TEMP, VOLUME, VOLUME_UP,
           VOLUME_DOWN, MUTE, CHANNEL_UP, CHANNEL_DOWN, KEY, LAUNCH_APP, SET_INPUT)

    # Which capability each action needs (service layer checks this).
    REQUIRES = {
        POWER: Cap.POWER, TOGGLE: Cap.POWER, BRIGHTNESS: Cap.BRIGHTNESS,
        COLOR: Cap.COLOR, COLOR_TEMP: Cap.COLOR_TEMP, VOLUME: Cap.VOLUME_LEVEL,
        VOLUME_UP: Cap.VOLUME, VOLUME_DOWN: Cap.VOLUME, MUTE: Cap.MUTE,
        CHANNEL_UP: Cap.CHANNEL, CHANNEL_DOWN: Cap.CHANNEL, KEY: Cap.REMOTE,
        LAUNCH_APP: Cap.APPS, SET_INPUT: Cap.INPUTS,
    }


class Key:
    """Brand-neutral remote keys. TV adapters translate them to their own codes."""
    UP, DOWN, LEFT, RIGHT, OK = "UP", "DOWN", "LEFT", "RIGHT", "OK"
    BACK, HOME, MENU, SOURCE = "BACK", "HOME", "MENU", "SOURCE"
    PLAY, PAUSE, STOP = "PLAY", "PAUSE", "STOP"
    REWIND, FORWARD = "REWIND", "FORWARD"

    ALL = (UP, DOWN, LEFT, RIGHT, OK, BACK, HOME, MENU, SOURCE,
           PLAY, PAUSE, STOP, REWIND, FORWARD)
    MEDIA = (PLAY, PAUSE, STOP, REWIND, FORWARD)   # allowed with Cap.MEDIA alone


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
    # Account-level settings (API keys, logins) shared by all devices of this adapter.
    account_fields: ClassVar[list[Field]] = []
    # Fields to add a device by hand when discovery can't find it.
    manual_fields: ClassVar[list[Field]] = []
    can_discover: ClassVar[bool] = True
    # Seconds between state refreshes. Cloud APIs should poll slowly.
    poll_interval: ClassVar[float] = 15.0
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

    # --- account-level actions (e.g. "Pair with Hue bridge") ---
    account_actions: ClassVar[list[dict]] = []   # [{"id","label","help"}]

    async def run_account_action(self, action: str) -> dict:
        """Returns account fields to merge and save, plus an optional message."""
        raise AdapterError("Not supported")

    # --- devices ---
    async def discover(self, timeout: float = 6.0) -> list[Found]:
        """Look for devices on the network or in the brand's cloud account."""
        return []

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


def missing_requirements(cls: type[DeviceAdapter]) -> list[str]:
    import importlib.util
    missing = []
    for mod in cls.requires:
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    return missing
