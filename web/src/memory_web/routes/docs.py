from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from ..adapter import MemoryToolError

router = APIRouter()


DOC_TYPES = (
    "wiki",
    "lesson",
    "troubleshooting",
    "decision-record",
    "runbook",
    "SOP",
    "project",
)


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


# Specific routes MUST be registered before the /docs/{slug:path} catchall.

@router.get("/docs/new", response_class=HTMLResponse, name="doc_new")
def doc_new(request: Request, error: str | None = None) -> HTMLResponse:
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "doc_edit.html",
        {
            "page": "docs",
            "mode": "new",
            "slug": "",
            "title": "",
            "doc_type": "wiki",
            "modified": "",
            "projects": "",
            "tags": "",
            "summary": "",
            "body": "",
            "doc_types": DOC_TYPES,
            "error": error,
        },
    )


@router.post("/docs/save")
def doc_save(
    request: Request,
    slug: str = Form(...),
    title: str = Form(""),
    doc_type: str = Form("wiki"),
    modified: str = Form(""),
    projects: str = Form(""),
    tags: str = Form(""),
    summary: str = Form(""),
    body: str = Form(...),
):
    adapter = request.app.state.adapter

    project_list = [p.strip() for p in projects.split(",") if p.strip()]
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    slug = slug.strip()

    try:
        result = adapter.upsert_doc(
            doc=slug,
            text=body,
            title=(title or None),
            doc_type=(doc_type or None),
            modified=(modified or None),
            projects=project_list or None,
            doc_tags=tag_list or None,
            summary=(summary or None),
        )
    except MemoryToolError as exc:
        # Re-render editor with the form values intact so the user doesn't
        # lose their work on a validation failure.
        templates = request.app.state.templates
        return templates.TemplateResponse(
            request,
            "doc_edit.html",
            {
                "page": "docs",
                "mode": "new" if not slug else "edit",
                "slug": slug,
                "title": title,
                "doc_type": doc_type,
                "modified": modified,
                "projects": projects,
                "tags": tags,
                "summary": summary,
                "body": body,
                "doc_types": DOC_TYPES,
                "error": str(exc),
            },
            status_code=400,
        )

    return RedirectResponse(f"/docs/{slug}", status_code=303)


@router.get("/docs/{slug:path}", name="doc_view")
def doc_view(
    request: Request,
    slug: str,
    raw: int | None = Query(None),
    edit: int | None = Query(None),
):
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    doc = adapter.read_doc(slug)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"doc not found: {slug}")

    if raw:
        media = "text/markdown; charset=utf-8" if doc["ext"] == "md" else "text/plain; charset=utf-8"
        return PlainTextResponse(doc["content"], media_type=media)

    if edit:
        if doc["ext"] != "md":
            raise HTTPException(status_code=400, detail="HTML docs are read-only; edit them on disk.")
        entry = doc.get("entry") or {}
        return templates.TemplateResponse(
            request,
            "doc_edit.html",
            {
                "page": "docs",
                "mode": "edit",
                "slug": doc["slug"],
                "title": entry.get("title") or "",
                "doc_type": entry.get("type") or "wiki",
                "modified": entry.get("modified") or "",
                "projects": ", ".join(entry.get("projects") or []),
                "tags": ", ".join(entry.get("tags") or []),
                "summary": entry.get("summary") or "",
                "body": doc["content"],
                "doc_types": DOC_TYPES,
                "error": None,
            },
        )

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
