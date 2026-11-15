"""One responsive grid for Home widgets and room cards.

Version 4 consolidates the selected legacy presentation into 2/4/6-column
positions with fine rows (40 CSS pixels before typography scaling). Migration
is one-way; the service backs up the old store before persisting it.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable

VERSION = 4
SIZES = tuple(f"{w}x{h}" for w in range(1, 7) for h in range(3, 25))
COLUMNS = ("2", "4", "6")
MAX_ROWS = 800
WIDGET_TYPES = ("clock", "notifications", "zone", "weather", "scenes", "rooms", "photos", "favourites")
MAX_FAVOURITES = 8
RETIRED_TYPES = ("device",)      # from version 1; dropped quietly
MAX_WIDGETS = 42

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_TZ = re.compile(r"^[A-Za-z_]+(?:/[A-Za-z0-9_+-]+){0,2}$")


class LayoutError(ValueError):
    """The layout can't be saved; the message says why in plain words."""


def default_layout(devices: Iterable[Any] = ()) -> dict:
    """Compact starting positions, fully editable like every other widget."""
    widgets = [
        {"id": "clock", "type": "clock", "size": "2x4", "hidden": False, "options": {}},
        {"id": "notifications", "type": "notifications", "size": "2x4", "hidden": False, "options": {}},
        {"id": "weather", "type": "weather", "size": "2x3", "hidden": False, "options": {}},
        {"id": "zone-in", "type": "zone", "size": "1x3", "hidden": False,
         "options": {"tz": "Asia/Kolkata", "label": "India"}},
        {"id": "zone-us", "type": "zone", "size": "1x3", "hidden": False, "options": {"tz": None, "label": "US"}},
        {"id": "rooms", "type": "rooms", "size": "2x6", "hidden": False, "options": {}},
        {"id": "scenes", "type": "scenes", "size": "2x3", "hidden": False, "options": {}},
    ]
    for cols in (2, 4, 6):
        width = cols // 2 if cols > 2 else 2
        for index, widget in enumerate(widgets[:2]):
            widget.setdefault("positions", {})[str(cols)] = {
                "x": index * width if cols > 2 else 0, "y": 0 if cols > 2 else index * 4, "size": f"{width}x4"}
        placed = _arrange([{**w, "positions": {str(cols): w["positions"][str(cols)]} if str(cols) in w.get("positions", {}) else {}}
                           for w in widgets], cols)
        for widget in widgets:
            widget.setdefault("positions", {})[str(cols)] = placed[widget["id"]]
    return {"version": VERSION, "widgets": widgets}


def _dimensions(size: str) -> tuple[int, int]:
    return tuple(map(int, size.split("x")))


def legacy_default_layout() -> dict:
    """The ordered built-in layout a pre-v4 profile with no saved Home used."""
    widgets = []
    for w in default_layout()["widgets"]:
        if w["type"] == "notifications":
            continue
        widgets.append({**w, "size": "1x1" if w["type"] == "zone" else "2x2" if w["type"] in ("clock", "rooms") else "2x1"})
        widgets[-1].pop("positions", None)
    return {"version": 3, "widgets": widgets}


def _fits(p: dict, occupied: list[dict], cols: int) -> bool:
    w, h = _dimensions(p["size"])
    if p["x"] < 0 or p["y"] < 0 or p["x"] + w > cols or p["y"] + h > MAX_ROWS:
        return False
    for q in occupied:
        qw, qh = _dimensions(q["size"])
        if p["x"] < q["x"] + qw and q["x"] < p["x"] + w and p["y"] < q["y"] + qh and q["y"] < p["y"] + h:
            return False
    return True


def _arrange(widgets: list[dict], cols: int) -> dict[str, dict]:
    """Same stable placement as grid.js; explicit gaps take priority."""
    placed, waiting = {}, []
    for w in widgets:
        if w.get("hidden"):
            continue
        p = w.get("positions", {}).get(str(cols))
        if p and _fits(p, list(placed.values()), cols):
            placed[w["id"]] = dict(p)
        else:
            waiting.append(w)
    for w in waiting:
        variants = sorted(w.get("positions", {}), key=lambda key: abs(int(key) - cols))
        source = w.get("positions", {}).get(variants[0]) if variants else None
        size = source["size"] if source else w["size"]
        width, height = _dimensions(size)
        size = f"{min(width, cols)}x{height}"
        preferred = {**source, "x": min(source["x"], cols - min(width, cols)), "size": size} if source else None
        if preferred and _fits(preferred, list(placed.values()), cols):
            placed[w["id"]] = preferred
            continue
        # Migration can increase a narrow tile's minimum width. Keep its row
        # or move down; never erase a deliberate gap by repacking above it.
        start = source["y"] if source else 0
        slot = next(({"x": x, "y": y, "size": size}
                     for y in range(start, MAX_ROWS - height + 1) for x in range(cols - min(width, cols) + 1)
                     if _fits({"x": x, "y": y, "size": size}, list(placed.values()), cols)), None)
        if slot is None:
            raise LayoutError("This grid is full. Remove a tile or make it smaller.")
        placed[w["id"]] = slot
    return placed


