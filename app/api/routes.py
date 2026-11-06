"""
API layer — the stable contract the UI (or any other client) talks to.

All routes live under /api/v1. They only call HomeService; they never know
which brand a device is. Errors come back as {"error": "<message for people>"}.
See docs/API.md for the full reference.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from ..core.adapter import AdapterError
from ..core import logs as logmod
from ..core.logs import ring
from ..core.photos import MAX_UPLOAD_BYTES, PhotoError
from ..core.net import in_container, phone_url
from ..core.profiles import AuthError, ProfileError, RateLimited, current_viewer
from ..core.service import HomeService
from .auth import COOKIE, client_address, read_cookie

log = logging.getLogger("homepanel.api")


def _svc(request: Request) -> HomeService:
    return request.app.state.service


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def handle_errors(fn):
    async def wrapper(request: Request):
        try:
            result = await fn(request)
            return result if isinstance(result, Response) \
                else JSONResponse(result)
        except RateLimited as e:
            return JSONResponse({"error": str(e)}, status_code=429,
                                headers={"Retry-After": str(int(e.retry_after) + 1)})
        except AuthError as e:
            return JSONResponse({"error": str(e)}, status_code=401)
        except (AdapterError, PhotoError, ProfileError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except KeyError:
            return JSONResponse({"error": "Not found"}, status_code=404)
        except (ValueError, TypeError) as e:
            return JSONResponse({"error": f"Invalid request: {e}"}, status_code=422)
        except asyncio.TimeoutError:
            return JSONResponse({"error": "That took too long. Try again."}, status_code=504)
        except Exception as e:
            log.exception("Unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse({"error": f"Something went wrong: {e}"}, status_code=500)
    wrapper.__name__ = fn.__name__
    return wrapper


# --- snapshot & live events ------------------------------------------------------

@handle_errors
async def get_state(request):
    return _svc(request).snapshot()


async def events(request: Request):
    """Server-Sent Events: the UI keeps this open and updates tiles as states change.
    Each event is checked against the listener's profile when it's sent, so a device the
    profile can't see never arrives, and the stream ends when the session does, or when
    the server shuts down (the UI then reconnects once it's back)."""
    svc = _svc(request)
    token = read_cookie(request.scope)
    opened_by = current_viewer.get()
    auto_viewer = opened_by if opened_by and opened_by.auto else None   # demo without sign-in

    def viewer_now():
        # Looked up again for every event (publish() runs in other requests' context,
        # so never read current_viewer here): a removed profile or ended session stops at once.
        v = svc.profiles.viewer_for(token) or auto_viewer
        return v if v and not (v.session and v.session.locked) else None

    def allow(ev: dict) -> bool:
        v = viewer_now()
        return v is not None and svc.event_visible(v, ev)

    q = svc.subscribe(allow)

    async def stream():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), 20)
                    if ev is None:              # the server is shutting down (end_streams)
                        break
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                if await request.is_disconnected() or viewer_now() is None:
                    break
        finally:
            svc.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- devices -------------------------------------------------------------------------

@handle_errors
async def device_command(request):
    body = await _body(request)
    return await _svc(request).command(request.path_params["id"], body.get("action", ""), body.get("value"))


@handle_errors
async def add_device(request):
    b = await _body(request)
    return await _svc(request).add_device(b.get("adapter", ""), uid=b.get("uid"), manual=b.get("manual"),
                                          name=b.get("name"), room=b.get("room", ""))


@handle_errors
async def update_device(request):
    return _svc(request).update_device(request.path_params["id"], await _body(request))


@handle_errors
async def remove_device(request):
    await _svc(request).remove_device(request.path_params["id"])
    return {"ok": True}


@handle_errors
async def pair_device(request):
    return await _svc(request).pair(request.path_params["id"])


@handle_errors
async def refresh_device(request):
    svc = _svc(request)
    await svc.refresh(request.path_params["id"])
    return svc.public_device(svc.get(request.path_params["id"]))


@handle_errors
async def all_off(request):
    b = await _body(request)
    return {"turned_off": await _svc(request).all_off(b.get("room"))}


@handle_errors
async def voice(request):
    """A spoken or typed sentence → device commands, run through the normal pipeline."""
    b = await _body(request)
    text = b.get("text")
    if not isinstance(text, str):
        raise AdapterError("Say or type a command, like “turn off the kitchen”.")
    return await _svc(request).voice.handle(text, confirm=b.get("confirm") is True)


# --- adapters / discovery / accounts --------------------------------------------------

@handle_errors
async def discover(request):
    return {"found": await _svc(request).discover(request.path_params["adapter"])}


