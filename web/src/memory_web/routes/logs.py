from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from .pagination import PER_PAGE_OPTIONS, normalize_per_page, paginate_items

DEFAULT_LOGS_PER_PAGE = 10

router = APIRouter()


@router.get("/logs", response_class=HTMLResponse, name="logs")
def logs(
    request: Request,
    log_from: str | None = Query(None, alias="from"),
    log_to: str | None = Query(None, alias="to"),
    days: int | None = Query(0, ge=0, le=365),
    q: str | None = None,
    tag: list[str] | None = Query(None),
    level: str | None = None,
    source: str | None = None,
    project: list[str] | None = Query(None),
    topic: list[str] | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int | None = Query(DEFAULT_LOGS_PER_PAGE),
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
    per_page_value = normalize_per_page(per_page)
    days_value = 0 if days in (None, 0) else days

    def _load_all_entries() -> list[dict]:
        root = adapter.primary_root()
        if root is None:
            return []
        log_dir = root / "log"
        if not log_dir.exists():
            return []
        all_entries: list[dict] = []
        for path in sorted(log_dir.glob("*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    all_entries.append(entry)
        return all_entries

    if log_from or log_to or days_value > 0:
        snapshot = adapter.load(
            log_from=log_from,
            log_to=log_to,
            log_days=days_value,
            log_query=q,
            projects=project or None,
            topics=topic or None,
        )
        filtered_entries = list(snapshot.get("log_entries", []))
    else:
        snapshot = {"log_entries": []}
        filtered_entries = _load_all_entries()
        if q:
            q_lower = q.lower()
            filtered_entries = [e for e in filtered_entries if q_lower in str(e.get("text") or "").lower()]
        if project:
            project_set = set(project)
            filtered_entries = [e for e in filtered_entries if e.get("project") in project_set]
        if topic:
            topic_set = set(topic)
            filtered_entries = [e for e in filtered_entries if e.get("topic") in topic_set]

    entries = list(filtered_entries)

    # Client-side post filters (the load command doesn't filter on tag/level/source).
    if tag:
        tag_set = set(tag)
        entries = [e for e in entries if e.get("tag") in tag_set]
    if level:
        entries = [e for e in entries if e.get("level") == level]
    if source:
        entries = [e for e in entries if e.get("source") == source]

    entries.sort(key=lambda e: (e.get("ts") or e.get("date") or ""), reverse=True)
    pagination = paginate_items(
        entries,
        page=page,
        per_page=per_page_value,
        base_path="/logs",
        query_params={
            "from": log_from,
            "to": log_to,
            "days": days,
            "q": q,
            "tag": tag,
            "level": level,
            "source": source,
            "project": project,
            "topic": topic,
        },
    )

    available_tags = sorted({e.get("tag") for e in filtered_entries if e.get("tag")})
    available_topics = sorted({e.get("topic") for e in filtered_entries if e.get("topic")})
    available_projects = sorted({e.get("project") for e in filtered_entries if e.get("project")})

    today = date.today()
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "page": "logs",
            "entries": pagination["items"],
            "total": pagination["total"],
            "pagination": pagination,
            "per_page_options": PER_PAGE_OPTIONS,
            "selected": {
                "from": log_from,
                "to": log_to,
                "days": days_value,
                "q": q or "",
                "tags": tag,
                "level": level or "",
                "source": source or "",
                "projects": project,
                "topics": topic,
                "page": pagination["page"],
                "per_page": pagination["per_page"],
            },
            "available_tags": available_tags,
            "available_topics": available_topics,
            "available_projects": available_projects,
            "today": today.isoformat(),
            "default_from": (today - timedelta(days=6)).isoformat(),
        },
    )
