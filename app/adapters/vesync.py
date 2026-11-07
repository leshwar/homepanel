"""Levoit Core300S through the pinned asynchronous pyvesync 3.5 API."""
from __future__ import annotations

import asyncio
import logging
import math

from ..core.adapter import Action, AdapterBackoff, AdapterError, Cap, Device, DeviceAdapter, Field, Found, Kind, register

# These model identifiers share the Core300S map in pyvesync 3.5.0.
MODELS = {"Core300S", "LAP-C301S-WJP", "LAP-C302S-WUSB", "LAP-C301S-WAAA", "LAP-C302S-WGC"}
MODES = {"manual": "Manual", "auto": "Automatic", "sleep": "Sleep"}
logging.getLogger("pyvesync").setLevel(logging.WARNING)


def _number(value, maximum=None):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        raise AdapterError("The purifier returned an invalid reading. Refresh its status.")
    return value


@register
class VeSyncAdapter(DeviceAdapter):
    id = "vesync"
    name = "VeSync / Levoit"
    brands = "Levoit Core300S air purifiers"
    kinds = (Kind.PURIFIER,)
    description = "Uses your VeSync cloud account. The panel and purifier need internet, not the same local network."
    requires = ("pyvesync",)
    poll_interval = 60
    failure_backoff = 60
    account_fields = [
        Field("email", "VeSync email", required=True, placeholder="you@example.com"),
        Field("password", "VeSync password", "password", required=True),
        Field("country", "Account country", "select", required=True, default="US",
              options=[{"value": code, "label": label} for code, label in
                       [("US", "United States"), ("CA", "Canada"), ("GB", "United Kingdom"), ("DE", "Germany"),
                        ("FR", "France"), ("AU", "Australia"), ("NZ", "New Zealand"), ("IN", "India"),
                        ("JP", "Japan"), ("SG", "Singapore")]]),
    ]
    account_actions = [{"id": "verify", "label": "Verify connection",
                        "help": "Save your account first. This checks sign-in and lists supported purifiers without operating them."}]

    def __init__(self, account, data_dir):
        super().__init__(account, data_dir)
        self._manager = None
        self._dirty = False
        self._lock = asyncio.Lock()
        self._devices = {}

    def account_changed(self, account):
        super().account_changed(account)
        self._dirty = True

    async def stop(self):
        async with self._lock:
            await self._close()

    async def _close(self):
        manager, self._manager = self._manager, None
        self._devices = {}
        if manager:
            await manager.__aexit__(None, None, None)

    async def _perform(self, call):
        from aiohttp import ClientError
        from pyvesync.utils.errors import VeSyncError, VeSyncLoginError, VeSyncRateLimitError, VeSyncTokenError
        try:
            return await call()
        except (VeSyncLoginError, VeSyncTokenError):
            self._dirty = True
            raise AdapterBackoff("VeSync sign-in failed. Check the saved account, password and country in Settings.", 300) from None
        except VeSyncRateLimitError:
            raise AdapterBackoff("VeSync is rate-limiting requests. Wait before trying again.", 300) from None
        except (VeSyncError, ClientError, OSError):
            raise AdapterBackoff("The VeSync cloud could not be reached or returned an error. Check internet access and the VeSync app.", 60) from None

    def _checked(self, result, device=None):
        response = getattr(device, "last_response", None)
        error = str(getattr(response, "error_type", "success"))
        if error in ("auth_error", "token_error"):
            self._dirty = True
            raise AdapterBackoff("VeSync sign-in expired. Check your saved account in Settings.", 300)
        if error == "rate_limit_error":
            raise AdapterBackoff("VeSync is rate-limiting requests. Wait before trying again.", 300)
        if error == "device_offline":
            raise AdapterBackoff("The purifier is offline in VeSync. Check its power and internet connection in the VeSync app.", 60)
        if result is False or error != "success":
            raise AdapterBackoff("VeSync did not accept the request. Check the device in the VeSync app.", 60)

    async def _connect(self):
        if self._dirty:
            await self._close()
            self._dirty = False
        if self._manager:
            return False
        email, password = self.account.get("email"), self.account.get("password")
        country = self.account.get("country") or "US"
        if not isinstance(email, str) or not email.strip() or not isinstance(password, str) or not password:
            raise AdapterError("Save your VeSync email and password in Settings first.")
        if not isinstance(country, str) or len(country) != 2 or not country.isascii() or not country.isalpha():
            raise AdapterError("Choose the two-letter country for your VeSync account.")
        from importlib.metadata import PackageNotFoundError, version
        try:
            supported = version("pyvesync") == "3.5.0"
        except PackageNotFoundError:
            supported = False
        if not supported:
            raise AdapterError("This connection needs pyvesync 3.5.0. Run make setup to install the supported version.")
        from pyvesync import VeSync
        manager = VeSync(email.strip(), password, country_code=country.upper(), redact=True)
        manager.verbose = False
        try:
            logged_in = await self._perform(manager.login)
            if logged_in is not True or not manager.enabled:
                raise AdapterBackoff("VeSync sign-in was not completed. Check your saved account.", 300)
            self._checked(await self._perform(manager.get_devices))
            self._manager = manager
        finally:
            if self._manager is not manager:
                await manager.__aexit__(None, None, None)
        self._devices = {str(d.cid): d for d in manager.devices.air_purifiers if d.device_type in MODELS}
        return True

    async def discover(self, timeout=6.0):
        async with self._lock:
            created = await self._connect()
            if not created:
                self._checked(await self._perform(self._manager.get_devices))
            self._devices = {str(d.cid): d for d in self._manager.devices.air_purifiers if d.device_type in MODELS}
            return [Found(adapter=self.id, uid=uid, name=d.device_name or "Air purifier", kind=Kind.PURIFIER,
                          caps=self._caps(d), config={"cid": uid}, detail=f"Levoit {d.device_type} (cloud)")
                    for uid, d in self._devices.items()]

    async def run_account_action(self, action):
        if action != "verify":
            raise AdapterError("Unknown connection action.")
        found = await self.discover()
        return {"message": f"Connected to VeSync. Found {len(found)} supported Core300S purifier(s). Use Search to add one."}

    @staticmethod
    def _caps(device):
        return [Cap.POWER, Cap.FAN_SPEED, Cap.FAN_MODE, Cap.FILTER_LIFE] \
            + ([Cap.AIR_QUALITY] if device.supports_air_quality else [])

    async def _device(self, device: Device):
        await self._connect()
        found = self._devices.get(str(device.config.get("cid")))
        if found is None:
            raise AdapterError("This Core300S is not available on the saved VeSync account. Search again.")
        device.caps = self._caps(found)
        device.meta = {"model": found.device_type, "connection": "cloud",
                       "fan_speeds": [{"id": str(n), "name": f"Speed {n}"} for n in found.fan_levels if n in (1, 2, 3)],
                       "fan_modes": [{"id": mode, "name": MODES[mode]} for mode in found.modes if mode in MODES]}
        return found

    def _state(self, device):
        state = device.state
        if str(state.connection_status) != "online":
            raise AdapterBackoff("The purifier is offline in VeSync. Check its power and internet connection in the VeSync app.", 60)
        result = {}
        if str(state.device_status) in ("on", "off"):
            result["on"] = str(state.device_status) == "on"
        if state.mode in MODES:
            result["fan_mode"] = str(state.mode)
        if state.fan_level is not None:
            result["fan_speed"] = str(state.fan_level)
        for key, value in (("filter_life", _number(state.filter_life, 100)),
                           ("pm25", _number(state.pm25) if device.supports_air_quality else None)):
            if value is not None:
                result[key] = value
        if device.supports_air_quality and state.air_quality_string:
            result["air_quality"] = str(state.air_quality_string).capitalize()
        return result

    async def setup(self, device):
        async with self._lock:
            await self._device(device)

    async def refresh(self, device):
        async with self._lock:
            purifier = await self._device(device)
            await self._perform(purifier.update)
            self._checked(None, purifier)
            return self._state(purifier)

    async def command(self, device, action, value=None):
        async with self._lock:
            purifier = await self._device(device)
            if action == Action.POWER:
                operation = purifier.turn_on if value else purifier.turn_off
            elif action == Action.SET_FAN_SPEED and str(value) in {o["id"] for o in device.meta["fan_speeds"]}:
                operation = lambda: purifier.set_fan_speed(int(value))
            elif action == Action.SET_FAN_MODE and value in {o["id"] for o in device.meta["fan_modes"]}:
                operation = lambda: purifier.set_mode(value)
            else:
                raise AdapterError("That purifier control is not supported.")
            self._checked(await self._perform(operation), purifier)
            return self._state(purifier)
