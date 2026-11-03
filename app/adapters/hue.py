"""Philips Hue lights and plugs through the Hue Bridge's local API."""
from __future__ import annotations

from ..core.adapter import Action, AdapterError, Cap, Device, DeviceAdapter, Field, Found, Kind, register
from ..core.net import http, rgb_to_xy, xy_to_rgb


@register
class HueAdapter(DeviceAdapter):
    id = "hue"
    name = "Philips Hue"
    brands = "Philips Hue bulbs, strips and smart plugs (needs a Hue Bridge)"
    kinds = (Kind.LIGHT, Kind.PLUG)
    description = "Local control through your Hue Bridge. Press the bridge button once to connect."
    poll_interval = 6
    account_fields = [
        Field("bridge_ip", "Bridge IP address", placeholder="Leave blank to find it automatically"),
        Field("username", "Bridge app key", "password", help="Filled in for you when you press Connect."),
    ]
    account_actions = [{"id": "pair", "label": "Connect to bridge",
                        "help": "Press the round button on top of the Hue Bridge, then tap Connect within 30 seconds."}]

    def _base(self) -> str:
        ip, user = self.account.get("bridge_ip"), self.account.get("username")
        if not ip or not user:
            raise AdapterError("Connect your Hue Bridge first: Settings → Philips Hue → Connect to bridge.")
        return f"http://{ip}/api/{user}"

    async def run_account_action(self, action):
        if action != "pair":
            raise AdapterError("Unknown action")
        ip = self.account.get("bridge_ip")
        if not ip:
            bridges = await http("GET", "https://discovery.meethue.com/", timeout=8)
            if not bridges:
                raise AdapterError("No Hue Bridge found. Enter its IP address (shown in the Hue app → Settings → Bridges).")
            ip = bridges[0]["internalipaddress"]
        res = await http("POST", f"http://{ip}/api", json_body={"devicetype": "homepanel#raspberrypi"})
        item = (res or [{}])[0]
        if "error" in item:
            if item["error"].get("type") == 101:
                raise AdapterError("Press the button on the Hue Bridge first, then tap Connect again.")
            raise AdapterError(item["error"].get("description", "Bridge refused the connection"))
        return {"account": {"bridge_ip": ip, "username": item["success"]["username"]},
                "message": "Connected to your Hue Bridge"}

    async def discover(self, timeout=6.0):
        lights = await http("GET", f"{self._base()}/lights")
        if isinstance(lights, list) and lights and "error" in lights[0]:
            raise AdapterError("The bridge rejected the saved key. Connect to the bridge again.")
        found = []
        for lid, light in (lights or {}).items():
            kind, caps = _kind_caps(light.get("type", ""))
            found.append(Found(adapter=self.id, uid=light.get("uniqueid") or lid, name=light.get("name", f"Hue {lid}"),
                               kind=kind, caps=caps, config={"light_id": lid},
                               detail=light.get("productname") or light.get("type", "")))
        return found

    async def refresh(self, device: Device) -> dict:
        light = await http("GET", f"{self._base()}/lights/{device.config['light_id']}")
        if isinstance(light, list):
            raise AdapterError("Light not found on the bridge")
        s = light.get("state", {})
        if s.get("reachable") is False:
            raise ConnectionError("The bridge can't reach this light (is it switched off at the wall?)")
        state = {"on": bool(s.get("on"))}
        if "bri" in s:
            state["brightness"] = max(1, round(s["bri"] / 254 * 100))
        if s.get("colormode") == "ct" and s.get("ct"):
            state.update(color_temp=round(1_000_000 / s["ct"]), color_mode="temp")
        elif s.get("colormode") in ("xy", "hs") and s.get("xy"):
            state.update(color=xy_to_rgb(*s["xy"]), color_mode="color")
        return state

    async def command(self, device: Device, action: str, value=None):
        body, out = {}, {}
        if action == Action.POWER:
            body, out = {"on": value}, {"on": value}
        elif action == Action.BRIGHTNESS:
            body, out = {"on": True, "bri": max(1, round(value / 100 * 254))}, {"on": True, "brightness": value}
        elif action == Action.COLOR:
            body, out = {"on": True, "xy": rgb_to_xy(value)}, {"on": True, "color": value, "color_mode": "color"}
        elif action == Action.COLOR_TEMP:
            mired = max(153, min(500, round(1_000_000 / value)))
            body, out = {"on": True, "ct": mired}, {"on": True, "color_temp": value, "color_mode": "temp"}
        else:
            raise AdapterError("Not supported")
        res = await http("PUT", f"{self._base()}/lights/{device.config['light_id']}/state", json_body=body)
        errors = [r["error"]["description"] for r in (res or []) if isinstance(r, dict) and "error" in r]
        if errors:
            raise AdapterError(errors[0])
        return out


def _kind_caps(light_type: str):
    t = light_type.lower()
    if "plug" in t or "on/off" in t:
        return Kind.PLUG, [Cap.POWER]
    if "extended color" in t:
        return Kind.LIGHT, [Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR, Cap.COLOR_TEMP]
    if "color light" in t:
        return Kind.LIGHT, [Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR]
    if "temperature" in t:
        return Kind.LIGHT, [Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR_TEMP]
    return Kind.LIGHT, [Cap.POWER, Cap.BRIGHTNESS]
