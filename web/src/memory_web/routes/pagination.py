from __future__ import annotations

import math
from urllib.parse import urlencode


PER_PAGE_OPTIONS = (10, 20, 50, 100)
DEFAULT_PER_PAGE = 20


def normalize_per_page(raw: int | None) -> int:
    try:
        value = int(raw or DEFAULT_PER_PAGE)
    except (TypeError, ValueError):
        return DEFAULT_PER_PAGE
    return value if value in PER_PAGE_OPTIONS else DEFAULT_PER_PAGE


def paginate_items(
    items: list[dict],
    *,
    page: int | None,
    per_page: int,
    base_path: str,
    query_params: dict[str, object],
) -> dict[str, object]:
    total = len(items)
    total_pages = max(1, math.ceil(total / per_page)) if per_page > 0 else 1
    try:
        current_page = int(page or 1)
    except (TypeError, ValueError):
        current_page = 1
    current_page = min(max(current_page, 1), total_pages)

    start = (current_page - 1) * per_page
    end = start + per_page
    page_items = items[start:end]

    def _page_url(target_page: int) -> str:
        params = {k: v for k, v in query_params.items() if v not in (None, "", [], ())}
        params["page"] = target_page
        params["per_page"] = per_page
        return f"{base_path}?{urlencode(params, doseq=True)}"

    window_start = max(1, current_page - 2)
    window_end = min(total_pages, current_page + 2)
    pages = [
        {
            "number": n,
            "url": _page_url(n),
            "current": n == current_page,
        }
        for n in range(window_start, window_end + 1)
    ]

    return {
        "items": page_items,
        "total": total,
        "page": current_page,
        "per_page": per_page,
        "total_pages": total_pages,
        "start_index": start + 1 if total else 0,
        "end_index": min(end, total),
        "page_size": len(page_items),
        "pages": pages,
        "first_url": _page_url(1) if current_page > 1 else None,
        "last_url": _page_url(total_pages) if current_page < total_pages else None,
        "prev_url": _page_url(current_page - 1) if current_page > 1 else None,
        "next_url": _page_url(current_page + 1) if current_page < total_pages else None,
        "has_leading_gap": window_start > 1,
        "has_trailing_gap": window_end < total_pages,
        "show": total_pages > 1,
    }
