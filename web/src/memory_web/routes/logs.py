from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/logs", response_class=HTMLResponse, name="logs")
def logs(
    request: Request,
    log_from: str | None = Query(None, alias="from"),
    log_to: str | None = Query(None, alias="to"),
    days: int | None = Query(None, ge=1, le=365),
    q: str | None = None,
    tag: list[str] | None = Query(None),
    level: str | None = None,
    source: str | None = None,
    project: list[str] | None = Query(None),
    topic: list[str] | None = Query(None),
) -> HTMLResponse:
    adapter = request.state.adapter
    templates = request.app.state.templates

    # Empty form fields submit as "" — treat those as "no filter" so the
    # form's "all" option behaves as expected. (Without this, ?tag= would
    # set tag=[""] and filter every entry out, which is what users hit
    # when they cleared a filter via the form.)
    def _clean_list(values: list[str] | None) -> list[str]:
        return [v for v in (values or []) if v]

    tag = _clean_list(tag)
    project = _clean_list(project)
    topic = _clean_list(topic)
    level = (level or "").strip() or None
    source = (source or "").strip() or None
    q = (q or "").strip() or None

    # Default window: last 7 days when nothing else is set.
    if not (log_from or log_to or days):
        days = 7

    snapshot = adapter.load(
        log_from=log_from,
        log_to=log_to,
        log_days=days,
        log_query=q,
        projects=project or None,
        topics=topic or None,
    )
    entries = list(snapshot.get("log_entries", []))

    # Client-side post filters (the load command doesn't filter on tag/level/source).
    if tag:
        tag_set = set(tag)
        entries = [e for e in entries if e.get("tag") in tag_set]
    if level:
        entries = [e for e in entries if e.get("level") == level]
    if source:
        entries = [e for e in entries if e.get("source") == source]

    entries.sort(key=lambda e: (e.get("ts") or e.get("date") or ""), reverse=True)

    available_tags = sorted({e.get("tag") for e in snapshot.get("log_entries", []) if e.get("tag")})
    available_topics = sorted({e.get("topic") for e in snapshot.get("log_entries", []) if e.get("topic")})
    available_projects = sorted({e.get("project") for e in snapshot.get("log_entries", []) if e.get("project")})

    today = date.today()
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "page": "logs",
            "entries": entries,
            "total": len(entries),
            "selected": {
                "from": log_from,
                "to": log_to,
                "days": days,
                "q": q or "",
                "tags": tag,
                "level": level or "",
                "source": source or "",
                "projects": project,
                "topics": topic,
            },
            "available_tags": available_tags,
            "available_topics": available_topics,
            "available_projects": available_projects,
            "today": today.isoformat(),
            "default_from": (today - timedelta(days=6)).isoformat(),
        },
    )