def _legacy_size(size: str, kind: str | None, cols: int) -> str:
    if size not in ("1x1", "2x1", "2x2"):
        raise LayoutError("A saved tile has an invalid legacy size.")
    width, height = _dimensions(size)
    return f"{min(cols, max(width, 1 if kind == 'zone' else 2))}x{height * 3}"


def _legacy_widgets(layout: Any, room: bool = False) -> list[dict]:
    if not isinstance(layout, dict) or not isinstance(layout.get("widgets"), list):
        raise LayoutError("A saved layout does not contain a widget list.")
    widgets = deepcopy(layout["widgets"])
    seen = set()
    for w in widgets:
        if not isinstance(w, dict) or not isinstance(w.get("id"), str) or not _ID.fullmatch(w["id"]) or w["id"] in seen:
            raise LayoutError("A saved layout has invalid or duplicate tile IDs.")
        seen.add(w["id"])
        w.setdefault("size", "1x1")
        if not room and w.get("type") not in (*WIDGET_TYPES, *RETIRED_TYPES):
            raise LayoutError("A saved layout contains an unknown widget.")
        for key in ("positions", "overview_positions"):
            if not isinstance(w.get(key, {}), dict):
                raise LayoutError("A saved layout has invalid positions.")
            for cols, p in w.get(key, {}).items():
                if cols not in COLUMNS or not isinstance(p, dict) or p.get("size") not in ("1x1", "2x1", "2x2"):
                    raise LayoutError("A saved layout has invalid positions.")
                width, height = _dimensions(p["size"])
                if type(p.get("x")) is not int or type(p.get("y")) is not int or not (
                        0 <= p["x"] <= int(cols) - width and 0 <= p["y"] <= 200 - height):
                    raise LayoutError("A saved layout has positions outside its grid.")
    return [w for w in widgets if w.get("type") not in RETIRED_TYPES]


def migrate_layout(layout: Any, presentation: str = "overview") -> Any:
    """Consolidate the currently selected legacy Home view exactly once."""
    if layout is None:
        return None
    if isinstance(layout, dict) and layout.get("version") == VERSION:
        return layout
    widgets = _legacy_widgets(layout)
    ids = {w["id"] for w in widgets}
    for kind in ("clock", "notifications"):
        matches = [w for w in widgets if w["type"] == kind]
        if len(matches) > 1:
            raise LayoutError(f"Keep only one primary {kind} widget before upgrading this layout.")
        if not matches:
            wid = kind
            while wid in ids:
                wid += "-new"
            widgets.append({"id": wid, "type": kind, "size": "2x1",
                            "hidden": kind == "clock" and presentation == "free", "options": {}})
            ids.add(wid)
    legacy = deepcopy(widgets)
    for w in widgets:
        w["size"] = _legacy_size(w.get("size", "1x1"), w["type"], 6)
        w["positions"] = {}
        w.pop("overview_positions", None)
    for cols in (2, 4, 6):
        visible = [w for w in legacy if presentation == "free" or w["type"] not in ("clock", "notifications")]
        projected = [{**w, "positions": w.get("overview_positions", w.get("positions", {}))}
                     for w in visible] if presentation != "free" else visible
        old = _arrange(projected, cols)
        for w in widgets:
            original = next(v for v in legacy if v["id"] == w["id"])
            p = old.get(w["id"]) or original.get("positions", {}).get(str(cols))
            if presentation != "free" and w["type"] in ("clock", "notifications"):
                width = cols // 2 if cols > 2 else 2
                index = int(w["type"] == "notifications")
                p = {"x": index * width if cols > 2 else 0, "y": 0 if cols > 2 else index * 4, "size": f"{width}x4"}
            elif p:
                p = {"x": p["x"], "y": p["y"] * 3 + (0 if presentation == "free" else 8 if cols == 2 else 4),
                     "size": _legacy_size(p["size"], w["type"], cols)}
            if p:
                w["positions"][str(cols)] = p
        arranged = _arrange(widgets, cols)
        for w in widgets:
            if w["id"] in arranged:
                w["positions"][str(cols)] = arranged[w["id"]]
    return clean_layout({"version": VERSION, "widgets": widgets})


