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

    log_block = stats.get("log") or {}
    memory_block = stats.get("memory") or {}

    def _sorted_by_count(by_tag: dict) -> list[dict]:
        items = [(k, v) for k, v in (by_tag or {}).items() if k]
        items.sort(key=lambda kv: (-kv[1], kv[0]))
        return [{"tag": k, "count": v} for k, v in items]

    log_tags = _sorted_by_count(log_block.get("by_tag") or {})
    memory_tags = _sorted_by_count(memory_block.get("by_tag") or {})
    log_max = log_tags[0]["count"] if log_tags else 0
    memory_max = memory_tags[0]["count"] if memory_tags else 0

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "page": "dashboard",
            "status": status,
            "lifetime": lifetime,
            "ratios": ratios,
            "stats": stats,
            "log_total": log_block.get("total", 0),
            "memory_total": memory_block.get("total", 0),
            "log_tags": log_tags,
            "memory_tags": memory_tags,
            "log_max": log_max,
            "memory_max": memory_max,
            "anatomy_count": anatomy.get("count", 0),
            "anatomy_projects": anatomy.get("projects", []),
            "last_event_ts": status.get("last_event_ts"),
            "warnings": status.get("warnings", []),
        },
    )
