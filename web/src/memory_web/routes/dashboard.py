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
    adapter = request.app.state.adapter
    templates = request.app.state.templates

    status = adapter.status()
    stats = adapter.stats()
    anatomy = adapter.anatomy_list()

    lifetime = status.get("lifetime", {}) or {}
    ratios = status.get("ratios", {}) or {}

    log_block = stats.get("log") or {}
    memory_block = stats.get("memory") or {}

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
