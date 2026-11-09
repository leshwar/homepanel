"""Sign-in for the API: who is asking, and may they?

An ASGI middleware in front of every /api/ route:

    cookie hp_session ─► session (app/core/profiles.py) ─► Viewer ─► current_viewer
                                                          │
          no session  → 401 {"error", "signin": true}     │
          member      → 403 on admin-only routes          │
          hidden device in the path → 404                 ▼
                                                    the route runs

Only the sign-in routes (/api/v1/auth/...) and a minimal /api/v1/health work
without a session. Members get an allow-list of routes; anything new is admin-only
until it is added here.

Internal automated fixtures can let requests without a session act as the first
admin. Signing in to another fixture profile still exercises per-profile devices.
The native user-facing service never enables that automatic fixture selection.
"""
from __future__ import annotations

import json
import re

from ..core.profiles import Viewer, current_viewer

COOKIE = "hp_session"

PUBLIC = {"/api/v1/auth/session", "/api/v1/auth/sign-in", "/api/v1/auth/sign-out",
          "/api/v1/health"}

# Everything a member may do. Device routes are also checked against their device list.
MEMBER_OK = [
    ("GET", re.compile(r"^/api/v1/photo-library/next$")),
    ("GET", re.compile(r"^/api/v1/(state|events|weather|sun|photos|photos/[^/]+/image|wallpapers|wallpapers/[^/]+/image)$")),
    ("GET", re.compile(r"^/api/v1/devices/[^/]+/(energy|map|picture)$")),
    ("POST", re.compile(r"^/api/v1/devices/[^/]+/(command|refresh)$")),
    ("POST", re.compile(r"^/api/v1/(all-off|scenes/[^/]+/run)$")),
    ("PATCH", re.compile(r"^/api/v1/profiles/me$")),
    ("PUT", re.compile(r"^/api/v1/profiles/me/(layout|rooms/layout)$")),
]
DEVICE_PATH = re.compile(r"^/api/v1/devices/([^/]+)/")


def _match(rules, method: str, path: str) -> bool:
    return any(m == method and rx.match(path) for m, rx in rules)


def read_cookie(scope) -> str | None:
    for k, v in scope.get("headers", []):
        if k == b"cookie":
            for part in v.decode("latin-1").split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE:
                    return value or None
    return None


def client_address(scope) -> str:
    c = scope.get("client")
    return c[0] if c else "unknown"


def resolve(service, token: str | None, *, auto: bool) -> Viewer | None:
    """The viewer for a cookie. In auto mode (demo without sign-in), no cookie = the owner."""
    viewer = service.profiles.viewer_for(token)
    if viewer is None and auto:
        owner = service.profiles.owner()
        if owner:
            viewer = Viewer(profile=owner, auto=True)
    return viewer


async def _send_json(send, status: int, body: dict) -> None:
    data = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode()),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": data})


class AuthMiddleware:
    def __init__(self, app, sign_in: bool = True):
        self.app = app
        self.sign_in = sign_in          # False only in demo mode without --sign-in

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        service = scope["app"].state.service
        path, method = scope["path"].rstrip("/") or "/", scope["method"]
        if method == "HEAD":
            method = "GET"
        viewer = resolve(service, read_cookie(scope), auto=not self.sign_in)
        scope.setdefault("state", {})["viewer"] = viewer

        if path not in PUBLIC:
            if viewer is None:
                return await _send_json(send, 401, {"error": "Choose your profile to use the panel.", "signin": True})
            if not viewer.is_admin and not _match(MEMBER_OK, method, path):
                return await _send_json(send, 403, {"error": "Only an admin can do that. Ask the panel's owner."})
            m = DEVICE_PATH.match(path)
            if m and not viewer.sees(m.group(1)):
                return await _send_json(send, 404, {"error": "Not found"})

        token = current_viewer.set(viewer)
        try:
            await self.app(scope, receive, send)
        finally:
            current_viewer.reset(token)
