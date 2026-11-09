"""Read-only Immich 2.x/3.x photo transport. No SDK or server code is copied."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from ..core.photos import PhotoError

NAME = "Immich"
PERMISSIONS = ["album.read", "asset.read", "asset.view"]
JSON_LIMIT = 1024 * 1024
IMAGE_LIMIT = 4 * 1024 * 1024


def server_url(value: str) -> str:
    try:
        if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
            raise ValueError
        parsed = urllib.parse.urlsplit(value.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
        if parsed.query or parsed.fragment or "%" in parsed.path or "%" in parsed.netloc \
                or any(p in (".", "..") for p in parsed.path.split("/")):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
        path = parsed.path.rstrip("/")
        if path.endswith("/api"):
            path = path[:-4]
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    except ValueError:
        raise PhotoError("Enter a direct HTTP(S) server URL without credentials, a query or a fragment.") from None


def asset_id(value) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise PhotoError("The photo server returned an unsupported identifier.") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PhotoSource:
    name = NAME
    permissions = PERMISSIONS

    def __init__(self, url: str, key: str):
        self.url = server_url(url)
        if not isinstance(key, str) or not key or len(key) > 1024 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise PhotoError("Enter a valid read-only API key in Settings.")
        self._key = key
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)

    def request(self, path: str, body=None, *, image=False, public=False, deadline=None):
        deadline = deadline or time.monotonic() + 12
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PhotoError("The photo server took too long. Try again.")
        headers = {"Accept": "image/*" if image else "application/json", "Accept-Encoding": "identity"}
        if not public:
            headers["x-api-key"] = self._key
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = urllib.request.Request(self.url + "/api" + path, data=data, headers=headers)
        limit = IMAGE_LIMIT if image else JSON_LIMIT
        try:
            with self._opener.open(request, timeout=min(5, remaining)) as response:
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    raise PhotoError("The photo server returned an unsupported compressed response.")
                chunks, size = [], 0
                while True:
                    if time.monotonic() > deadline:
                        raise PhotoError("The photo server took too long. Try again.")
                    chunk = response.read1(min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > limit:
                        raise PhotoError("The photo server response is too large for the panel.")
                raw = b"".join(chunks)
                if image:
                    if response.headers.get_content_type() not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                        raise PhotoError("The photo server did not return a supported preview image.")
                    return raw
                return json.loads(raw)
        except PhotoError:
            raise
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            if code in (401, 403):
                raise PhotoError("Photo access was refused. Check the API key and album.read, asset.read and asset.view permissions.") from None
            if 300 <= code < 400:
                raise PhotoError("Photo-server redirects are blocked. Enter its direct server URL.") from None
            if code == 429:
                raise PhotoError("The photo server is rate-limiting requests. Wait and try again.") from None
            if code in (400, 404, 405, 422):
                raise PhotoError("This photo API is unavailable or incompatible. Check the URL and supported server version.") from None
            raise PhotoError("The photo server is unavailable. Try again later.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise PhotoError("Cannot reach the photo server. Check its address and connection.") from None
        except (ValueError, UnicodeError):
            raise PhotoError("The photo server returned an incompatible response.") from None

    def verify(self) -> dict:
        version = self.request("/server/version", public=True)
        if not isinstance(version, dict) or type(version.get("major")) is not int or version["major"] not in (2, 3):
            raise PhotoError("This integration supports Immich 2.x and 3.x photo APIs. Other versions need compatibility verification.")
        self.albums()
        return {key: version.get(key, 0) for key in ("major", "minor", "patch")}

    def albums(self, photo=None, *, deadline=None) -> list[dict]:
        path = "/albums" + ("?assetId=" + asset_id(photo) if photo else "")
        result = self.request(path, deadline=deadline)
        if not isinstance(result, list) or len(result) > 1000 or any(not isinstance(a, dict) for a in result):
            raise PhotoError("The photo server returned an unsupported album list.")
        return [{"id": asset_id(a.get("id")), "name": str(a.get("albumName", "Album"))[:160]}
                for a in result if isinstance(a, dict)]

    @staticmethod
    def eligible(photo: dict) -> bool:
        if not isinstance(photo, dict) or "visibility" not in photo or type(photo.get("isTrashed")) is not bool:
            raise PhotoError("The server does not report the required photo privacy fields. No photos will be displayed.")
        return photo.get("type") == "IMAGE" and photo["visibility"] == "timeline" \
            and photo["isTrashed"] is False and photo.get("isOffline") is False and photo.get("isArchived") is not True

    def candidates(self, albums: list[str], deadline) -> list[dict]:
        if not albums:
            raise PhotoError("Choose an album before displaying photos.")
        result = self.request("/search/random", {
            "size": 12, "type": "IMAGE", "albumIds": albums, "visibility": "timeline",
            "withDeleted": False, "isOffline": False, "withExif": False, "withPeople": False, "withStacked": False,
        }, deadline=deadline)
        if not isinstance(result, list) or len(result) > 12:
            raise PhotoError("The photo server returned an incompatible search response.")
        return [{"id": asset_id(p.get("id"))}
                for p in result if self.eligible(p)]

    def validate(self, photo: str, albums: list[str], deadline) -> str:
        # Independently confirm membership; a search response alone is not authorization.
        membership = {a["id"] for a in self.albums(photo, deadline=deadline)}
        if not membership.intersection(albums):
            raise PhotoError("That photo is no longer in a selected album.")
        result = self.request("/search/metadata", {
            "id": asset_id(photo), "size": 1, "type": "IMAGE", "albumIds": albums,
            "visibility": "timeline", "withDeleted": False, "isOffline": False,
            "withExif": False, "withPeople": False,
        }, deadline=deadline)
        items = result.get("assets", {}).get("items") if isinstance(result, dict) else None
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict) \
                or items[0].get("id") != photo or not self.eligible(items[0]):
            raise PhotoError("That photo is no longer available for display.")
        if not isinstance(items[0].get("updatedAt"), str) or not items[0]["updatedAt"]:
            raise PhotoError("The server does not report preview revisions. Check API compatibility.")
        return items[0]["updatedAt"]

    def preview(self, photo: str, deadline) -> bytes:
        return self.request(f"/assets/{asset_id(photo)}/thumbnail?size=preview", image=True, deadline=deadline)
