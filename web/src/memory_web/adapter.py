"""Thin adapter that loads memory_tool.py as a library and exposes typed helpers."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any


_MEMORY_LINE_RE = re.compile(
    r"^- \[(?P<tag>[A-Za-z0-9_-]+)(?:\|(?P<date>\d{4}-\d{2}-\d{2}))?\]\s+(?P<text>.*)$"
)
_PREF_LINE_RE = re.compile(r"^- \[(?P<tag>[A-Za-z0-9_-]+)\]\s+(?P<text>.*)$")


_MEMORY_TOOL: ModuleType | None = None


class MemoryToolError(RuntimeError):
    """Raised when memory_tool's do_* function would have sys.exit()'d.

    The original stderr message is preserved as the exception message so
    routes can surface it back to the user.
    """


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[3]


def memory_tool() -> ModuleType:
    global _MEMORY_TOOL
    if _MEMORY_TOOL is not None:
        return _MEMORY_TOOL
    mt_path = _skill_root() / "scripts" / "memory_tool.py"
    if not mt_path.exists():
        raise RuntimeError(f"memory_tool.py not found at {mt_path}")
    spec = importlib.util.spec_from_file_location("memory_tool", mt_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MEMORY_TOOL = module
    return module


def _args(**kwargs: Any) -> SimpleNamespace:
    kwargs.setdefault("config", None)
    return SimpleNamespace(**kwargs)


class MemoryAdapter:
    """Single entry point used by FastAPI routes."""

    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = config_path
        self._mt = memory_tool()

    def _ns(self, **extra: Any) -> SimpleNamespace:
        return _args(config=self.config_path, **extra)

    def status(self) -> dict:
        return self._mt.do_status(self._ns(json=True))

    def stats(self) -> dict:
        return self._mt.do_stats(self._ns(json=True))

    def load(
        self,
        *,
        date: str | None = None,
        log_from: str | None = None,
        log_to: str | None = None,
        log_days: int | None = None,
        log_query: str | None = None,
        projects: list[str] | None = None,
        topics: list[str] | None = None,
        doc: str | None = None,
        doc_type: str | None = None,
        doc_tags: list[str] | None = None,
        doc_query: str | None = None,
        anatomy: bool = False,
        cwd: str | None = None,
        anatomy_max_tokens: int | None = None,
    ) -> dict:
        ns = self._ns(
            date=date,
            json=True,
            log_from=log_from,
            log_to=log_to,
            log_days=log_days,
            log_query=log_query,
            project=projects or [],
            topic=topics or [],
            doc=doc,
            doc_type=doc_type,
            doc_tag=doc_tags or [],
            doc_query=doc_query,
            anatomy=anatomy,
            cwd=cwd,
            anatomy_max_tokens=anatomy_max_tokens,
        )
        return self._mt.do_load(ns)

    def search(
        self,
        query: str,
        *,
        no_docs: bool = False,
        no_memory: bool = False,
        no_log: bool = False,
        log_days: int = 30,
        projects: list[str] | None = None,
        topics: list[str] | None = None,
    ) -> dict:
        ns = self._ns(
            query=query,
            json=True,
            no_docs=no_docs,
            no_memory=no_memory,
            no_log=no_log,
            log_days=log_days,
            project=projects or [],
            topic=topics or [],
        )
        return self._mt.do_search(ns)

    def anatomy_list(self) -> dict:
        return self._mt.do_anatomy_list(self._ns(json=True))

    def distill_candidates(self, *, min_entries: int = 3, min_days: int = 3) -> dict:
        """Read-only distillation bucket analysis.

        Calls memory_tool.do_maintain with --distill, which fast-paths past
        the heavy audit. Safe to call per-dashboard-render — no writes.
        """
        ns = self._ns(
            distill=True,
            promote=None,
            min_entries=min_entries,
            min_days=min_days,
            json=True,
        )
        return self._mt.do_maintain(ns)

    def anatomy_show(self, slug: str) -> dict | None:
        """Return the structured anatomy JSON for one project.

        memory_tool.do_anatomy_show returns the rendered markdown text only
        (slug / md_path / content), which is fine for SessionStart attach but
        useless for the web UI's file table. We read the .json source of
        truth directly so routes can render rows with desc / kind / tokens.
        """
        root = self.primary_root()
        if root is None:
            return None
        json_path = root / "anatomy" / f"{slug}.json"
        if not json_path.exists():
            return None
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    # --- Write operations ---------------------------------------------------
    #
    # memory_tool.do_* functions call sys.exit(2) on validation failures and
    # write the error message to stderr. We capture both so HTTP routes can
    # surface a 400 with the original message instead of crashing the worker.

    def _call_capturing_exits(self, fn, args: SimpleNamespace) -> dict:
        buf = io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                return fn(args)
        except SystemExit as exc:
            msg = buf.getvalue().strip() or f"memory_tool exited with code {exc.code}"
            raise MemoryToolError(msg) from None

    _MEMORY_TAGS = ("fact", "decision", "lesson")

    def write_memory(self, *, when: str | None, tag: str, text: str) -> dict:
        when_str = when or date.today().isoformat()
        ns = self._ns(date=when_str, tag=tag, text=text, json=True)
        return self._call_capturing_exits(self._mt.do_write_memory, ns)

    def write_preference(self, *, text: str) -> dict:
        ns = self._ns(text=text, json=True)
        return self._call_capturing_exits(self._mt.do_write_preference, ns)

    def upsert_doc(
        self,
        *,
        doc: str,
        text: str,
        title: str | None = None,
        doc_type: str | None = None,
        modified: str | None = None,
        projects: list[str] | None = None,
        doc_tags: list[str] | None = None,
        summary: str | None = None,
        link_logs: list[str] | None = None,
    ) -> dict:
        ns = self._ns(
            doc=doc,
            text=text,
            text_stdin=False,
            title=title,
            doc_type=doc_type,
            modified=modified,
            project=projects or None,
            doc_tag=doc_tags or None,
            summary=summary,
            link_log=link_logs or None,
            json=True,
        )
        return self._call_capturing_exits(self._mt.do_upsert_doc, ns)

    # --- structural helpers used by routes for richer rendering -------------

    def primary_root(self) -> Path | None:
        """Resolve the primary repo's namespace-scoped root directory."""
        mt = self._mt
        config = mt.load_config(
            Path(self.config_path) if self.config_path else None,
            os.environ.get("USING_MEMORY_CONFIG"),
        )
        if not config:
            return None
        primary_list, _ = mt.collect_roots(config)
        if not primary_list:
            return None
        root_cfg = primary_list[0]
        raw_path = root_cfg.get("path", "")
        if not raw_path:
            return None
        r_path = mt.expand_path(raw_path)
        return mt.namespace_root(r_path, mt.namespace_from_root(root_cfg))

    def docs_index_entries(self) -> list[dict]:
        root = self.primary_root()
        if root is None:
            return []
        index_path = root / "docs" / "index.json"
        if not index_path.exists():
            return []
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return self._mt.normalize_doc_index(raw)

    # --- Filesystem-aware docs listing ---------------------------------------
    #
    # memory_tool's index.json only tracks .md files (the skill's curated set).
    # The web UI also lists raw .html and .md files that exist on disk but
    # aren't registered, and renders both formats. Slug = path under docs/
    # without the extension. Subdirectories are allowed.

    _DOC_EXTS = (".md", ".html", ".htm")

    def list_docs(self) -> list[dict]:
        root = self.primary_root()
        if root is None:
            return []
        docs_dir = root / "docs"
        if not docs_dir.exists():
            return []
        index_by_slug: dict[str, dict] = {}
        for e in self.docs_index_entries():
            raw = e.get("path") or ""
            slug = raw.removesuffix(".md")
            if slug:
                index_by_slug[slug] = e

        items: list[dict] = []
        for f in sorted(docs_dir.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix.lower() not in self._DOC_EXTS:
                continue
            if f.name.startswith("."):
                continue
            rel = f.relative_to(docs_dir).as_posix()
            slug = rel.rsplit(".", 1)[0]
            ext = f.suffix.lower().lstrip(".")
            entry = index_by_slug.get(slug)
            items.append({
                "slug": slug,
                "rel": rel,
                "ext": "md" if ext == "md" else "html",
                "in_index": entry is not None,
                "title": (entry.get("title") if entry else None) or _fallback_title(f),
                "type": (entry.get("type") if entry else None) or ("markdown" if ext == "md" else "html"),
                "modified": (entry.get("modified") if entry else None),
                "projects": (entry.get("projects") if entry else None) or [],
                "tags": (entry.get("tags") if entry else None) or [],
                "summary": (entry.get("summary") if entry else None) or "",
                "size": f.stat().st_size,
            })
        return items

    def read_doc(self, slug: str) -> dict | None:
        root = self.primary_root()
        if root is None:
            return None
        docs_dir = root / "docs"
        if not docs_dir.exists():
            return None

        # If the URL carried an explicit extension, look up that file only —
        # otherwise an HTML doc with a same-named .md sibling would silently
        # resolve to the .md. When no extension is given, fall back to the
        # historic resolution order (md → html → htm) so legacy slug-only
        # links (search hits, /docs/save redirect, edit links) still work.
        explicit_ext: str | None = None
        bare = slug
        for ext in self._DOC_EXTS:
            if slug.lower().endswith(ext):
                explicit_ext = ext
                bare = slug[: -len(ext)]
                break

        if bare.startswith("/") or ".." in Path(bare).parts:
            return None

        exts_to_try: tuple[str, ...] = (explicit_ext,) if explicit_ext else self._DOC_EXTS

        candidate: Path | None = None
        ext_used: str | None = None
        for ext in exts_to_try:
            p = (docs_dir / f"{bare}{ext}").resolve()
            try:
                p.relative_to(docs_dir.resolve())
            except ValueError:
                continue
            if p.exists() and p.is_file():
                candidate = p
                ext_used = ext.lstrip(".")
                break

        if candidate is None:
            return None

        index_entry: dict | None = None
        if ext_used == "md":
            for e in self.docs_index_entries():
                if (e.get("path") or "").removesuffix(".md") == bare:
                    index_entry = e
                    break

        return {
            "slug": bare,
            "ext": "md" if ext_used == "md" else "html",
            "content": candidate.read_text(encoding="utf-8"),
            "entry": index_entry,
            "rel": candidate.relative_to(docs_dir).as_posix(),
            "in_index": index_entry is not None,
        }

    def read_text_file(self, relative: str) -> str | None:
        root = self.primary_root()
        if root is None:
            return None
        path = root / relative
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    # --- MEMORY.md / PREFERENCES.md card helpers ---------------------------

    def list_memory_entries(self) -> list[dict]:
        """Parse MEMORY.md into per-entry cards keyed by 1-based line number.

        Lines that don't match the bullet pattern (headers, blank lines, free
        prose) are kept out of the cards list so the UI shows only editable
        entries. The line_no on each card refers to the canonical position in
        the original file — used by update/delete to locate the row safely.
        """
        return self._parse_entries("MEMORY.md", _MEMORY_LINE_RE, with_date=True)

    def list_preference_entries(self) -> list[dict]:
        return self._parse_entries("PREFERENCES.md", _PREF_LINE_RE, with_date=False)

    def _parse_entries(
        self, relative: str, pattern: re.Pattern[str], *, with_date: bool
    ) -> list[dict]:
        content = self.read_text_file(relative)
        if not content:
            return []
        entries: list[dict] = []
        for idx, line in enumerate(content.splitlines(), start=1):
            m = pattern.match(line.rstrip("\r"))
            if not m:
                continue
            entry = {
                "line_no": idx,
                "tag": m.group("tag"),
                "text": m.group("text"),
            }
            if with_date:
                entry["date"] = m.group("date") or ""
            entries.append(entry)
        # Show newest first — entries near the bottom of the file are usually
        # the most recently appended.
        entries.reverse()
        return entries

    def update_memory_line(
        self, *, line_no: int, tag: str, when: str | None, text: str
    ) -> None:
        if tag not in self._MEMORY_TAGS:
            raise MemoryToolError(f"tag '{tag}' is not allowed for memory")
        when_str = (when or "").strip()
        if when_str:
            try:
                date.fromisoformat(when_str)
            except ValueError:
                raise MemoryToolError(f"invalid date: {when_str!r}") from None
        text = text.strip()
        if not text:
            raise MemoryToolError("text must not be empty")
        new_line = f"- [{tag}|{when_str}] {text}" if when_str else f"- [{tag}] {text}"
        self._replace_line("MEMORY.md", line_no, new_line, _MEMORY_LINE_RE)

    def delete_memory_line(self, *, line_no: int) -> None:
        self._delete_line("MEMORY.md", line_no, _MEMORY_LINE_RE)

    def update_preference_line(self, *, line_no: int, text: str) -> None:
        text = text.strip()
        if not text:
            raise MemoryToolError("text must not be empty")
        new_line = f"- [pref] {text}"
        self._replace_line("PREFERENCES.md", line_no, new_line, _PREF_LINE_RE)

    def delete_preference_line(self, *, line_no: int) -> None:
        self._delete_line("PREFERENCES.md", line_no, _PREF_LINE_RE)

    def _resolve_path(self, relative: str) -> Path:
        root = self.primary_root()
        if root is None:
            raise MemoryToolError("memory root is not configured")
        path = root / relative
        if not path.exists():
            raise MemoryToolError(f"{relative} does not exist yet")
        return path

    def _replace_line(
        self,
        relative: str,
        line_no: int,
        new_line: str,
        pattern: re.Pattern[str],
    ) -> None:
        path = self._resolve_path(relative)
        mt = self._mt
        with mt.exclusive_file_lock(mt.lock_path_for(path)):
            existing = path.read_text(encoding="utf-8")
            had_trailing_newline = existing.endswith("\n")
            lines = existing.splitlines()
            if line_no < 1 or line_no > len(lines):
                raise MemoryToolError(f"line {line_no} is out of range")
            current = lines[line_no - 1]
            if not pattern.match(current.rstrip("\r")):
                raise MemoryToolError(
                    f"line {line_no} no longer matches an entry; refresh the page"
                )
            lines[line_no - 1] = new_line
            new_content = "\n".join(lines) + ("\n" if had_trailing_newline else "")
            mt.atomic_write_text(path, new_content)

    def _delete_line(
        self, relative: str, line_no: int, pattern: re.Pattern[str]
    ) -> None:
        path = self._resolve_path(relative)
        mt = self._mt
        with mt.exclusive_file_lock(mt.lock_path_for(path)):
            existing = path.read_text(encoding="utf-8")
            had_trailing_newline = existing.endswith("\n")
            lines = existing.splitlines()
            if line_no < 1 or line_no > len(lines):
                raise MemoryToolError(f"line {line_no} is out of range")
            current = lines[line_no - 1]
            if not pattern.match(current.rstrip("\r")):
                raise MemoryToolError(
                    f"line {line_no} no longer matches an entry; refresh the page"
                )
            del lines[line_no - 1]
            new_content = "\n".join(lines)
            if new_content and had_trailing_newline:
                new_content += "\n"
            mt.atomic_write_text(path, new_content)


def _fallback_title(path: Path) -> str:
    """Best-effort title when index.json has no entry."""
    name = path.name
    if path.suffix.lower() == ".md":
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[:40]:
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
        except OSError:
            pass
        return path.stem
    if path.suffix.lower() in (".html", ".htm"):
        try:
            import re
            text = path.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"<title>([^<]+)</title>", text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        except OSError:
            pass
        return path.stem
    return name

