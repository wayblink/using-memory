"""FastAPI app for browsing using-memory content."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .adapter import MemoryAdapter
from .i18n import COOKIE_NAME, SUPPORTED, lang_context, resolve_lang
from .routes import anatomy, dashboard, docs, logs, memory, preferences, search


_PKG_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(
    directory=str(_PKG_DIR / "templates"),
    context_processors=[lang_context],
)


def create_app(config_path: str | None = None) -> FastAPI:
    # docs_url / redoc_url / openapi_url disabled so we own /docs ourselves.
    app = FastAPI(
        title="using-memory web",
        version="0.4.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    adapter = MemoryAdapter(config_path=config_path)

    app.state.adapter = adapter
    app.state.templates = TEMPLATES

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

    app.mount(
        "/static",
        StaticFiles(directory=str(_PKG_DIR / "static")),
        name="static",
    )

    app.include_router(dashboard.router)
    app.include_router(logs.router)
    app.include_router(search.router)
    app.include_router(docs.router)
    app.include_router(memory.router)
    app.include_router(preferences.router)
    app.include_router(anatomy.router)

    return app
