"""Background scheduler that periodically runs `memory_tool.py maintain`.

Configuration:
- Interval comes from env var ``MEMORY_WEB_MAINTAIN_INTERVAL_MIN`` (default 360).
- Setting it to ``0`` disables the scheduler entirely.

Only the default (writable) namespace is maintained; sibling namespaces are
read-only in the web UI.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .adapter import MemoryAdapter, MemoryToolError


ENV_INTERVAL_MIN = "MEMORY_WEB_MAINTAIN_INTERVAL_MIN"
DEFAULT_INTERVAL_MIN = 360


def _local_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _summarize(report: dict[str, Any]) -> dict[str, int]:
    stale = report.get("stale_files") or report.get("stale") or []
    corrupt = report.get("corrupt") or []
    repaired = report.get("repaired_index_entries") or report.get("repaired") or []
    anatomy = report.get("anatomy") or {}
    broken = report.get("broken_log_refs") or anatomy.get("broken_log_refs") or []
    projects = anatomy.get("projects") if isinstance(anatomy, dict) else []
    project_drift = 0
    if isinstance(projects, list):
        for proj in projects:
            if not isinstance(proj, dict):
                continue
            if proj.get("stale_files") or proj.get("new_files"):
                project_drift += 1
    return {
        "stale": len(stale) if isinstance(stale, list) else 0,
        "corrupt": len(corrupt) if isinstance(corrupt, list) else 0,
        "repaired": len(repaired) if isinstance(repaired, list) else 0,
        "broken_log_refs": len(broken) if isinstance(broken, list) else 0,
        "anatomy_projects_with_drift": project_drift,
    }


@dataclass
class MaintenanceState:
    interval_minutes: int = 0
    running: bool = False
    last_run_ts: str | None = None
    last_status: str | None = None  # "ok" | "error" | "skipped"
    last_error: str | None = None
    last_summary: dict[str, int] = field(default_factory=dict)
    runs_total: int = 0
    next_run_ts: str | None = None


class MaintenanceScheduler:
    """Async scheduler bound to a single (writable) MemoryAdapter."""

    def __init__(self, adapter: MemoryAdapter, interval_minutes: int) -> None:
        self.adapter = adapter
        self.state = MaintenanceState(interval_minutes=interval_minutes)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._run_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self.state.interval_minutes > 0

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        self._stop.clear()
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._loop(), name="memory-web-maintenance")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        interval = self.state.interval_minutes * 60
        try:
            while not self._stop.is_set():
                self.state.next_run_ts = _next_iso(interval)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=interval)
                    return  # stop requested
                except asyncio.TimeoutError:
                    pass
                await self.run_once(triggered_by="scheduler")
        except asyncio.CancelledError:
            raise

    async def run_once(self, *, triggered_by: str = "manual") -> dict[str, Any]:
        async with self._run_lock:
            self.state.running = True
            try:
                report = await asyncio.to_thread(self.adapter.maintain)
                self.state.last_status = "ok"
                self.state.last_error = None
                self.state.last_summary = _summarize(report or {})
            except MemoryToolError as exc:
                self.state.last_status = "error"
                self.state.last_error = str(exc)
                self.state.last_summary = {}
                report = {"error": str(exc)}
            except Exception as exc:  # noqa: BLE001 — surface any failure
                self.state.last_status = "error"
                self.state.last_error = f"{type(exc).__name__}: {exc}"
                self.state.last_summary = {}
                report = {"error": self.state.last_error}
            finally:
                self.state.running = False
                self.state.last_run_ts = _local_now_iso()
                self.state.runs_total += 1
                if self.enabled:
                    self.state.next_run_ts = _next_iso(self.state.interval_minutes * 60)
                else:
                    self.state.next_run_ts = None
            return {
                "triggered_by": triggered_by,
                "ts": self.state.last_run_ts,
                "status": self.state.last_status,
                "error": self.state.last_error,
                "summary": self.state.last_summary,
                "report": report,
            }

    def status(self) -> dict[str, Any]:
        s = self.state
        return {
            "enabled": self.enabled,
            "interval_minutes": s.interval_minutes,
            "running": s.running,
            "last_run_ts": s.last_run_ts,
            "last_status": s.last_status,
            "last_error": s.last_error,
            "last_summary": s.last_summary,
            "runs_total": s.runs_total,
            "next_run_ts": s.next_run_ts,
        }


def _next_iso(interval_seconds: float) -> str:
    return (
        datetime.now(timezone.utc)
        + _td(interval_seconds)
    ).astimezone().isoformat(timespec="seconds")


def _td(seconds: float):
    from datetime import timedelta
    return timedelta(seconds=seconds)


def read_interval_from_env() -> int:
    raw = os.environ.get(ENV_INTERVAL_MIN)
    if raw is None or raw == "":
        return DEFAULT_INTERVAL_MIN
    try:
        v = int(raw)
    except ValueError:
        return DEFAULT_INTERVAL_MIN
    return max(0, v)
