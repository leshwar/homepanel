"""The Home page layout: which widgets are on it, their order, size and options.

Kept as one plain object in settings (`home_layout`) so every screen shows the
same Home page. It is self-contained on purpose: when profiles arrive, each
profile can hold its own copy without anything else changing.

    {"version": 1,
     "widgets": [{"id": "clock", "type": "clock", "size": "2x2", "hidden": false, "options": {}},
                 {"id": "zone-in", "type": "zone", "size": "1x1", "options": {"tz": "Asia/Kolkata", "label": "India"}},
                 {"id": "rooms", "type": "rooms", "size": "2x2", "options": {}}, ...]}

Devices live on the Rooms pages, not on Home. Layouts saved before version 2 could
hold "device" widgets; `migrate_layout` drops them, and a "device" widget sent by an
old screen is dropped too, so nobody is left with an empty slot.

Sizes are columns x rows of the Home grid. The UI decides how each widget looks
at each size. `options.tz = None` on a clock means "this screen's own time zone".
"""
from __future__ import annotations

import re
from typing import Any, Iterable

VERSION = 2
SIZES = ("1x1", "2x1", "2x2")
WIDGET_TYPES = ("clock", "zone", "weather", "scenes", "rooms")
RETIRED_TYPES = ("device",)      # from version 1; dropped quietly
MAX_WIDGETS = 40

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_TZ = re.compile(r"^[A-Za-z_]+(?:/[A-Za-z0-9_+-]+){0,2}$")


class LayoutError(ValueError):
    """The layout can't be saved; the message says why in plain words."""


def default_layout(devices: Iterable[Any] = ()) -> dict:
    """The Home page before anyone edits it: big clock, weather, clocks for India and
    the US, the rooms (each opens its own page) and scenes. No devices: those are on
    the Rooms pages. `devices` is accepted for older callers and ignored."""
    widgets = [
        {"id": "clock", "type": "clock", "size": "2x2", "hidden": False, "options": {}},
        {"id": "weather", "type": "weather", "size": "2x1", "hidden": False, "options": {}},
        {"id": "zone-in", "type": "zone", "size": "1x1", "hidden": False,
         "options": {"tz": "Asia/Kolkata", "label": "India"}},
        {"id": "zone-us", "type": "zone", "size": "1x1", "hidden": False, "options": {"tz": None, "label": "US"}},
        {"id": "rooms", "type": "rooms", "size": "2x2", "hidden": False, "options": {}},
        {"id": "scenes", "type": "scenes", "size": "2x1", "hidden": False, "options": {}},
    ]
    return {"version": VERSION, "widgets": widgets}


def migrate_layout(layout: Any) -> Any:
    """A saved layout brought up to date: device widgets (version 1) are dropped.
    Anything that isn't a layout is returned as it is (None stays None)."""
    if not isinstance(layout, dict) or not isinstance(layout.get("widgets"), list):
        return layout
    widgets = [w for w in layout["widgets"] if not (isinstance(w, dict) and w.get("type") in RETIRED_TYPES)]
    return {**layout, "version": VERSION, "widgets": widgets}


def _options(kind: str, raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    if kind == "zone":
        tz = raw.get("tz")
        if tz not in (None, "") and not (isinstance(tz, str) and _TZ.match(tz)):
            raise LayoutError(f"'{tz}' isn't a time zone name like America/New_York.")
        label = " ".join(str(raw.get("label") or "").split())[:24]
        return {"tz": tz or None, "label": label}
    return {}


def clean_layout(value: Any) -> dict:
    """Check a layout sent by the UI and return a tidy copy. Raises LayoutError."""
    if not isinstance(value, dict) or not isinstance(value.get("widgets"), list):
        raise LayoutError("The Home layout should have a list of widgets.")
    if len(value["widgets"]) > MAX_WIDGETS:
        raise LayoutError(f"The Home page can hold up to {MAX_WIDGETS} widgets.")
    seen: set[str] = set()
    widgets = []
    for w in value["widgets"]:
        if not isinstance(w, dict):
            raise LayoutError("Each widget should be an object.")
        kind, wid, size = w.get("type"), w.get("id"), w.get("size", "1x1")
        if kind in RETIRED_TYPES:
            continue                  # an old screen still showing device widgets: devices are on the Rooms pages now
        if kind not in WIDGET_TYPES:
            raise LayoutError(f"Unknown widget type '{kind}'. Use one of: {', '.join(WIDGET_TYPES)}.")
        if not (isinstance(wid, str) and _ID.match(wid)) or wid in seen:
            raise LayoutError("Each widget needs its own short id.")
        if size not in SIZES:
            raise LayoutError(f"Widget size should be one of: {', '.join(SIZES)}.")
        seen.add(wid)
        widgets.append({"id": wid, "type": kind, "size": size, "hidden": bool(w.get("hidden", False)),
                        "options": _options(kind, w.get("options"))})
    return {"version": VERSION, "widgets": widgets}
