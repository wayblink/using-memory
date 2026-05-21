from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


_SCOPE_TO_FLAGS = {
    "all": (False, False, False),       # docs, memory, log all included
    "docs": (False, True, True),        # only docs
    "memory": (True, False, True),      # only memory
    "log": (True, True, False),         # only log
}


@router.get("/search", response_class=HTMLResponse, name="search")
def search(
    request: Request,
    q: str | None = None,
    log_days: int = Query(30, ge=1, le=3650),
    scope: str | None = None,
) -> HTMLResponse:
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    scope_value = (scope or "all").strip().lower()
    if scope_value not in _SCOPE_TO_FLAGS:
        scope_value = "all"
    no_docs, no_memory, no_log = _SCOPE_TO_FLAGS[scope_value]

    results: dict | None = None
    grouped: dict[str, list[dict]] = {"docs": [], "memory": [], "log": []}
    total = 0
    if q:
        results = adapter.search(
            q,
            no_docs=no_docs,
            no_memory=no_memory,
            no_log=no_log,
            log_days=log_days,
        )
        source_map = {"docs": "docs", "MEMORY.md": "memory", "log": "log"}
        for hit in results.get("hits", []) or []:
            bucket = source_map.get(hit.get("source") or "", "log")
            grouped.setdefault(bucket, []).append(hit)
        total = results.get("total", sum(len(v) for v in grouped.values()))

    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "page": "search",
            "q": q or "",
            "log_days": log_days,
            "scope_value": scope_value,
            "results": results,
            "grouped": grouped,
            "total": total,
        },
    )
