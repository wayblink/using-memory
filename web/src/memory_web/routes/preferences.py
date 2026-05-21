from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..adapter import MemoryToolError

router = APIRouter()


@router.get("/preferences", response_class=HTMLResponse, name="preferences")
def preferences(request: Request, error: str | None = None) -> HTMLResponse:
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    content = adapter.read_text_file("PREFERENCES.md") or ""
    return templates.TemplateResponse(
        request,
        "preferences.html",
        {
            "page": "preferences",
            "content": content,
            "missing": not content,
            "error": error,
        },
    )


@router.post("/preferences/append")
def preferences_append(request: Request, text: str = Form(...)):
    adapter = request.app.state.adapter
    try:
        adapter.write_preference(text=text)
    except MemoryToolError as exc:
        from urllib.parse import urlencode
        qs = urlencode({"error": str(exc)})
        return RedirectResponse(f"/preferences?{qs}", status_code=303)
    return RedirectResponse("/preferences", status_code=303)
