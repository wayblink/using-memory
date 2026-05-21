from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/anatomy", response_class=HTMLResponse, name="anatomy_index")
def anatomy_index(request: Request) -> HTMLResponse:
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    listing = adapter.anatomy_list()
    return templates.TemplateResponse(
        request,
        "anatomy_index.html",
        {
            "page": "anatomy",
            "projects": listing.get("projects", []),
            "count": listing.get("count", 0),
        },
    )


@router.get("/anatomy/{slug}", response_class=HTMLResponse, name="anatomy_show")
def anatomy_show(request: Request, slug: str) -> HTMLResponse:
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    data = adapter.anatomy_show(slug)
    if not data:
        raise HTTPException(status_code=404, detail=f"anatomy not found: {slug}")

    files = data.get("files") or {}
    file_rows = []
    if isinstance(files, dict):
        for rel, info in sorted(files.items()):
            info = info or {}
            file_rows.append({
                "rel": rel,
                "desc": info.get("desc") or "",
                "desc_source": info.get("desc_source") or "auto",
                "tokens_est": info.get("tokens_est") or 0,
                "kind": info.get("kind") or "other",
                "mtime": info.get("mtime"),
            })

    totals = data.get("totals") or {}
    return templates.TemplateResponse(
        request,
        "anatomy.html",
        {
            "page": "anatomy",
            "slug": slug,
            "root": data.get("root"),
            "scanned_at": data.get("scanned_at"),
            "totals": totals,
            "files": file_rows,
            "raw": data,
        },
    )
