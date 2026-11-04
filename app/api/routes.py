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
from ..core.service import HomeService

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
        except (AdapterError, PhotoError) as e:
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
    """Server-Sent Events: the UI keeps this open and updates tiles as states change."""
    svc = _svc(request)
    q = svc.subscribe()

    async def stream():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), 20)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                if await request.is_disconnected():
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
    svc = _svc(request)
    devices = list(svc.store.devices.values())
    return {"ok": True, "time": time.time(), "uptime_s": round(time.time() - request.app.state.started, 1),
            "devices": len(devices), "online": sum(1 for d in devices if d.state.get("online")),
            "adapters": sorted(svc.adapters), "unavailable": svc.unavailable, "unsupported": svc.unsupported, "demo": svc.demo,
            "in_container": in_container(),
            # where to open the panel on a phone (unknown inside Docker: the container's
            # address isn't the computer's, so the UI explains how to find it)
            "phone_url": None if in_container() else phone_url(getattr(request.app.state, "port", 8080))}


routes = [
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
