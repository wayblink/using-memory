from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/search", response_class=HTMLResponse, name="search")
def search(
    request: Request,
    q: str | None = None,
    log_days: int = Query(30, ge=1, le=365),
    scope: list[str] | None = Query(None),
) -> HTMLResponse:
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    scope_set = set(scope or ["docs", "memory", "log"])
    results: dict | None = None
    grouped: dict[str, list[dict]] = {"doc": [], "memory": [], "log": []}
    total = 0
    if q:
        results = adapter.search(
            q,
            no_docs="docs" not in scope_set,
            no_memory="memory" not in scope_set,
            no_log="log" not in scope_set,
            log_days=log_days,
        )
        for hit in results.get("hits", []) or []:
            src = hit.get("source") or "log"
            grouped.setdefault(src, []).append(hit)
        total = results.get("total", sum(len(v) for v in grouped.values()))

    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "page": "search",
            "q": q or "",
            "log_days": log_days,
            "scope": list(scope_set),
            "results": results,
            "grouped": grouped,
            "total": total,
        },
    )
