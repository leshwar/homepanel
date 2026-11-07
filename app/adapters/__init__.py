"""
Device adapters. Each module registers one DeviceAdapter with @register.

To add a brand: copy an existing module (shelly.py is the simplest), change the
class, and add its module name to the list below. Third-party libraries must be
imported inside methods, so a missing library only disables that one adapter.
"""
import importlib
import logging


def photo_source(url: str, key: str):
    from .immich_photos import PhotoSource
    return PhotoSource(url, key)


def photo_source_info():
    from .immich_photos import NAME, PERMISSIONS
    return {"name": NAME, "permissions": PERMISSIONS}


MODULES = [
    "demo",
    "tuya",        # Globe Electric, Feit, Gosund, Treatlife, any "Smart Life" device
    "govee",       # Govee plugs (cloud API) and lights (LAN API)
    "kasa",        # TP-Link Kasa and Tapo
    "shelly",      # Shelly relays and plugs
    "wiz",         # WiZ / Philips WiZ bulbs
    "hue",         # Philips Hue (bridge)
    "samsung_tv",  # Samsung Tizen TVs (2016+)
    "lg_tv",       # LG webOS TVs
    "lg_soundbar",  # LG sound bars with Wi-Fi
    "home_assistant",  # anything an existing Home Assistant controls
    "ecovacs",     # Ecovacs Deebot robot vacuums (cloud)
    "vesync",      # Levoit Core300S air purifiers (cloud)
]

for _name in MODULES:
    try:
        importlib.import_module(f"{__name__}.{_name}")
    except Exception as e:  # never let one adapter break start-up
        logging.getLogger("homepanel").exception("Couldn't load adapter %s: %s", _name, e)
