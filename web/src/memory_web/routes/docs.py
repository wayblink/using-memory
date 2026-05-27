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

DOC_EXTS = ("md", "html", "txt")
DEFAULT_DOC_EXT = "md"
EDITABLE_DOC_EXTS = frozenset({"md", "html", "htm", "txt"})

GROUP_OPTIONS = ("none", "type", "project")
SORT_OPTIONS = ("name", "modified")
NO_PROJECT_KEY = "__no_project__"
ALL_DOCS_KEY = "__all_docs__"


@router.get("/docs", response_class=HTMLResponse, name="docs_index")
def docs_index(
    request: Request,
    type: str | None = None,
    format: str | None = None,
    project: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    indexed: str | None = None,
    group: str | None = None,
    sort: str | None = None,
) -> HTMLResponse:
    adapter = request.state.adapter
    templates = request.app.state.templates

    items = adapter.list_docs()

    # Build available-value lists from the full doc set (before filtering)
    # so dropdowns reflect what exists on disk, not what survived a filter.
    available_types = sorted({(i.get("type") or "wiki") for i in items})
    available_projects = sorted({p for i in items for p in (i.get("projects") or [])})
    available_tags = sorted({t for i in items for t in (i.get("tags") or [])})

    # Normalize empty form values.
    type = (type or "").strip() or None
    format = (format or "").strip() or None
    project = (project or "").strip() or None
    tag = (tag or "").strip() or None
    q = (q or "").strip() or None
    indexed_flag = (indexed or "").strip() or None  # "yes" | "no" | None
    group_value = (group or "").strip()
    if group_value not in GROUP_OPTIONS:
        group_value = "none"
    sort_value = (sort or "").strip()
    if sort_value not in SORT_OPTIONS:
        sort_value = "modified"

    filtered = items
    if type:
        filtered = [i for i in filtered if (i.get("type") or "wiki") == type]
    if format:
        filtered = [i for i in filtered if i.get("ext") == format]
    if project:
        filtered = [i for i in filtered if project in (i.get("projects") or [])]
    if tag:
        filtered = [i for i in filtered if tag in (i.get("tags") or [])]
    if indexed_flag == "yes":
        filtered = [i for i in filtered if i.get("in_index")]
    elif indexed_flag == "no":
        filtered = [i for i in filtered if not i.get("in_index")]
    if q:
        needle = q.lower()
        def _hay(i: dict) -> str:
            return " ".join(filter(None, [
                i.get("title") or "",
                i.get("slug") or "",
                i.get("rel") or "",
                i.get("summary") or "",
            ])).lower()
        filtered = [i for i in filtered if needle in _hay(i)]

    groups: dict[str, list[dict]] = {}
    if group_value == "none":
        groups[ALL_DOCS_KEY] = list(filtered)
    elif group_value == "project":
        for item in filtered:
            projects = item.get("projects") or []
            if projects:
                for p in projects:
                    groups.setdefault(p, []).append(item)
            else:
                groups.setdefault(NO_PROJECT_KEY, []).append(item)
    else:
        for item in filtered:
            groups.setdefault(item.get("type") or "wiki", []).append(item)

    def _name_key(e: dict) -> str:
        return (e.get("title") or e.get("rel") or "").lower()

    if sort_value == "modified":
        for k in groups:
            with_mod = [e for e in groups[k] if e.get("modified")]
            without_mod = [e for e in groups[k] if not e.get("modified")]
            # Two-pass stable sort: ascending name first, then descending date.
            # On equal dates, ascending-name order is preserved.
            with_mod.sort(key=_name_key)
            with_mod.sort(key=lambda e: e.get("modified") or "", reverse=True)
            without_mod.sort(key=_name_key)
            groups[k] = with_mod + without_mod
    else:
        for k in groups:
            groups[k].sort(key=_name_key)

    def _group_sort_key(k: str) -> tuple:
        # NO_PROJECT_KEY always last; everything else alphabetical.
        return (1, "") if k == NO_PROJECT_KEY else (0, k.lower())

    ordered_groups = dict(sorted(groups.items(), key=lambda kv: _group_sort_key(kv[0])))

    return templates.TemplateResponse(
        request,
        "docs_index.html",
        {
            "page": "docs",
            "items": filtered,
            "groups": ordered_groups,
            "total": len(filtered),
            "grand_total": len(items),
            "unregistered": sum(1 for i in filtered if not i.get("in_index")),
            "available_types": available_types,
            "available_projects": available_projects,
            "available_tags": available_tags,
            "no_project_key": NO_PROJECT_KEY,
            "all_docs_key": ALL_DOCS_KEY,
            "selected": {
                "type": type or "",
                "format": format or "",
                "project": project or "",
                "tag": tag or "",
                "q": q or "",
                "indexed": indexed_flag or "",
                "group": group_value,
                "sort": sort_value,
            },
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
            "ext": DEFAULT_DOC_EXT,
            "title": "",
            "doc_type": "wiki",
            "modified": "",
            "projects": "",
            "tags": "",
            "summary": "",
            "body": "",
            "doc_types": DOC_TYPES,
            "doc_exts": DOC_EXTS,
            "error": error,
        },
    )


