from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse, name="dashboard")
def dashboard(request: Request) -> HTMLResponse:
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    status = adapter.status()
    stats = adapter.stats()
    anatomy = adapter.anatomy_list()

    lifetime = status.get("lifetime", {}) or {}
    ratios = status.get("ratios", {}) or {}

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "page": "dashboard",
            "status": status,
            "lifetime": lifetime,
            "ratios": ratios,
            "stats": stats,
            "anatomy_count": anatomy.get("count", 0),
            "anatomy_projects": anatomy.get("projects", []),
            "last_event_ts": status.get("last_event_ts"),
            "warnings": status.get("warnings", []),
        },
    )
