"""JSON API (v1) for using-memory — command-level CRUD over the memory repo.

Reuses ``MemoryAdapter`` (the same ``do_*`` handlers the CLI runs, against local
files). This is the **server side** of the remote backend: an external
``umem`` / ``memory_tool`` client can POST here instead of writing local files.
The adapter always operates on local storage, so there is no web→HTTP→web
recursion.

All write handlers surface ``MemoryToolError`` (validation failures) as HTTP
400 so a client can self-correct, mirroring the CLI's stderr behaviour.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ..adapter import MemoryToolError

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


class LogIn(BaseModel):
    tag: str
    text: str
    date: str | None = None
    level: str = "detail"
    confidence: int | None = None
    source: str | None = None
    files: list[str] | None = None
    project: str | None = None
    topic: str | None = None


class MemoryIn(BaseModel):
    tag: str
    text: str
    date: str | None = None


class PreferenceIn(BaseModel):
    text: str
    date: str | None = None


class DocIn(BaseModel):
    doc: str
    text: str
    title: str | None = None
    doc_type: str | None = None
    created: str | None = None
    modified: str | None = None
    projects: list[str] | None = None
    doc_tags: list[str] | None = None
    summary: str | None = None
    link_logs: list[str] | None = None


def _adapter(request: Request):
    # Set by the attach_namespace middleware; defaults to the primary namespace
    # when no ?ns= / cookie is present (API clients normally send neither).
    return request.state.adapter


def _guard(fn):
    try:
        return fn()
    except MemoryToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/health")
def api_health():
    return {"ok": True, "api": "v1"}


@router.post("/log")
def api_write_log(payload: LogIn, request: Request):
    a = _adapter(request)
    return _guard(lambda: a.write_log(
        when=payload.date, tag=payload.tag, text=payload.text, level=payload.level,
        confidence=payload.confidence, source=payload.source, files=payload.files,
        project=payload.project, topic=payload.topic,
    ))


@router.post("/memory")
def api_write_memory(payload: MemoryIn, request: Request):
    a = _adapter(request)
    return _guard(lambda: a.write_memory(when=payload.date, tag=payload.tag, text=payload.text))


@router.post("/preference")
def api_write_preference(payload: PreferenceIn, request: Request):
    a = _adapter(request)
    return _guard(lambda: a.write_preference(when=payload.date, text=payload.text))


@router.post("/doc")
def api_upsert_doc(payload: DocIn, request: Request):
    a = _adapter(request)
    return _guard(lambda: a.upsert_doc(
        doc=payload.doc, text=payload.text, title=payload.title, doc_type=payload.doc_type,
        created=payload.created, modified=payload.modified, projects=payload.projects,
        doc_tags=payload.doc_tags, summary=payload.summary, link_logs=payload.link_logs,
    ))


@router.get("/load")
def api_load(request: Request, date: str | None = None, log_days: int | None = None,
             log_from: str | None = None, log_to: str | None = None,
             log_query: str | None = None, project: list[str] | None = Query(default=None),
             topic: list[str] | None = Query(default=None), doc: str | None = None,
             doc_type: str | None = None, doc_tag: list[str] | None = Query(default=None),
             doc_query: str | None = None):
    a = _adapter(request)
    return _guard(lambda: a.load(
        date=date, log_from=log_from, log_to=log_to, log_days=log_days,
        log_query=log_query, projects=project, topics=topic, doc=doc,
        doc_type=doc_type, doc_tags=doc_tag, doc_query=doc_query,
    ))


@router.get("/search")
def api_search(request: Request, q: str, log_days: int = 30, no_docs: bool = False,
               no_memory: bool = False, no_log: bool = False,
               project: list[str] | None = Query(default=None),
               topic: list[str] | None = Query(default=None)):
    a = _adapter(request)
    return _guard(lambda: a.search(
        query=q, log_days=log_days, no_docs=no_docs, no_memory=no_memory,
        no_log=no_log, projects=project, topics=topic,
    ))
