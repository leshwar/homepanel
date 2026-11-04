"""
HomePanel entry point.

    python -m app.main --demo          # try it with pretend devices
    python -m app.main                 # real devices on your Wi-Fi
    python -m app.main --debug         # verbose logs (logs/homepanel.log)
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import os
import time

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .api.routes import routes as api_routes
from .core.logs import setup_logging
from .core.net import in_container, phone_url
from .core.service import HomeService

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
log = logging.getLogger("homepanel")


def ui_cache_header(path: str) -> str | None:
    """Cache policy for the touch UI's own files.

    "no-cache" means "check with the server before reusing" (cheap: an ETag check
    on the home network). Without it a browser can keep an old or half-loaded
    copy of app.css / app.js, e.g. the kiosk after an update, or a browser that
    opened the page while the server was still starting.
    """
    if path.startswith("/api/"):
        return None                      # API responses set their own headers
    if path == "/" or path.endswith((".html", ".css", ".js", ".svg", ".json")):
        return "no-cache"
    return None


class RequestLog(BaseHTTPMiddleware):
    """Logs every API call with its status and duration (skips the long-lived event stream)."""

    async def dispatch(self, request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        path = request.url.path
        cache = ui_cache_header(path)
        if cache and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = cache
        if path.startswith("/api/") and not path.endswith("/events"):
            ms = (time.monotonic() - start) * 1000
            lvl = logging.WARNING if response.status_code >= 400 else logging.DEBUG
            logging.getLogger("homepanel.http").log(lvl, "%s %s -> %s (%.0f ms)",
                                                     request.method, path, response.status_code, ms)
        return response


async def index(request):
    return FileResponse(os.path.join(WEB_DIR, "index.html"), headers={"Cache-Control": "no-cache"})


def create_app(data_dir: str, demo: bool = False, port: int = 8080) -> Starlette:
    service = HomeService(data_dir, demo=demo)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        app.state.service = service
        app.state.started = time.time()
        app.state.port = port
        await service.start()
        log.info("HomePanel ready: %d devices, adapters: %s%s", len(service.store.devices),
                 ", ".join(sorted(service.adapters)) or "none",
                 f" (unavailable: {', '.join(sorted(service.unavailable))})" if service.unavailable else "")
        url = None if in_container() else phone_url(port)
        if url:
            log.info("To use it on a phone or tablet on the same Wi-Fi, open %s", url)
        yield
        await service.stop()

    return Starlette(
        routes=[*api_routes, Route("/", index), Mount("/", StaticFiles(directory=WEB_DIR), name="web")],
        middleware=[Middleware(RequestLog)],
        lifespan=lifespan,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="HomePanel smart home controller")
    p.add_argument("--host", default=os.environ.get("HOMEPANEL_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("HOMEPANEL_PORT", "8080")))
    p.add_argument("--data", default=os.environ.get("HOMEPANEL_DATA", os.path.join(ROOT, "data")),
                   help="Where settings, devices and tokens are stored")
    p.add_argument("--logs", default=os.environ.get("HOMEPANEL_LOGS", os.path.join(ROOT, "logs")))
    p.add_argument("--demo", action="store_true", help="Use pretend devices (no hardware needed)")
    p.add_argument("--debug", action="store_true", help="Verbose logging")
    args = p.parse_args()

    log_path = setup_logging(args.logs, args.debug)
    log.info("Logging to %s", log_path)
    import uvicorn
    uvicorn.run(create_app(args.data, demo=args.demo, port=args.port), host=args.host, port=args.port,
                log_config=None, access_log=False)


if __name__ == "__main__":
    main()
