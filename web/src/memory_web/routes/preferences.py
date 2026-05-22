from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..adapter import MemoryToolError

router = APIRouter()


def _redirect_with_error(exc: MemoryToolError) -> RedirectResponse:
    qs = urlencode({"error": str(exc)})
    return RedirectResponse(f"/preferences?{qs}", status_code=303)


@router.get("/preferences", response_class=HTMLResponse, name="preferences")
def preferences(request: Request, error: str | None = None) -> HTMLResponse:
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    entries = adapter.list_preference_entries()
    return templates.TemplateResponse(
        request,
        "preferences.html",
        {
            "page": "preferences",
            "entries": entries,
            "missing": not entries,
            "error": error,
        },
    )


@router.post("/preferences/append")
def preferences_append(request: Request, text: str = Form(...)):
    adapter = request.app.state.adapter
    try:
        adapter.write_preference(text=text)
    except MemoryToolError as exc:
        return _redirect_with_error(exc)
    return RedirectResponse("/preferences", status_code=303)


@router.post("/preferences/update/{line_no}")
def preferences_update(
    line_no: int,
    request: Request,
    text: str = Form(...),
):
    adapter = request.app.state.adapter
    try:
        adapter.update_preference_line(line_no=line_no, text=text)
    except MemoryToolError as exc:
        return _redirect_with_error(exc)
    return RedirectResponse("/preferences", status_code=303)


@router.post("/preferences/delete/{line_no}")
def preferences_delete(line_no: int, request: Request):
    adapter = request.app.state.adapter
    try:
        adapter.delete_preference_line(line_no=line_no)
    except MemoryToolError as exc:
        return _redirect_with_error(exc)
    return RedirectResponse("/preferences", status_code=303)
