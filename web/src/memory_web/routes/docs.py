from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

router = APIRouter()


@router.get("/docs", response_class=HTMLResponse, name="docs_index")
def docs_index(request: Request) -> HTMLResponse:
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    items = adapter.list_docs()
    by_type: dict[str, list[dict]] = {}
    for item in items:
        by_type.setdefault(item.get("type") or "wiki", []).append(item)
    for k in by_type:
        by_type[k].sort(key=lambda e: (e.get("title") or e.get("rel") or "").lower())

    return templates.TemplateResponse(
        request,
        "docs_index.html",
        {
            "page": "docs",
            "items": items,
            "by_type": dict(sorted(by_type.items())),
            "total": len(items),
            "unregistered": sum(1 for i in items if not i.get("in_index")),
        },
    )


@router.get("/docs/{slug:path}", name="doc_view")
def doc_view(
    request: Request,
    slug: str,
    raw: int | None = Query(None),
):
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    doc = adapter.read_doc(slug)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"doc not found: {slug}")

    if raw:
        media = "text/markdown; charset=utf-8" if doc["ext"] == "md" else "text/plain; charset=utf-8"
        return PlainTextResponse(doc["content"], media_type=media)

    return templates.TemplateResponse(
        request,
        "doc.html",
        {
            "page": "docs",
            "slug": doc["slug"],
            "rel": doc["rel"],
            "ext": doc["ext"],
            "entry": doc.get("entry") or {},
            "in_index": doc["in_index"],
            "content": doc["content"],
        },
    )
