"""
Photo library for the photo-frame slideshow.

Photos live in data/photos/ on the panel. They get there by uploading from a
phone or laptop browser (Settings → Photo frame), or by copying files into the
folder (USB stick, scp, the Docker volume).

Uploads are made screen-ready when Pillow is installed: rotated upright using the
camera's orientation tag, shrunk to at most MAX_EDGE pixels on the long side, and
saved without metadata (so no GPS location is kept). Without Pillow, JPEG, PNG,
WebP and GIF files are stored as they are.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import time

log = logging.getLogger("homepanel.photos")

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_EDGE = 2560
EXTENSIONS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
              ".webp": "image/webp", ".gif": "image/gif"}
MAGIC = ((b"\xff\xd8\xff", ".jpg"), (b"\x89PNG\r\n\x1a\n", ".png"), (b"GIF87a", ".gif"),
         (b"GIF89a", ".gif"), (b"RIFF", ".webp"))
ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


class PhotoError(ValueError):
    """A problem with a photo, worded for people."""


def _sniff(data: bytes) -> str | None:
    for magic, ext in MAGIC:
        if data.startswith(magic):
            if ext == ".webp" and data[8:12] != b"WEBP":
                continue
            return ext
    return None


class PhotoLibrary:
    def __init__(self, folder: str):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)

    # --- reading ------------------------------------------------------------
    def list(self) -> list[dict]:
        items = []
        for name in os.listdir(self.folder):
            ext = os.path.splitext(name)[1].lower()
            path = os.path.join(self.folder, name)
            if ext in EXTENSIONS and os.path.isfile(path) and not name.startswith("."):
                st = os.stat(path)
                items.append({"id": name, "name": name, "size": st.st_size, "added": st.st_mtime})
        items.sort(key=lambda p: p["added"], reverse=True)
        return items

    def path(self, photo_id: str) -> tuple[str, str]:
        """Absolute path and media type for a photo id. Refuses anything outside the folder."""
        if not ID_RE.match(photo_id or "") or photo_id.startswith("."):
            raise KeyError(photo_id)
        ext = os.path.splitext(photo_id)[1].lower()
        if ext not in EXTENSIONS:
            raise KeyError(photo_id)
        path = os.path.join(self.folder, photo_id)
        if os.path.dirname(os.path.abspath(path)) != os.path.abspath(self.folder) or not os.path.isfile(path):
            raise KeyError(photo_id)
        return path, EXTENSIONS[ext]

    # --- writing ------------------------------------------------------------
    def add(self, data: bytes, filename: str = "") -> dict:
        if not data:
            raise PhotoError("That file is empty.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise PhotoError(f"That photo is too large (over {MAX_UPLOAD_BYTES // 1024 // 1024} MB).")
        ext = _sniff(data)
        if not ext:
            raise PhotoError("That isn't a supported photo. Use JPEG, PNG, WebP or GIF "
                             "(on iPhone, photos picked in the browser are converted to JPEG automatically).")
        data, ext = self._make_screen_ready(data, ext)
        digest = hashlib.sha1(data).hexdigest()[:16]
        for existing in os.listdir(self.folder):
            if existing.startswith(digest):
                return self._info(existing)   # same photo already added
        name = f"{digest}{ext}"
        tmp = os.path.join(self.folder, f".{name}.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, os.path.join(self.folder, name))
        log.info("Added photo %s (%s, %d KB)", name, filename or "upload", len(data) // 1024)
        return self._info(name)

    def delete(self, photo_id: str) -> None:
        path, _ = self.path(photo_id)
        os.remove(path)

    def _info(self, name: str) -> dict:
        st = os.stat(os.path.join(self.folder, name))
        return {"id": name, "name": name, "size": st.st_size, "added": st.st_mtime}

    def _make_screen_ready(self, data: bytes, ext: str) -> tuple[bytes, str]:
        if ext == ".gif":
            return data, ext            # keep animations as they are
        try:
            from PIL import Image, ImageOps
        except ImportError:
            return data, ext
        try:
            img = Image.open(io.BytesIO(data))
            img = ImageOps.exif_transpose(img)
            img.thumbnail((MAX_EDGE, MAX_EDGE))
            out = io.BytesIO()
            if img.mode in ("RGBA", "LA", "P") and ext == ".png":
                img.save(out, "PNG", optimize=True)          # keep transparency
                return out.getvalue(), ".png"
            img.convert("RGB").save(out, "JPEG", quality=88, optimize=True, progressive=True)
            return out.getvalue(), ".jpg"
        except Exception as e:
            raise PhotoError(f"Couldn't read that photo ({e.__class__.__name__}).")

    # --- demo ---------------------------------------------------------------
    def seed_demo(self, count: int = 5) -> int:
        """Painted landscape scenes so the demo slideshow has something to show."""
        try:
            from PIL import Image, ImageDraw, ImageFilter
        except ImportError:
            return 0
        palettes = [  # sky top, sky bottom, sun, hills near, hills far
            ((24, 40, 110), (250, 150, 110), (255, 220, 160), (40, 30, 70), (90, 60, 110)),
            ((10, 30, 70), (60, 140, 190), (240, 250, 255), (20, 60, 70), (40, 100, 110)),
            ((60, 20, 80), (255, 120, 90), (255, 200, 120), (60, 20, 50), (120, 50, 90)),
            ((120, 180, 230), (230, 240, 250), (255, 250, 220), (60, 120, 80), (110, 160, 120)),
            ((5, 10, 30), (40, 50, 110), (230, 230, 250), (10, 15, 35), (30, 35, 70)),
        ]
        made = 0
        for i, (top, bottom, sun, near, far) in enumerate(palettes[:count]):
            w, h = 1600, 1000
            img = Image.new("RGB", (w, h))
            d = ImageDraw.Draw(img)
            for y in range(h):
                t = y / h
                d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True)))
            cx, cy = 400 + i * 220, 360 + (i % 2) * 80
            glow = Image.new("RGB", (w, h), (0, 0, 0))
            ImageDraw.Draw(glow).ellipse([cx - 220, cy - 220, cx + 220, cy + 220], fill=sun)
            img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(90)), 0.35)
            d = ImageDraw.Draw(img)
            d.ellipse([cx - 70, cy - 70, cx + 70, cy + 70], fill=sun)
            for color, base, amp, phase in ((far, 640, 90, i), (near, 760, 120, i + 2)):
                pts = [(x, base - amp * (0.6 * abs(((x / 260 + phase) % 2) - 1)) - 20 * ((x // 97) % 3))
                       for x in range(0, w + 40, 40)]
                d.polygon([(0, h)] + pts + [(w, h)], fill=color)
            out = io.BytesIO()
            img.filter(ImageFilter.SMOOTH).save(out, "JPEG", quality=85)
            self.add(out.getvalue(), f"demo-{i}.jpg")
            made += 1
        return made


def is_night(now: float | None = None, start: int = 22, end: int = 7) -> bool:
    hour = time.localtime(now).tm_hour
    return hour >= start or hour < end
