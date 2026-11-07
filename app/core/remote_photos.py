"""Private, explicitly shared photo source; credentials never enter public settings."""
from __future__ import annotations

import asyncio
import hashlib
import io
import secrets
import time
import warnings
from collections import OrderedDict

from ..adapters import photo_source, photo_source_info
from .photos import PhotoError
from .profiles import current_viewer

ACCOUNT = "photo_library"


def screen_preview(data: bytes) -> bytes:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        raise PhotoError("Photo previews need Pillow installed on the panel.") from None
    try:
        with warnings.catch_warnings(action="error", category=Image.DecompressionBombWarning), Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 12_000_000:
                raise PhotoError("That preview is too large to decode safely.")
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1280, 1280))
            output = io.BytesIO()
            image.convert("RGB").save(output, "JPEG", quality=85)
            if output.tell() > 2 * 1024 * 1024:
                raise PhotoError("That preview is too large for the panel.")
            return output.getvalue()
    except PhotoError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise PhotoError("That photo preview could not be decoded.") from None


class RemotePhotos:
    def __init__(self, store, notify):
        self.store, self.notify = store, notify
        self._lock = asyncio.Lock()
        self._last: dict[str, str] = {}
        self._attempt: dict[str, float] = {}
        self._cache: OrderedDict[tuple, tuple[bytes, float]] = OrderedDict()

    @property
    def config(self):
        return self.store.accounts.get(ACCOUNT, {})

    def _client(self, config=None):
        c = self.config if config is None else config
        return photo_source(c.get("url", ""), c.get("key", ""))

    def _admin(self):
        viewer = current_viewer.get()
        if viewer is not None and not viewer.is_admin:
            raise KeyError("photo source")
        return viewer

    def permitted(self):
        viewer = current_viewer.get()
        return viewer is not None and viewer.id in self.config.get("profiles", []) \
            and any(p["id"] == viewer.id for p in self.store.profiles)

    def status(self):
        c = self.config
        ready = bool(c.get("key") and c.get("albums"))
        allowed = self.permitted()
        return {"ready": ready and allowed, "configured": bool(c.get("key")),
                "permitted": allowed, "generation": c.get("generation", "") if allowed else "",
                "seconds": c.get("seconds", 45)}

    def management(self):
        self._admin()
        c = self.config
        return {**photo_source_info(), "url": c.get("url", ""), "key_set": bool(c.get("key")),
                "albums": c.get("albums", []), "profiles": c.get("profiles", []),
                "seconds": c.get("seconds", 45), "version": c.get("version")}

    def _save(self, config):
        config["generation"] = secrets.token_hex(12)
        self.store.accounts[ACCOUNT] = config
        self.store.save()
        self._last.clear()
        self._attempt.clear()
        self._cache.clear()
        self.notify()

    async def connect(self, values):
        viewer = self._admin()
        old = self.config
        url = values.get("url")
        key = values.get("key") or (old.get("key") if url == old.get("url") else "")
        client = photo_source(url, key)
        version = await asyncio.to_thread(client.verify)
        available = {a["id"] for a in await asyncio.to_thread(client.albums)}
        if self.config.get("generation") != old.get("generation"):
            raise PhotoError("The connection changed on another screen. Reload settings.")
        same = client.url == old.get("url")
        selected = old.get("albums", []) if same and set(old.get("albums", [])).issubset(available) else []
        self._save({"url": client.url, "key": key, "version": version, "albums": selected,
                    "profiles": old.get("profiles", []) if same else [viewer.id] if viewer else [],
                    "seconds": old.get("seconds", 45)})
        return self.management()

    async def albums(self):
        self._admin()
        return await asyncio.to_thread(self._client().albums)

    async def select(self, values):
        self._admin()
        generation = self.config.get("generation")
        albums, profiles, seconds = values.get("albums"), values.get("profiles"), values.get("seconds", 45)
        if not isinstance(albums, list) or not 1 <= len(albums) <= 8 or any(not isinstance(a, str) for a in albums):
            raise PhotoError("Choose between one and eight albums for the display.")
        available = {a["id"] for a in await self.albums()}
        if self.config.get("generation") != generation:
            raise PhotoError("The connection changed on another screen. Reload settings.")
        if not set(albums).issubset(available):
            raise PhotoError("A selected album is unavailable. Refresh the album list.")
        valid_profiles = {p["id"] for p in self.store.profiles}
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= 128 \
                or any(not isinstance(p, str) or p not in valid_profiles for p in profiles):
            raise PhotoError("Choose the profiles allowed to see these photos.")
        if type(seconds) is not int or not 30 <= seconds <= 300:
            raise PhotoError("Rotate photos every 30 to 300 seconds.")
        self._save({**self.config, "albums": list(dict.fromkeys(albums)),
                    "profiles": list(dict.fromkeys(profiles)), "seconds": seconds})
        return self.management()

    def disconnect(self):
        self._admin()
        self._save({})
        return self.management()

    def _next(self, config, profile):
        deadline = time.monotonic() + 12
        client = self._client(config)
        candidates = client.candidates(config["albums"], deadline)
        if not candidates:
            raise PhotoError("No eligible photos were found in the selected albums.")
        choices = [p for p in candidates if p["id"] != self._last.get(profile)]
        if not choices and profile in self._last:
            more = client.candidates(config["albums"], deadline)
            choices = [p for p in more if p["id"] != self._last[profile]]
        choices = choices or candidates
        photo = secrets.choice(choices)
        # Revalidate membership on every request, including a cached preview.
        updated = client.validate(photo["id"], config["albums"], deadline)
        cache_key = (config["generation"], profile, photo["id"], updated)
        cached = self._cache.get(cache_key)
        image = cached[0] if cached and cached[1] > time.monotonic() else screen_preview(client.preview(photo["id"], deadline))
        return photo["id"], image, cache_key

    async def next(self):
        viewer = current_viewer.get()
        if not self.permitted():
            raise KeyError("photo")
        if not self.config.get("albums"):
            raise PhotoError("Choose an album in Photo library settings.")
        profile = viewer.id
        async with self._lock:
            if profile in self._attempt and time.monotonic() - self._attempt[profile] < 5:
                raise PhotoError("Please wait a few seconds before requesting another photo.")
            self._attempt[profile] = time.monotonic()
            config = dict(self.config)
            photo, image, cache_key = await asyncio.to_thread(self._next, config, profile)
            if self.config.get("generation") != config.get("generation") or not self.permitted() \
                    or not any(p["id"] == profile for p in self.store.profiles):
                self._cache.clear()
                raise PhotoError("The photo source changed. Reload the panel.")
            self._last[profile] = photo
            self._cache[cache_key] = (image, time.monotonic() + 300)
            self._cache.move_to_end(cache_key)
            while len(self._cache) > 8 or sum(len(entry[0]) for entry in self._cache.values()) > 8 * 1024 * 1024:
                self._cache.popitem(last=False)
            token = hashlib.sha256((config["generation"] + photo).encode()).hexdigest()[:24]
            return image, token, config["generation"]
