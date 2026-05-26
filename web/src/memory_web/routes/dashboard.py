from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


# Heuristic factors for the rough token-savings estimate. The skill has no
# real-API visibility, so these are explicit guesses about average sizes
# kept out of the conversation window. Document them so future readers know
# the number is directional, not precise.
_AUTO_SUMMARY_TOKENS_AVOIDED = 400   # avg detail entry size that a silent
                                     # Stop-hook summary replaces in-context
_STOP_BLOCK_TOKENS_AVOIDED = 200     # avg "context-bloat" message a Stop block
                                     # converts to a disk-only write
_ANATOMY_DISCOVERY_FACTOR = 1.0      # injected anatomy tokens are 1:1 saved
                                     # from the model needing to re-discover


@router.get("/", response_class=HTMLResponse, name="dashboard")
def dashboard(request: Request) -> HTMLResponse:
    adapter = request.state.adapter
    templates = request.app.state.templates

    status = adapter.status()
    stats = adapter.stats()
    anatomy = adapter.anatomy_list()

    lifetime = status.get("lifetime", {}) or {}
    ratios = status.get("ratios", {}) or {}

    log_block = stats.get("log") or {}
    memory_block = stats.get("memory") or {}

    # Docs counts straight from filesystem (already deduped/typed by adapter)
    docs_items = adapter.list_docs()
    docs_total = len(docs_items)
    docs_indexed = sum(1 for it in docs_items if it.get("in_index"))
    docs_unindexed = docs_total - docs_indexed
    docs_md = sum(1 for it in docs_items if it.get("ext") == "md")
    docs_html = sum(1 for it in docs_items if it.get("ext") == "html")

    # Preferences entry count: each line beginning with "- [" counts as an
    # entry. PREFERENCES.md is append-only with this single-format shape.
    prefs_text = adapter.read_text_file("PREFERENCES.md") or ""
    prefs_total = sum(1 for line in prefs_text.splitlines() if line.lstrip().startswith("- ["))

    # Distillation snapshot — read-only, cheap.
    try:
        distill = adapter.distill_candidates()
    except Exception:
        distill = {}
    distill_candidates = len(distill.get("buckets") or [])
    last_distill_check = lifetime.get("last_distill_check_ts") or distill.get("checked_at")
    last_promote = lifetime.get("last_promote_ts")

    def _short_ts(ts: str | None) -> str | None:
        if not ts:
            return None
        # Strip seconds + timezone for compactness (e.g. 2026-05-22 11:14)
        return ts.replace("T", " ")[:16]

    def _sorted_by_count(by_tag: dict) -> list[dict]:
        items = [(k, v) for k, v in (by_tag or {}).items() if k]
        items.sort(key=lambda kv: (-kv[1], kv[0]))
        return [{"tag": k, "count": v} for k, v in items]

    log_tags = _sorted_by_count(log_block.get("by_tag") or {})
    memory_tags = _sorted_by_count(memory_block.get("by_tag") or {})
    log_max = log_tags[0]["count"] if log_tags else 0
    memory_max = memory_tags[0]["count"] if memory_tags else 0

    def _int(key: str) -> int:
        try:
            return int(lifetime.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    anatomy_tokens = _int("anatomy_attached_tokens_est")
    auto_entries = _int("log_entries_auto")
    stop_blocks = _int("stop_blocks")

    savings_breakdown = {
        "anatomy": int(anatomy_tokens * _ANATOMY_DISCOVERY_FACTOR),
        "auto_summary": auto_entries * _AUTO_SUMMARY_TOKENS_AVOIDED,
        "stop_block": stop_blocks * _STOP_BLOCK_TOKENS_AVOIDED,
    }
    savings_total = sum(savings_breakdown.values())

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "page": "dashboard",
            "status": status,
            "lifetime": lifetime,
            "ratios": ratios,
            "stats": stats,
            "log_total": log_block.get("total", 0),
            "memory_total": memory_block.get("total", 0),
            "docs_total": docs_total,
            "docs_indexed": docs_indexed,
            "docs_unindexed": docs_unindexed,
            "docs_md": docs_md,
            "docs_html": docs_html,
            "prefs_total": prefs_total,
            "distill_candidates": distill_candidates,
            "last_distill_check": _short_ts(last_distill_check),
            "last_promote": _short_ts(last_promote),
            "log_tags": log_tags,
            "memory_tags": memory_tags,
            "log_max": log_max,
            "memory_max": memory_max,
            "anatomy_count": anatomy.get("count", 0),
            "anatomy_projects": anatomy.get("projects", []),
            "last_event_ts": status.get("last_event_ts"),
            "warnings": status.get("warnings", []),
            "savings_total": savings_total,
            "savings_breakdown": savings_breakdown,
            "savings_factors": {
                "auto_summary": _AUTO_SUMMARY_TOKENS_AVOIDED,
                "stop_block": _STOP_BLOCK_TOKENS_AVOIDED,
            },
        },
    )
