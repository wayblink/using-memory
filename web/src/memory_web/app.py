"""FastAPI app for browsing using-memory content."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .adapter import MemoryAdapter, NamespaceRegistry
from .i18n import COOKIE_NAME, SUPPORTED, lang_context, resolve_lang
from .maintenance import MaintenanceScheduler, read_interval_from_env
from .routes import admin, api_v1, dashboard, docs, downloads, logs, memory, preferences, search


_PKG_DIR = Path(__file__).resolve().parent


NAMESPACE_COOKIE = "memory_web_ns"

# Section roots that are guaranteed to render without entity lookup, so they
# stay valid after switching namespaces. Anything deeper (``/docs/<slug>``)
# is collapsed to its section root because the slug usually does not exist in
# the sibling namespace.
_NAMESPACE_SAFE_ROOTS = frozenset({
    "/",
    "/docs",
    "/logs",
    "/memory",
    "/preferences",
    "/search",
})


def _safe_namespace_target(referer: str) -> str:
    """Return a namespace-agnostic redirect target derived from ``referer``.

    Section roots like ``/docs`` or ``/logs`` round-trip; deeper paths are
    collapsed to their section root if recognized, otherwise to ``/``.
    Querystrings on safe roots are preserved (search filters, log date
    ranges) since they carry no slug-shaped entity reference.
    """
    if not referer:
        return "/"
    parsed = urlparse(referer)
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    if path in _NAMESPACE_SAFE_ROOTS:
        return f"{path}{query}"
    head = "/" + path.lstrip("/").split("/", 1)[0]
    if head in _NAMESPACE_SAFE_ROOTS:
        return head
    return "/"


def _read_skill_version() -> str:
    """Read the using-memory skill version from <repo>/version.txt.

    The web package lives at <repo>/web/src/memory_web/, so the repo root is
    `_PKG_DIR.parents[2]`. Falls back to ``unknown`` if the file is missing
    or unreadable (e.g. memory-web installed standalone via pip).
    """
    candidates = [
        _PKG_DIR.parents[2] / "version.txt",
        Path("~/.skills/using-memory/version.txt").expanduser(),
        Path("~/.claude/skills/using-memory/version.txt").expanduser(),
        Path("~/.codex/skills/using-memory/version.txt").expanduser(),
    ]
    for path in candidates:
        try:
            if path.exists():
                v = path.read_text(encoding="utf-8").strip()
                if v:
                    return v
        except OSError:
            continue
    return "unknown"


SKILL_VERSION = _read_skill_version()


def _remote_api_token(adapter: MemoryAdapter) -> str | None:
    mt = adapter._mt
    config = mt.load_config(
        Path(adapter.config_path) if adapter.config_path else None,
        os.environ.get("USING_MEMORY_CONFIG"),
    )
    remote = mt.remote_api_from_config(config)
    return remote.get("token") if remote else None


def _is_loopback_request(request: Request) -> bool:
    candidates = []
    if request.client and request.client.host:
        candidates.append(request.client.host)
    host = request.headers.get("host", "")
    if host:
        candidates.append(host.rsplit(":", 1)[0].strip("[]"))
    return any(host in {"127.0.0.1", "localhost", "::1"} for host in candidates)


def _namespace_context(request: Request) -> dict:
    """Surface the active namespace + sibling list to every template.

    Reads ``request.state.adapter`` and ``request.state.namespaces`` set by
    the ``attach_namespace`` middleware. Falls back to an empty list if the
    middleware didn't run (e.g. error responses).
    """
    adapter = getattr(request.state, "adapter", None)
    return {
        "current_ns": getattr(adapter, "namespace", "main") if adapter else "main",
        "ns_writable": getattr(adapter, "writable", True) if adapter else True,
        "namespaces": getattr(request.state, "namespaces", []) or [],
    }


def _to_minute(value: str | None) -> str:
    if not value:
        return ""
    text = str(value)
    if "T" not in text:
        return text
    return text.replace("T", " ")[:16]


TEMPLATES = Jinja2Templates(
    directory=str(_PKG_DIR / "templates"),
    context_processors=[lang_context, _namespace_context],
)
# Make the skill version available to every template without per-route boilerplate.
TEMPLATES.env.globals["skill_version"] = SKILL_VERSION
TEMPLATES.env.filters["to_minute"] = _to_minute


def create_app(config_path: str | None = None) -> FastAPI:
    # docs_url / redoc_url / openapi_url disabled so we own /docs ourselves.
    app = FastAPI(
        title="using-memory web",
        version=SKILL_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    adapter = MemoryAdapter(config_path=config_path)
    registry = NamespaceRegistry(adapter)

    app.state.adapter = adapter
    app.state.namespaces = registry
    app.state.templates = TEMPLATES
    app.state.skill_version = SKILL_VERSION
    app.state.api_token = _remote_api_token(adapter)

    interval_min = read_interval_from_env()
    scheduler = MaintenanceScheduler(adapter, interval_minutes=interval_min)
    app.state.maintenance = scheduler

    @app.on_event("startup")
    async def _start_maintenance() -> None:
        scheduler.start()

    @app.on_event("shutdown")
    async def _stop_maintenance() -> None:
        await scheduler.stop()

    @app.middleware("http")
    async def attach_lang(request: Request, call_next):
        # Query ?lang= takes precedence so deep-linking with explicit lang works
        # even before the cookie is set.
        lang = resolve_lang(
            query=request.query_params.get("lang"),
            cookie=request.cookies.get(COOKIE_NAME),
            accept_language=request.headers.get("accept-language"),
        )
        request.state.lang = lang
        return await call_next(request)

    @app.middleware("http")
    async def attach_namespace(request: Request, call_next):
        # ?ns= overrides the cookie (one-shot deep linking) but does not
        # persist; /ns/<name> is the way to switch durably via cookie.
        ns_name = (
            request.query_params.get("ns")
            or request.cookies.get(NAMESPACE_COOKIE)
        )
        request.state.adapter = registry.resolve(ns_name)
        request.state.namespaces = registry.available()
        return await call_next(request)

    @app.middleware("http")
    async def require_api_token(request: Request, call_next):
        token = app.state.api_token
        if token and request.url.path.startswith("/api/v1") and not _is_loopback_request(request):
            expected = f"Bearer {token}"
            if request.headers.get("authorization") != expected:
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/lang/{code}", name="set_lang")
    def set_lang(code: str, request: Request):
        if code not in SUPPORTED:
            return RedirectResponse("/", status_code=303)
        target = request.headers.get("referer") or "/"
        resp = RedirectResponse(target, status_code=303)
        # 1 year, sane defaults — no JS, host-only, same-site lax.
        resp.set_cookie(
            COOKIE_NAME,
            code,
            max_age=60 * 60 * 24 * 365,
            httponly=False,
            samesite="lax",
        )
        return resp

    @app.get("/ns/{name}", name="set_namespace")
    def set_namespace(name: str, request: Request):
        # Only allow switching to a discovered namespace; anything else is a
        # cookie clear (back to the default).
        valid = {row["name"] for row in registry.available()}
        # The referer typically points at a namespace-scoped resource (e.g.
        # /docs/foo.md or /logs?from=...). Switching ns and replaying that
        # URL against the new ns 404s the moment the entity does not exist
        # there. Redirect to a stable section root (or home for unknown
        # paths) so the user always lands somewhere valid in the new ns.
        referer = request.headers.get("referer") or "/"
        target = _safe_namespace_target(referer)
        resp = RedirectResponse(target, status_code=303)
        if name == registry.default_namespace or name not in valid:
            resp.delete_cookie(NAMESPACE_COOKIE)
        else:
            resp.set_cookie(
                NAMESPACE_COOKIE,
                name,
                max_age=60 * 60 * 24 * 365,
                httponly=False,
                samesite="lax",
            )
        return resp

    # Serve the SVG favicon at /favicon.ico (browsers request that path even
    # when <link rel="icon"> points elsewhere). Returns the same SVG file.
    _favicon = _PKG_DIR / "static" / "favicon.svg"

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(_favicon, media_type="image/svg+xml")

    app.mount(
        "/static",
        StaticFiles(directory=str(_PKG_DIR / "static")),
        name="static",
    )

    app.include_router(dashboard.router)
    app.include_router(logs.router)
    app.include_router(search.router)
    app.include_router(downloads.router)
    app.include_router(docs.router)
    app.include_router(memory.router)
    app.include_router(preferences.router)
    app.include_router(admin.router)
    app.include_router(api_v1.router)

    return app
