from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..adapter import MemoryToolError

router = APIRouter()

MEMORY_TAGS = ("fact", "decision", "lesson")


def _redirect_with_error(exc: MemoryToolError) -> RedirectResponse:
    qs = urlencode({"error": str(exc)})
    return RedirectResponse(f"/memory?{qs}", status_code=303)


@router.get("/memory", response_class=HTMLResponse, name="memory")
def memory(request: Request, error: str | None = None) -> HTMLResponse:
    adapter = request.state.adapter
    templates = request.app.state.templates

    entries = adapter.list_memory_entries()
    return templates.TemplateResponse(
        request,
        "memory.html",
        {
            "page": "memory",
            "entries": entries,
            "missing": not entries,
            "memory_tags": MEMORY_TAGS,
            "today": date.today().isoformat(),
            "error": error,
        },
    )


@router.post("/memory/append")
def memory_append(
    request: Request,
    tag: str = Form(...),
    text: str = Form(...),
    when: str = Form(""),
):
    adapter = request.state.adapter
    try:
        adapter.write_memory(when=(when or None), tag=tag, text=text)
    except MemoryToolError as exc:
        return _redirect_with_error(exc)
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/update/{line_no}")
def memory_update(
    line_no: int,
    request: Request,
    tag: str = Form(...),
    text: str = Form(...),
    when: str = Form(""),
):
    adapter = request.state.adapter
    try:
        adapter.update_memory_line(line_no=line_no, tag=tag, when=when or None, text=text)
    except MemoryToolError as exc:
        return _redirect_with_error(exc)
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/delete/{line_no}")
def memory_delete(line_no: int, request: Request):
    adapter = request.state.adapter
    try:
        adapter.delete_memory_line(line_no=line_no)
    except MemoryToolError as exc:
        return _redirect_with_error(exc)
    return RedirectResponse("/memory", status_code=303)