@router.post("/docs/save")
def doc_save(
    request: Request,
    slug: str = Form(...),
    ext: str = Form(DEFAULT_DOC_EXT),
    title: str = Form(""),
    doc_type: str = Form("wiki"),
    modified: str = Form(""),
    projects: str = Form(""),
    tags: str = Form(""),
    summary: str = Form(""),
    body: str = Form(...),
):
    adapter = request.state.adapter

    project_list = [p.strip() for p in projects.split(",") if p.strip()]
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    slug = slug.strip()
    ext = (ext or "").strip().lower().lstrip(".")
    if ext not in EDITABLE_DOC_EXTS:
        ext = DEFAULT_DOC_EXT

    # If the user typed an extension into the slug field, honor it; otherwise
    # use the format selector. memory_tool.upsert-doc accepts the full rel
    # path (with extension) as ``--doc``.
    if "." in slug.rsplit("/", 1)[-1]:
        doc_arg = slug
        rel_for_redirect = slug
    else:
        doc_arg = f"{slug}.{ext}"
        rel_for_redirect = f"{slug}.{ext}"

    try:
        result = adapter.upsert_doc(
            doc=doc_arg,
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
                "ext": ext,
                "title": title,
                "doc_type": doc_type,
                "modified": modified,
                "projects": projects,
                "tags": tags,
                "summary": summary,
                "body": body,
                "doc_types": DOC_TYPES,
                "doc_exts": DOC_EXTS,
                "error": str(exc),
            },
            status_code=400,
        )

    return RedirectResponse(f"/docs/{rel_for_redirect}", status_code=303)


@router.get("/docs/{slug:path}", name="doc_view")
def doc_view(
    request: Request,
    slug: str,
    raw: int | None = Query(None),
    edit: int | None = Query(None),
):
    adapter = request.state.adapter
    templates = request.app.state.templates

    doc = adapter.read_doc(slug)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"doc not found: {slug}")

    if raw:
        if doc["ext"] == "md":
            media = "text/markdown; charset=utf-8"
        elif doc["ext"] in ("html", "htm"):
            media = "text/html; charset=utf-8"
        else:
            media = "text/plain; charset=utf-8"
        return PlainTextResponse(doc["content"], media_type=media)

    if edit:
        if doc["ext"] not in EDITABLE_DOC_EXTS:
            raise HTTPException(status_code=400, detail=f"{doc['ext']} docs are read-only; edit them on disk.")
        entry = doc.get("entry") or {}
        return templates.TemplateResponse(
            request,
            "doc_edit.html",
            {
                "page": "docs",
                "mode": "edit",
                "slug": doc["slug"],
                "ext": doc["ext"],
                "title": entry.get("title") or "",
                "doc_type": entry.get("type") or "wiki",
                "modified": entry.get("modified") or "",
                "projects": ", ".join(entry.get("projects") or []),
                "tags": ", ".join(entry.get("tags") or []),
                "summary": entry.get("summary") or "",
                "body": doc["content"],
                "doc_types": DOC_TYPES,
                "doc_exts": DOC_EXTS,
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
