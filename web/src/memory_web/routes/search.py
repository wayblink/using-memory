from __future__ import annotations

from pathlib import PurePath
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


_SCOPE_TO_FLAGS = {
    "all": (False, False, False),       # docs, memory, log all included
    "docs": (False, True, True),        # only docs
    "memory": (True, False, True),      # only memory
    "log": (True, True, False),         # only log
}


def _doc_link(path: str) -> str:
    # Index hits use a relative path like "foo.md" / "page.html" / "notes.txt";
    # some sources include the docs/ prefix or absolute path. We pass the full
    # rel path (with extension) to /docs/<rel> so any registered format
    # resolves correctly — read_doc honours an explicit extension before
    # falling back to the historic md→html→htm→txt resolution order.
    if "/docs/" in path:
        path = path.split("/docs/", 1)[1]
    rel = path.lstrip("/")
    return f"/docs/{rel}" if rel else "/docs"


def _log_link(path: str, q: str | None) -> tuple[str, str]:
    """Return (href, human_label) for a log hit. Falls back to /logs root."""
    name = PurePath(path).stem  # 2026-05-08
    if len(name) == 10 and name[4] == "-" and name[7] == "-":
        params = {"from": name, "to": name}
        if q:
            params["q"] = q
        return f"/logs?{urlencode(params)}", name
    return "/logs", path


@router.get("/search", response_class=HTMLResponse, name="search")
def search(
    request: Request,
    q: str | None = None,
    log_days: int = Query(30, ge=1, le=3650),
    scope: str | None = None,
) -> HTMLResponse:
    adapter = request.state.adapter
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
            # Add navigation metadata so the template can render clickable cards.
            path = hit.get("path") or ""
            if bucket == "docs":
                hit["link"] = _doc_link(path)
                hit["where"] = PurePath(path).name
            elif bucket == "memory":
                hit["link"] = "/memory"
                hit["where"] = "MEMORY.md"
                if hit.get("line"):
                    hit["where"] += f" · line {hit['line']}"
            else:  # log
                hit["link"], date_label = _log_link(path, q)
                hit["where"] = date_label
                if hit.get("line"):
                    hit["where"] += f" · line {hit['line']}"
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