@handle_errors
async def discover_all(request):
    return await _svc(request).discover_all()


@handle_errors
async def get_account(request):
    return _svc(request).account_public(request.path_params["adapter"])


@handle_errors
async def put_account(request):
    return _svc(request).set_account(request.path_params["adapter"], await _body(request))


@handle_errors
async def account_action(request):
    p = request.path_params
    return await _svc(request).account_action(p["adapter"], p["action"])


# --- rooms, scenes, settings ---------------------------------------------------------

@handle_errors
async def put_rooms(request):
    return {"rooms": _svc(request).set_rooms((await _body(request)).get("rooms", []))}


@handle_errors
async def save_scene(request):
    return _svc(request).save_scene(await _body(request))


@handle_errors
async def delete_scene(request):
    _svc(request).delete_scene(request.path_params["id"])
    return {"ok": True}


@handle_errors
async def run_scene(request):
    return await _svc(request).run_scene(request.path_params["id"])


@handle_errors
async def put_settings(request):
    return _svc(request).update_settings(await _body(request))


# --- energy, automations, presence ---------------------------------------------------

@handle_errors
async def device_map(request):
    content_type, body = await _svc(request).map_image(request.path_params["id"])
    # The picture comes from the device's cloud: never let it run scripts or load anything.
    return Response(body, media_type=content_type, headers={
        "Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@handle_errors
async def device_energy(request):
    days = int(request.query_params.get("days", 7))
    return await _svc(request).energy(request.path_params["id"], days)


@handle_errors
async def list_automations(request):
    return {"automations": _svc(request).automations.list()}


@handle_errors
async def save_automation(request):
    return _svc(request).automations.save(await _body(request))


@handle_errors
async def delete_automation(request):
    _svc(request).automations.delete(request.path_params["id"])
    return {"ok": True}


@handle_errors
async def run_automation(request):
    return await _svc(request).automations.run_now(request.path_params["id"])


@handle_errors
async def get_presence(request):
    return {"people": _svc(request).presence.snapshot()}


@handle_errors
async def get_sun(request):
    from datetime import datetime
    from ..core.sun import sun_event
    s = _svc(request).store.settings
    if s.get("latitude") is None or s.get("longitude") is None:
        return {"sunrise": None, "sunset": None}
    today = datetime.now().astimezone().date()
    out = {}
    for ev in ("sunrise", "sunset"):
        t = sun_event(today, s["latitude"], s["longitude"], ev)
        out[ev] = t.timestamp() if t else None
    return out


@handle_errors
async def lookup_location(request):
    """Find the home's location (Settings → "Use my location"). Doesn't save anything."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    return await _svc(request).geo.lookup(body.get("latitude"), body.get("longitude"))


@handle_errors
async def get_weather(request):
    return await _svc(request).weather.current()


# --- photo frame -------------------------------------------------------------------

@handle_errors
async def list_photos(request):
    photos = await asyncio.to_thread(_svc(request).photos.list)
    return {"photos": [{**p, "url": f"/api/v1/photos/{p['id']}/image"} for p in photos]}


@handle_errors
async def upload_photo(request):
    """Body is the raw image file (Content-Type image/*). One photo per request."""
    if int(request.headers.get("content-length") or 0) > MAX_UPLOAD_BYTES:
        raise PhotoError("That photo is too large.")
    data = await request.body()
    photo = await asyncio.to_thread(_svc(request).photos.add, data, request.query_params.get("name", ""))
    return {**photo, "url": f"/api/v1/photos/{photo['id']}/image"}


@handle_errors
async def delete_photo(request):
    await asyncio.to_thread(_svc(request).photos.delete, request.path_params["id"])
    return {"ok": True}


@handle_errors
async def photo_image(request):
    path, media_type = _svc(request).photos.path(request.path_params["id"])
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})


# --- diagnostics -------------------------------------------------------------------

@handle_errors
async def get_logs(request):
    if request.query_params.get("format") == "text":   # full file download (last ~2 MB)
        path = logmod.LOG_PATH
        text = ""
        if path:
            try:
                with open(path, errors="replace") as f:
                    text = f.read()
            except OSError:
                pass
        return PlainTextResponse(text or "No log file yet.",
                                 headers={"Content-Disposition": "attachment; filename=homepanel-log.txt"})
    level = request.query_params.get("level", "").upper()
    order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    min_level = order.get(level, 0)
    items = [r for r in ring.records if order.get(r["level"], 0) >= min_level]
    return {"logs": items[-300:]}


@handle_errors
async def health(request):
    """Without a session only "it's running" (for the kiosk script and Docker's health check)."""
    svc = _svc(request)
    viewer = current_viewer.get()
    if viewer is None or (viewer.session and viewer.session.locked):
        return {"ok": True, "time": time.time(), "sign_in": True}
    devices = list(svc.store.devices.values())
    return {"ok": True, "time": time.time(), "uptime_s": round(time.time() - request.app.state.started, 1),
            "devices": len(devices), "online": sum(1 for d in devices if d.state.get("online")),
            "adapters": sorted(svc.adapters), "unavailable": svc.unavailable, "unsupported": svc.unsupported, "demo": svc.demo,
            "in_container": in_container(),
            # where to open the panel on a phone (unknown inside Docker: the container's
            # address isn't the computer's, so the UI explains how to find it)
            "phone_url": None if in_container() else phone_url(getattr(request.app.state, "port", 8080))}


# --- sign-in and profiles ------------------------------------------------------------

def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


def _with_cookie(request: Request, body: dict, token: str | None, max_age: int = 0) -> JSONResponse:
    """Set (token) or clear (None) the session cookie: HttpOnly, SameSite=Strict, Secure over HTTPS."""
    res = JSONResponse(body, headers={"Cache-Control": "no-store"})
    if token:
        res.set_cookie(COOKIE, token, max_age=max_age, path="/", httponly=True, samesite="strict",
                       secure=_secure(request))
    else:
        res.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=_secure(request))
    return res


def _session_info(request: Request) -> dict:
    svc = _svc(request)
    viewer = current_viewer.get()
    session = viewer.session if viewer else None
    locked = bool(session and session.locked)
    signed_in = viewer is not None and not locked
    return {
        "signed_in": signed_in,
        "auto": bool(viewer and viewer.auto),
        "setup": svc.profiles.needs_setup and not (viewer and viewer.auto),
        "locked": locked,
        "panel": bool(session and session.panel),
        "me": svc.profiles.public(viewer.profile) if signed_in else None,
        "profiles": svc.profiles.picker(),
        "display": svc.display_settings(with_location=signed_in or bool(session and session.panel)),
        "demo": svc.demo,
    }


@handle_errors
async def auth_session(request):
    return JSONResponse(_session_info(request), headers={"Cache-Control": "no-store"})


async def _start_session(request: Request, profile: dict, panel: bool):
    svc = _svc(request)
    old = svc.profiles.viewer_for(read_cookie(request.scope))
    if old and old.session:                 # a fresh token on every sign-in
        panel = panel or old.session.panel   # the wall panel stays the wall panel
        svc.profiles.sessions.delete(old.session)
    token, session = svc.profiles.sessions.create(profile["id"], panel=panel)
    current_viewer.set(svc.profiles.viewer_for(token))
    return _with_cookie(request, _session_info(request), token, int(session.ttl))


@handle_errors
async def sign_in(request):
    """{profile_id, pin} | {profile_id, password} | {email, password}; optional panel: true (admins)."""
    body = await _body(request)
    p = await asyncio.to_thread(_svc(request).profiles.check_credentials, body, client_address(request.scope))
    return await _start_session(request, p, panel=bool(body.get("panel")) and p.get("role") == "admin")


@handle_errors
async def setup(request):
    """First open after upgrading: protect the Owner profile with a PIN or password."""
    body = await _body(request)
    svc = _svc(request)
    p = await asyncio.to_thread(svc.profiles.setup, body)
    return await _start_session(request, p, panel=bool(body.get("panel")))


@handle_errors
async def sign_out(request):
    """Ends this browser's session. On the wall panel it locks instead (unless forget: true),
    so the panel stays signed in and shows the profile picker."""
    svc = _svc(request)
    body = await _body(request)
    viewer = svc.profiles.viewer_for(read_cookie(request.scope))
    if viewer and viewer.session and viewer.session.panel and not body.get("forget"):
        svc.profiles.sessions.update(viewer.session, locked=True)
        current_viewer.set(viewer)
        return JSONResponse(_session_info(request), headers={"Cache-Control": "no-store"})
    if viewer and viewer.session:
        svc.profiles.sessions.delete(viewer.session)
    current_viewer.set(None)
    return _with_cookie(request, _session_info(request), None)


@handle_errors
async def lock(request):
    """The wall panel was idle: back to the profile picker (the session is kept)."""
    viewer = current_viewer.get()
    if viewer and viewer.session:
        _svc(request).profiles.sessions.update(viewer.session, locked=True)
    return JSONResponse(_session_info(request), headers={"Cache-Control": "no-store"})


@handle_errors
async def set_panel(request):
    """Admin: make this screen the wall panel (stays signed in, locks when idle), or not."""
    viewer = current_viewer.get()
    if not viewer or not viewer.session:
        raise AdapterError("Sign in with a PIN or password first.")
    body = await _body(request)
    _svc(request).profiles.sessions.update(viewer.session, panel=bool(body.get("panel")))
    return _with_cookie(request, _session_info(request), read_cookie(request.scope), int(viewer.session.ttl))


@handle_errors
async def list_profiles(request):
    return {"profiles": _svc(request).list_profiles()}


@handle_errors
async def add_profile(request):
    return await _svc(request).add_profile(await _body(request))


@handle_errors
async def update_profile(request):
    return await _svc(request).update_profile(request.path_params["id"], await _body(request))


@handle_errors
async def delete_profile(request):
    _svc(request).delete_profile(request.path_params["id"])
    return {"ok": True}


@handle_errors
async def update_me(request):
    return await _svc(request).update_me(await _body(request))


@handle_errors
async def put_my_layout(request):
    return _svc(request).save_my_layout((await _body(request)).get("home_layout"))


routes = [
    Route("/api/v1/auth/session", auth_session),
    Route("/api/v1/auth/sign-in", sign_in, methods=["POST"]),
    Route("/api/v1/auth/setup", setup, methods=["POST"]),
    Route("/api/v1/auth/sign-out", sign_out, methods=["POST"]),
    Route("/api/v1/auth/lock", lock, methods=["POST"]),
    Route("/api/v1/auth/panel", set_panel, methods=["POST"]),
    Route("/api/v1/profiles", list_profiles, methods=["GET"]),
    Route("/api/v1/profiles", add_profile, methods=["POST"]),
    Route("/api/v1/profiles/me", update_me, methods=["PATCH"]),
    Route("/api/v1/profiles/me/layout", put_my_layout, methods=["PUT"]),
    Route("/api/v1/profiles/{id}", update_profile, methods=["PATCH"]),
    Route("/api/v1/profiles/{id}", delete_profile, methods=["DELETE"]),
    Route("/api/v1/state", get_state),
    Route("/api/v1/events", events),
    Route("/api/v1/health", health),
    Route("/api/v1/logs", get_logs),
    Route("/api/v1/devices", add_device, methods=["POST"]),
    Route("/api/v1/devices/{id}", update_device, methods=["PATCH"]),
    Route("/api/v1/devices/{id}", remove_device, methods=["DELETE"]),
    Route("/api/v1/devices/{id}/command", device_command, methods=["POST"]),
    Route("/api/v1/devices/{id}/pair", pair_device, methods=["POST"]),
    Route("/api/v1/devices/{id}/refresh", refresh_device, methods=["POST"]),
    Route("/api/v1/all-off", all_off, methods=["POST"]),
    Route("/api/v1/voice", voice, methods=["POST"]),
    Route("/api/v1/discover", discover_all, methods=["POST"]),
    Route("/api/v1/adapters/{adapter}/discover", discover, methods=["POST"]),
    Route("/api/v1/adapters/{adapter}/account", get_account, methods=["GET"]),
    Route("/api/v1/adapters/{adapter}/account", put_account, methods=["PUT"]),
    Route("/api/v1/adapters/{adapter}/actions/{action}", account_action, methods=["POST"]),
    Route("/api/v1/rooms", put_rooms, methods=["PUT"]),
    Route("/api/v1/scenes", save_scene, methods=["POST"]),
    Route("/api/v1/scenes/{id}", delete_scene, methods=["DELETE"]),
    Route("/api/v1/scenes/{id}/run", run_scene, methods=["POST"]),
    Route("/api/v1/settings", put_settings, methods=["PUT"]),
    Route("/api/v1/devices/{id}/energy", device_energy),
    Route("/api/v1/devices/{id}/map", device_map),
    Route("/api/v1/automations", list_automations, methods=["GET"]),
    Route("/api/v1/automations", save_automation, methods=["POST"]),
    Route("/api/v1/automations/{id}", delete_automation, methods=["DELETE"]),
    Route("/api/v1/automations/{id}/run", run_automation, methods=["POST"]),
    Route("/api/v1/presence", get_presence),
    Route("/api/v1/sun", get_sun),
    Route("/api/v1/weather", get_weather),
    Route("/api/v1/location/lookup", lookup_location, methods=["POST"]),
    Route("/api/v1/photos", list_photos, methods=["GET"]),
    Route("/api/v1/photos", upload_photo, methods=["POST"]),
    Route("/api/v1/photos/{id}", delete_photo, methods=["DELETE"]),
    Route("/api/v1/photos/{id}/image", photo_image, methods=["GET"]),
]
