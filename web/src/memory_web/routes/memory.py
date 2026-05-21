from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/memory", response_class=HTMLResponse, name="memory")
def memory(request: Request) -> HTMLResponse:
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
        },
    )
