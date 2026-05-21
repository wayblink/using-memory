"""FastAPI app for browsing using-memory content."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .adapter import MemoryAdapter
from .routes import anatomy, dashboard, docs, logs, memory, preferences, search


_PKG_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(_PKG_DIR / "templates"))


def create_app(config_path: str | None = None) -> FastAPI:
    # docs_url / redoc_url / openapi_url disabled so we own /docs ourselves.
    app = FastAPI(
        title="using-memory web",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    adapter = MemoryAdapter(config_path=config_path)

    app.state.adapter = adapter
    app.state.templates = TEMPLATES

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
