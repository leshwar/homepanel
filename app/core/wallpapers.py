"""Read-only bundled art alongside the existing user-owned wallpaper library."""
from pathlib import Path

from .photos import PhotoError, PhotoLibrary

ART = (
    ("alpine-dusk", "Alpine dusk"),
    ("cedar-mist", "Cedar mist"),
    ("quiet-coast", "Quiet coast"),
    ("desert-glow", "Desert glow"),
    ("starlit-ridge", "Starlit ridge"),
)
ASSETS = Path(__file__).resolve().parents[2] / "web/wallpapers"
BUILTINS = {f"builtin-{slug}.webp": name for slug, name in ART}


class WallpaperLibrary(PhotoLibrary):
    def list(self) -> list[dict]:
        return [
            {"id": wid, "name": name, "width": 1600, "height": 1200, "builtin": True, "crop_safe": True,
             "thumbnail_url": f"/wallpapers/{wid.removesuffix('.webp')}-thumb.webp",
             "size": (ASSETS / wid).stat().st_size, "added": 0}
            for wid, name in BUILTINS.items()
        ] + super().list()

    def path(self, photo_id: str) -> tuple[str, str]:
        if photo_id in BUILTINS:
            path = ASSETS / photo_id
            if not path.is_file():
                raise KeyError(photo_id)
            return str(path), "image/webp"
        return super().path(photo_id)

    def delete(self, photo_id: str) -> None:
        if photo_id in BUILTINS:
            raise PhotoError("Built-in artwork stays on the panel. Choose another background instead.")
        super().delete(photo_id)