def migrate_room_layout(layout: Any, devices: Iterable[Any], presentation: str = "compact") -> dict:
    if isinstance(layout, dict) and layout.get("version") == VERSION:
        return layout
    widgets = _legacy_widgets(layout, room=True) if layout else []
    order = {"tv": 0, "speaker": 1, "light": 2, "switch": 3, "fan": 4, "purifier": 5, "plug": 6, "vacuum": 7}
    for d in sorted(devices, key=lambda d: (order.get(d.kind, 8), d.name.lower())):
        if not any(w["id"] == d.id for w in widgets):
            widgets.append({"id": d.id, "size": "2x1"})
    legacy = deepcopy(widgets)
    for w in widgets:
        w["size"] = "2x3" if presentation != "free" else _legacy_size(w.get("size", "1x1"), None, 6)
        w["positions"] = {}
    for cols in (2, 4, 6):
        if presentation != "free":
            width = cols // 2 if cols > 2 else 2
            for index, w in enumerate(widgets):
                w["positions"][str(cols)] = {"x": index % (cols // width) * width,
                                             "y": index // (cols // width) * 3, "size": f"{width}x3"}
        else:
            for w in widgets:
                p = _arrange(legacy, cols)[w["id"]]
                w["positions"][str(cols)] = {"x": p["x"], "y": p["y"] * 3,
                                             "size": _legacy_size(p["size"], None, cols)}
            for wid, p in _arrange(widgets, cols).items():
                next(w for w in widgets if w["id"] == wid)["positions"][str(cols)] = p
    return clean_room_layout({"version": VERSION, "widgets": widgets})


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
            raise LayoutError("Tile sizes use 1–6 columns and 3–24 rows.")
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
    if value.get("version", VERSION) != VERSION or any(isinstance(w, dict) and "overview_positions" in w for w in value["widgets"]):
        raise LayoutError("The layout format changed. Reload this screen before saving.")
    if len(value["widgets"]) > MAX_WIDGETS:
        raise LayoutError(f"The Home page can hold up to {MAX_WIDGETS} widgets.")
    seen: set[str] = set()
    widgets = []
    for w in value["widgets"]:
        if not isinstance(w, dict):
            raise LayoutError("Each widget should be an object.")
        kind, wid, size = w.get("type"), w.get("id"), w.get("size", "2x3")
        if kind in RETIRED_TYPES:
            continue                  # an old screen still showing device widgets: devices are on the Rooms pages now
        if kind not in WIDGET_TYPES:
            raise LayoutError(f"Unknown widget type '{kind}'. Use one of: {', '.join(WIDGET_TYPES)}.")
        if not (isinstance(wid, str) and _ID.match(wid)) or wid in seen:
            raise LayoutError("Each widget needs its own short id.")
        if size not in SIZES:
            raise LayoutError("Widget size should use 1–6 columns and 3–24 rows.")
        if _dimensions(size)[0] < (1 if kind == "zone" else 2):
            raise LayoutError("Keep this widget at least two columns and three rows (one column for a timezone clock).")
        seen.add(wid)
        widgets.append({"id": wid, "type": kind, "size": size, "hidden": bool(w.get("hidden", False)),
                        "options": _options(kind, w.get("options"))})
        if "positions" in w:
            widgets[-1]["positions"] = _positions(w["positions"])
        if any(_dimensions(p["size"])[0] < (1 if kind == "zone" else 2) for p in widgets[-1].get("positions", {}).values()):
            raise LayoutError("This widget is narrower than its minimum size.")
    if any(sum(w["type"] == kind for w in widgets) > 1 for kind in ("clock", "notifications")):
        raise LayoutError("Use one primary clock and one Notifications widget.")
    _check_overlaps(widgets)
    return {"version": VERSION, "widgets": widgets}


def clean_room_layout(value: Any) -> dict:
    """Room device tiles use the same sizes and responsive positions as Home widgets."""
    if not isinstance(value, dict) or not isinstance(value.get("widgets"), list):
        raise LayoutError("The room layout should have a list of tiles.")
    if value.get("version", VERSION) != VERSION:
        raise LayoutError("The layout format changed. Reload this screen before saving.")
    if len(value["widgets"]) > 100:
        raise LayoutError("A room can hold up to 100 tiles.")
    seen = set()
    widgets = []
    for tile in value["widgets"]:
        if not isinstance(tile, dict):
            raise LayoutError("Each tile should be an object.")
        wid, size = tile.get("id"), tile.get("size", "2x3")
        if not isinstance(wid, str) or not _ID.fullmatch(wid) or wid in seen:
            raise LayoutError("Each tile needs its own device id.")
        if size not in SIZES or _dimensions(size)[0] < 2:
            raise LayoutError("Room cards need at least two columns and three rows.")
        seen.add(wid)
        widgets.append({"id": wid, "size": size, "positions": _positions(tile.get("positions", {}))})
        if any(_dimensions(p["size"])[0] < 2 for p in widgets[-1]["positions"].values()):
            raise LayoutError("Room cards need at least two columns.")
    _check_overlaps(widgets)
    return {"version": VERSION, "widgets": widgets}
