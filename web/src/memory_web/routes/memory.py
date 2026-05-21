from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..adapter import MemoryToolError

router = APIRouter()

MEMORY_TAGS = ("fact", "decision", "lesson")


@router.get("/memory", response_class=HTMLResponse, name="memory")
def memory(request: Request, error: str | None = None) -> HTMLResponse:
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    content = adapter.read_text_file("MEMORY.md") or ""
    return templates.TemplateResponse(
        request,
        "memory.html",
        {
            "page": "memory",
            "content": content,
            "missing": not content,
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
    adapter = request.app.state.adapter
    try:
        adapter.write_memory(when=(when or None), tag=tag, text=text)
    except MemoryToolError as exc:
        # PRG-with-error: redirect back to /memory with the error in a query
        # string. Keeps refresh-friendly URLs and avoids re-rendering with
        # unsaved form state for now (v0.4 keeps the editor minimal).
        from urllib.parse import urlencode
        qs = urlencode({"error": str(exc)})
        return RedirectResponse(f"/memory?{qs}", status_code=303)
    return RedirectResponse("/memory", status_code=303)
