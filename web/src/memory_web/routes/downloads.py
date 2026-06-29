from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse


router = APIRouter()


def _attachment(path: Path, filename: str | None = None) -> FileResponse:
    return FileResponse(
        path,
        filename=filename or path.name,
        media_type="application/octet-stream",
    )


@router.get("/memory/download", name="memory_download")
def memory_download(request: Request) -> FileResponse:
    adapter = request.state.adapter
    path = adapter.namespace_file_path("MEMORY.md")
    if path is None:
        raise HTTPException(status_code=404, detail="MEMORY.md not found")
    return _attachment(path, "MEMORY.md")


@router.get("/preferences/download", name="preferences_download")
def preferences_download(request: Request) -> FileResponse:
    adapter = request.state.adapter
    path = adapter.namespace_file_path("PREFERENCES.md")
    if path is None:
        raise HTTPException(status_code=404, detail="PREFERENCES.md not found")
    return _attachment(path, "PREFERENCES.md")


@router.get("/docs/{slug:path}/download", name="doc_download")
def doc_download(request: Request, slug: str) -> FileResponse:
    adapter = request.state.adapter
    path = adapter.resolve_doc_path(slug)
    if path is None:
        raise HTTPException(status_code=404, detail=f"doc not found: {slug}")
    return _attachment(path, path.name)


@router.get("/anatomy/{slug}/download", name="anatomy_download")
def anatomy_download(
    request: Request,
    slug: str,
    format: str = Query("json"),
) -> FileResponse:
    adapter = request.state.adapter
    path = adapter.anatomy_file_path(slug, format)
    if path is None:
        raise HTTPException(status_code=404, detail=f"anatomy file not found: {slug}.{format}")
    return _attachment(path, path.name)
