from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from ..adapter import MemoryToolError
from .pagination import DEFAULT_PER_PAGE, PER_PAGE_OPTIONS, normalize_per_page, paginate_items

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
SORT_OPTIONS = ("name", "modified", "created")
NO_PROJECT_KEY = "__no_project__"
ALL_DOCS_KEY = "__all_docs__"


def _to_minute(value: str | None) -> str:
    if not value:
        return ""
    if "T" not in value:
        return value
    return value.replace("T", " ")[:16]


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
    maintained: int | None = Query(None, ge=0),
    error: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int | None = Query(DEFAULT_PER_PAGE),
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
    per_page_value = normalize_per_page(per_page)

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

    def _name_key(e: dict) -> str:
        return (e.get("title") or e.get("rel") or "").lower()
    if sort_value in {"modified", "created"}:
        sort_field = sort_value
        with_date = [e for e in filtered if e.get(sort_field)]
        without_date = [e for e in filtered if not e.get(sort_field)]
        with_date.sort(key=_name_key)
        with_date.sort(key=lambda e: e.get(sort_field) or "", reverse=True)
        without_date.sort(key=_name_key)
        filtered = with_date + without_date
    else:
        filtered.sort(key=_name_key)

    pagination = paginate_items(
        filtered,
        page=page,
        per_page=per_page_value,
        base_path="/docs",
        query_params={
            "type": type,
            "format": format,
            "project": project,
            "tag": tag,
            "q": q,
            "indexed": indexed_flag,
            "group": group_value,
            "sort": sort_value,
        },
    )
    page_items = list(pagination["items"])

    groups: dict[str, list[dict]] = {}
    if group_value == "none":
        groups[ALL_DOCS_KEY] = page_items
    elif group_value == "project":
        for item in page_items:
            projects = item.get("projects") or []
            if projects:
                for p in projects:
                    groups.setdefault(p, []).append(item)
            else:
                groups.setdefault(NO_PROJECT_KEY, []).append(item)
    else:
        for item in page_items:
            groups.setdefault(item.get("type") or "wiki", []).append(item)

    def _group_sort_key(k: str) -> tuple:
        return (1, "") if k == NO_PROJECT_KEY else (0, k.lower())

    ordered_groups = dict(sorted(groups.items(), key=lambda kv: _group_sort_key(kv[0])))

    return templates.TemplateResponse(
        request,
        "docs_index.html",
        {
            "page": "docs",
            "items": page_items,
            "groups": ordered_groups,
            "total": pagination["total"],
            "grand_total": len(items),
            "unregistered": sum(1 for i in page_items if not i.get("in_index")),
            "pagination": pagination,
            "per_page_options": PER_PAGE_OPTIONS,
            "maintained": maintained,
            "error": error,
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
                "page": pagination["page"],
                "per_page": pagination["per_page"],
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
            "created_display": "",
            "projects": "",
            "tags": "",
            "summary": "",
            "body": "",
            "doc_types": DOC_TYPES,
            "doc_exts": DOC_EXTS,
            "error": error,
        },
    )


@router.post("/docs/refresh", name="docs_refresh")
def docs_refresh(request: Request):
    adapter = request.state.adapter
    try:
        report = adapter.maintain()
    except MemoryToolError as exc:
        return RedirectResponse(f"/docs?error={quote(str(exc))}", status_code=303)
    added = len(report.get("indexed_docs") or [])
    return RedirectResponse(f"/docs?maintained={added}", status_code=303)


@router.post("/docs/upload", name="docs_upload")
async def docs_upload(
    request: Request,
    file: UploadFile = File(...),
    path: str = Form(""),
    replace: str | None = Form(None),
):
    adapter = request.state.adapter
    filename = (file.filename or "").strip()
    target = (path or "").strip() or filename
    if not target:
        return RedirectResponse("/docs?error=missing%20upload%20filename", status_code=303)

    data = await file.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return RedirectResponse("/docs?error=uploaded%20file%20must%20be%20UTF-8%20text", status_code=303)

    try:
        rel = adapter.normalize_doc_upload_path(target)
        adapter.upload_doc(doc=rel, text=text, replace=bool(replace))
    except MemoryToolError as exc:
        return RedirectResponse(f"/docs?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(f"/docs/{rel}", status_code=303)


@router.post("/docs/save")
def doc_save(
    request: Request,
    slug: str = Form(...),
    ext: str = Form(DEFAULT_DOC_EXT),
    title: str = Form(""),
    doc_type: str = Form("wiki"),
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
                "created_display": "",
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
                "created_display": _to_minute(entry.get("created") or ""),
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
