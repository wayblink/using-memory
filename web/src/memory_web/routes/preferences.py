from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/preferences", response_class=HTMLResponse, name="preferences")
def preferences(request: Request) -> HTMLResponse:
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
        },
    )
