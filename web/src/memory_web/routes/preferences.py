from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..adapter import MemoryToolError

router = APIRouter()

# `/preferences` was the page's address before rules were renamed to SPEC. Old
# bookmarks and links keep working; the canonical route is now `/spec`.
LEGACY_ROUTE = "/preferences"
CANONICAL_ROUTE = "/spec"


def _redirect_with_error(exc: MemoryToolError, scope: str = "global") -> RedirectResponse:
    qs = urlencode({"error": str(exc), "scope": scope})
    return RedirectResponse(f"{CANONICAL_ROUTE}?{qs}", status_code=303)


def _safe_scope(raw: str | None, valid: list[str]) -> str:
    """Fall back to global rather than 500 when a scope disappears.

    A project file can be deleted between page load and form submit; treating
    that as an error would surface as a crash for a stale tab.
    """
    if raw and raw in valid:
        return raw
    return "global"


@router.get(CANONICAL_ROUTE, response_class=HTMLResponse, name="spec")
def spec(
    request: Request,
    scope: str | None = None,
    mode: str = "files",
    error: str | None = None,
) -> HTMLResponse:
    adapter = request.state.adapter
    templates = request.app.state.templates

    scopes = adapter.list_spec_scopes()
    active = _safe_scope(scope, scopes)
    files = adapter.list_all_spec_files()
    # `mode=file` narrows to one file; the default shows every file as its own
    # group, because a file is a scope and flattening hides who a rule binds.
    if mode == "file":
        files = [f for f in files if f["scope"] == active]
    total = sum(f["count"] for f in files)
    # Empty means "nothing to edit": no file has any body. Judging by rule count
    # would hide a file whose rules lack the `[date]` marker.
    has_body = any(f["text"].strip() for f in files)
    return templates.TemplateResponse(
        request,
        "preferences.html",
        {
            "page": "spec",
            "files": files,
            "total": total,
            "missing": not has_body,
            "today": date.today().isoformat(),
            "error": error,
            "scopes": scopes,
            "active_scope": active,
            "mode": "file" if mode == "file" else "files",
        },
    )


@router.get(LEGACY_ROUTE, response_class=HTMLResponse, include_in_schema=False)
def preferences_legacy(request: Request, scope: str | None = None, error: str | None = None):
    qs = urlencode({k: v for k, v in (("scope", scope), ("error", error)) if v})
    target = f"{CANONICAL_ROUTE}?{qs}" if qs else CANONICAL_ROUTE
    return RedirectResponse(target, status_code=301)


@router.get(f"{CANONICAL_ROUTE}/edit/{{scope}}", response_class=HTMLResponse, name="spec_edit")
def spec_edit(request: Request, scope: str, error: str | None = None) -> HTMLResponse:
    """Edit one spec file as a whole.

    The file is the unit: its heading and its scope sentence cannot be carried
    by individual rule rows, and a rule list cannot express a new rule that the
    writer wants to word differently.
    """
    adapter = request.state.adapter
    templates = request.app.state.templates
    scopes = adapter.list_spec_scopes()
    if scope not in scopes:
        raise HTTPException(status_code=404, detail=f"unknown spec scope: {scope}")
    return templates.TemplateResponse(
        request,
        "spec_edit.html",
        {
            "page": "spec",
            "scope": scope,
            "relative": adapter._spec_relative(scope),
            "text": adapter.read_text_file(adapter._spec_relative(scope)) or "",
            "error": error,
        },
    )


@router.post(f"{CANONICAL_ROUTE}/save")
def spec_save(
    request: Request,
    text: str = Form(""),
    scope: str = Form("global"),
):
    """Write a whole spec file.

    The file is the unit of editing: its heading and its scope cannot be
    expressed by any single rule row, and rewriting the file from rows would
    drop both.
    """
    adapter = request.state.adapter
    active = _safe_scope(scope, adapter.list_spec_scopes())
    try:
        adapter.write_spec_file(scope=active, text=text)
    except MemoryToolError as exc:
        return _redirect_with_error(exc, active)
    return RedirectResponse(f"{CANONICAL_ROUTE}?scope={active}&mode=file", status_code=303)


@router.post(f"{CANONICAL_ROUTE}/append")
def spec_append(
    request: Request,
    text: str = Form(...),
    when: str = Form(""),
    scope: str = Form("global"),
):
    adapter = request.state.adapter
    active = _safe_scope(scope, adapter.list_spec_scopes())
    try:
        adapter.write_preference(when=(when or None), text=text, scope=active)
    except MemoryToolError as exc:
        return _redirect_with_error(exc, active)
    return RedirectResponse(f"{CANONICAL_ROUTE}?scope={active}", status_code=303)


@router.post(f"{CANONICAL_ROUTE}/update/{{line_no}}")
def spec_update(
    line_no: int,
    request: Request,
    text: str = Form(...),
    when: str = Form(""),
    scope: str = Form("global"),
):
    adapter = request.state.adapter
    active = _safe_scope(scope, adapter.list_spec_scopes())
    try:
        adapter.update_preference_line(
            line_no=line_no, when=when or None, text=text, scope=active
        )
    except MemoryToolError as exc:
        return _redirect_with_error(exc, active)
    return RedirectResponse(f"{CANONICAL_ROUTE}?scope={active}", status_code=303)


@router.post(f"{CANONICAL_ROUTE}/delete/{{line_no}}")
def spec_delete(line_no: int, request: Request, scope: str = Form("global")):
    adapter = request.state.adapter
    active = _safe_scope(scope, adapter.list_spec_scopes())
    try:
        adapter.delete_preference_line(line_no=line_no, scope=active)
    except MemoryToolError as exc:
        return _redirect_with_error(exc, active)
    return RedirectResponse(f"{CANONICAL_ROUTE}?scope={active}", status_code=303)
