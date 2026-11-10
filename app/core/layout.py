"""Per-profile Home and room layouts: widgets, responsive positions, sizes and options.

Version 3 adds optional `positions`: {"4": {"x": 2, "y": 3, "size": "2x2"}}.
Each 2/4/6-column grid keeps its own geometry, so narrower screens do not destroy
the arrangement saved on a wider one. Older layouts keep their order and sizes.

Devices live on the Rooms pages. Home can hold "favourites" widgets: a short list of
chosen devices (`options.devices`, up to 8 ids; empty = the UI picks the first ones).
Layouts saved before version 2 could hold one "device" widget per device;
`migrate_layout` drops them, and a "device" widget sent by an old screen is dropped
too, so nobody is left with an empty slot.

Sizes are columns x rows of the Home grid. The UI decides how each widget looks
at each size. `options.tz = None` on a clock means "this screen's own time zone".
"""
from __future__ import annotations

import re
from typing import Any, Iterable

VERSION = 3
SIZES = ("1x1", "2x1", "2x2")
COLUMNS = ("2", "4", "6")
MAX_ROWS = 200
WIDGET_TYPES = ("clock", "zone", "weather", "scenes", "rooms", "photos", "favourites")
MAX_FAVOURITES = 8
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
    if kind == "favourites":
        ids = raw.get("devices", [])
        if not isinstance(ids, list) or not all(isinstance(i, str) and _ID.fullmatch(i) for i in ids):
            raise LayoutError("Favourites should be a list of device ids.")
        ids = list(dict.fromkeys(ids))
        if len(ids) > MAX_FAVOURITES:
            raise LayoutError(f"Favourites can hold up to {MAX_FAVOURITES} devices.")
        return {"devices": ids}
    return {}


def _positions(raw: Any) -> dict:
    if not isinstance(raw, dict) or any(k not in COLUMNS for k in raw):
        raise LayoutError("Tile positions should use the 2, 4 or 6 column grid.")
    out = {}
    for cols, p in raw.items():
        if not isinstance(p, dict):
            raise LayoutError("Each tile position needs a column, row and size.")
        x, y, size = p.get("x"), p.get("y"), p.get("size")
        if size not in SIZES:
            raise LayoutError(f"Tile size should be one of: {', '.join(SIZES)}.")
        w, h = map(int, size.split("x"))
        if type(x) is not int or type(y) is not int or not (0 <= x <= int(cols) - w and 0 <= y <= MAX_ROWS - h):
            raise LayoutError("Keep tiles inside the grid.")
        out[cols] = {"x": x, "y": y, "size": size}
    return out


def _check_overlaps(widgets: list[dict]) -> None:
    for cols in COLUMNS:
        occupied = set()
        for tile in widgets:
            p = tile.get("positions", {}).get(cols)
            if tile.get("hidden") or not p:
                continue
            w, h = map(int, p["size"].split("x"))
            cells = {(x, y) for x in range(p["x"], p["x"] + w) for y in range(p["y"], p["y"] + h)}
            if occupied & cells:
                raise LayoutError("Tiles overlap. Move or shrink a tile before saving.")
            occupied.update(cells)


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
        if "positions" in w:
            widgets[-1]["positions"] = _positions(w["positions"])
    _check_overlaps(widgets)
    return {"version": VERSION, "widgets": widgets}


def clean_room_layout(value: Any) -> dict:
    """Room device tiles use the same sizes and responsive positions as Home widgets."""
    if not isinstance(value, dict) or not isinstance(value.get("widgets"), list):
        raise LayoutError("The room layout should have a list of tiles.")
    if len(value["widgets"]) > 100:
        raise LayoutError("A room can hold up to 100 tiles.")
    seen = set()
    widgets = []
    for tile in value["widgets"]:
        if not isinstance(tile, dict):
            raise LayoutError("Each tile should be an object.")
        wid, size = tile.get("id"), tile.get("size", "1x1")
        if not isinstance(wid, str) or not _ID.fullmatch(wid) or wid in seen:
            raise LayoutError("Each tile needs its own device id.")
        if size not in SIZES:
            raise LayoutError(f"Tile size should be one of: {', '.join(SIZES)}.")
        seen.add(wid)
        widgets.append({"id": wid, "size": size, "positions": _positions(tile.get("positions", {}))})
    _check_overlaps(widgets)
    return {"version": VERSION, "widgets": widgets}
