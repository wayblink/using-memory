"""Thin adapter that loads memory_tool.py as a library and exposes typed helpers."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import yaml


_MEMORY_LINE_RE = re.compile(
    r"^- \[(?P<tag>[A-Za-z0-9_-]+)(?:\|(?P<date>\d{4}-\d{2}-\d{2}))?\]\s+(?P<text>.*)$"
)
_PREF_LINE_RE = re.compile(
    r"^- \[(?P<date>\d{4}-\d{2}-\d{2})\]\s+(?P<text>.+)$"
)


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
    """Single entry point used by FastAPI routes.

    The default adapter (``namespace_override=None``) reads and writes against
    the configured primary root + namespace from ``~/.skills/using-memory/config.yaml``.

    A second adapter constructed via ``for_namespace("other-ns")`` reads from a
    sibling namespace under the same path. It is **read-only**: writes raise
    ``MemoryToolError``. The do_* read paths see the alternate namespace via a
    lazily-materialized temp config file whose ``memory_roots[*].namespace`` is
    rewritten — no monkeypatching of ``memory_tool`` needed.
    """

    def __init__(
        self,
        config_path: str | None = None,
        *,
        namespace_override: str | None = None,
    ) -> None:
        self.config_path = config_path
        self.namespace_override = namespace_override
        self._mt = memory_tool()
        self._override_config_path: str | None = None
        self._cached_namespace: str | None = None

    # -- namespace plumbing --------------------------------------------------

    @property
    def writable(self) -> bool:
        """True only on the default adapter. Alternate namespaces are read-only."""
        return self.namespace_override is None

    @property
    def namespace(self) -> str:
        """The active namespace name. Resolves from config when no override is set."""
        if self.namespace_override:
            return self.namespace_override
        if self._cached_namespace is None:
            self._cached_namespace = self._resolve_default_namespace()
        return self._cached_namespace

    def _resolve_default_namespace(self) -> str:
        mt = self._mt
        config = mt.load_config(
            Path(self.config_path) if self.config_path else None,
            os.environ.get("USING_MEMORY_CONFIG"),
        )
        if not config:
            return "main"
        primary_list, _ = mt.collect_roots(config)
        if not primary_list:
            return "main"
        return mt.namespace_from_root(primary_list[0])

    def _effective_config_path(self) -> str | None:
        """Return the config path to hand to memory_tool.do_*.

        Default adapter: returns self.config_path unchanged. Alternate-namespace
        adapter: writes a temp config (once) with ``namespace`` rewritten on
        every root. ``writable`` is left untouched because several read-only
        do_* paths (do_status, do_maintain --distill) call
        ``load_primary_for_write`` internally and require ``writable: true``
        on the primary root even though they don't actually mutate state.
        Write-gating happens one layer up via ``_require_writable()``.
        Cached on the instance; the file lives for the process lifetime.
        """
        if self.namespace_override is None:
            return self.config_path
        if self._override_config_path is not None:
            return self._override_config_path

        mt = self._mt
        base = mt.load_config(
            Path(self.config_path) if self.config_path else None,
            os.environ.get("USING_MEMORY_CONFIG"),
        )
        # Strip internal fields memory_tool stamps onto the loaded dict before
        # writing back out so yaml.safe_dump doesn't reject them.
        base = {k: v for k, v in base.items() if not k.startswith("_")}
        roots = base.get("memory_roots") or []
        for root in roots:
            if isinstance(root, dict):
                root["namespace"] = self.namespace_override
        fd, path = tempfile.mkstemp(
            prefix=f"memory-web-ns-{self.namespace_override}-",
            suffix=".yaml",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                yaml.safe_dump(base, fp, sort_keys=False, allow_unicode=True)
        except Exception:
            os.unlink(path)
            raise
        self._override_config_path = path
        return path

    def _ns(self, **extra: Any) -> SimpleNamespace:
        return _args(config=self._effective_config_path(), **extra)

    def _require_writable(self) -> None:
        if not self.writable:
            raise MemoryToolError(
                f"namespace '{self.namespace}' is read-only in the web UI; "
                "switch to the default namespace to make changes"
            )

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
        cwd: str | None = None,
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
            cwd=cwd,
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

    def maintain(self) -> dict:
        """Run the full maintain audit (no --distill, no --promote).

        Returns the structured report (stale files, corrupt jsonl lines, doc
        index repairs). Requires the default writable namespace because
        do_maintain calls load_primary_for_write internally.
        """
        self._require_writable()
        ns = self._ns(
            distill=False,
            promote=None,
            min_entries=3,
            min_days=3,
            json=True,
        )
        return self._call_capturing_exits(self._mt.do_maintain, ns)

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

    def namespace_file_path(self, relative: str) -> Path | None:
        """Return a safe absolute path for a namespace-scoped file."""
        root = self.primary_root()
        if root is None:
            return None
        rel_path = Path(relative)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            return None
        path = (root / rel_path).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            return None
        if not path.exists() or not path.is_file():
            return None
        return path

    def resolve_doc_path(self, slug: str) -> Path | None:
        root = self.primary_root()
        if root is None:
            return None
        docs_dir = root / "docs"
        if not docs_dir.exists():
            return None

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
        docs_root = docs_dir.resolve()
        for ext in exts_to_try:
            candidate = (docs_dir / f"{bare}{ext}").resolve()
            try:
                candidate.relative_to(docs_root)
            except ValueError:
                continue
            if candidate.exists() and candidate.is_file():
                return candidate
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
        self._require_writable()
        when_str = when or date.today().isoformat()
        ns = self._ns(date=when_str, tag=tag, text=text, json=True)
        return self._call_capturing_exits(self._mt.do_write_memory, ns)

    def write_preference(self, *, when: str | None, text: str) -> dict:
        self._require_writable()
        when_str = when or date.today().isoformat()
        ns = self._ns(date=when_str, text=text, json=True)
        return self._call_capturing_exits(self._mt.do_write_preference, ns)

    def upsert_doc(
        self,
        *,
        doc: str,
        text: str,
        title: str | None = None,
        doc_type: str | None = None,
        created: str | None = None,
        modified: str | None = None,
        projects: list[str] | None = None,
        doc_tags: list[str] | None = None,
        summary: str | None = None,
        link_logs: list[str] | None = None,
    ) -> dict:
        self._require_writable()
        ns = self._ns(
            doc=doc,
            text=text,
            text_stdin=False,
            title=title,
            doc_type=doc_type,
            created=created,
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
        eff = self._effective_config_path()
        config = mt.load_config(
            Path(eff) if eff else None,
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
    # memory_tool's index.json tracks any extension in SUPPORTED_DOC_EXTS
    # (md/html/htm/txt). The web UI lists every doc in docs/ regardless of
    # whether it's in the index, then renders+edits the supported formats.
    # Slug = rel path under docs/ without the extension; the index is keyed
    # by full rel path (including extension) so two files sharing a stem
    # (foo.md and foo.html) get distinct entries.

    _DOC_EXTS = (".md", ".html", ".htm", ".txt")
    _EDITABLE_DOC_EXTS = frozenset({"md", "html", "htm", "txt"})

    def list_docs(self) -> list[dict]:
        root = self.primary_root()
        if root is None:
            return []
        docs_dir = root / "docs"
        if not docs_dir.exists():
            return []
        index_by_rel: dict[str, dict] = {}
        for e in self.docs_index_entries():
            raw = e.get("path") or ""
            if raw:
                index_by_rel[raw] = e

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
            entry = index_by_rel.get(rel)
            created = None
            modified = None
            if entry:
                modified = entry.get("modified")
                created = entry.get("created") or modified
            items.append({
                "slug": slug,
                "rel": rel,
                "ext": ext,
                "in_index": entry is not None,
                "title": (entry.get("title") if entry else None) or _fallback_title(f),
                "type": (entry.get("type") if entry else None) or _fallback_type(ext),
                "created": created,
                "modified": modified,
                "projects": (entry.get("projects") if entry else None) or [],
                "tags": (entry.get("tags") if entry else None) or [],
                "summary": (entry.get("summary") if entry else None) or "",
                "size": f.stat().st_size,
            })
        return items

    def read_doc(self, slug: str) -> dict | None:
        candidate = self.resolve_doc_path(slug)
        if candidate is None:
            return None

        # Look up the index entry by *full rel path* so .md / .html / .htm /
        # .txt all populate metadata correctly (in_index, title, projects…).
        root = self.primary_root()
        assert root is not None
        docs_dir = root / "docs"
        full_rel = candidate.relative_to(docs_dir.resolve()).as_posix()
        index_entry: dict | None = None
        for e in self.docs_index_entries():
            if (e.get("path") or "") == full_rel:
                index_entry = e
                break
        if index_entry is not None and index_entry.get("modified") and not index_entry.get("created"):
            index_entry = dict(index_entry)
            index_entry["created"] = index_entry["modified"]

        return {
            "slug": full_rel.rsplit(".", 1)[0],
            "ext": candidate.suffix.lower().lstrip("."),
            "content": candidate.read_text(encoding="utf-8"),
            "entry": index_entry,
            "rel": full_rel,
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
        return self._parse_entries("PREFERENCES.md", _PREF_LINE_RE, with_date=True)

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
            groups = m.groupdict()
            entry = {
                "line_no": idx,
                "text": groups["text"],
            }
            if "tag" in groups:
                entry["tag"] = groups["tag"]
            if with_date:
                entry["date"] = groups.get("date") or ""
            entries.append(entry)
        # Show newest first — entries near the bottom of the file are usually
        # the most recently appended.
        entries.reverse()
        return entries

    def update_memory_line(
        self, *, line_no: int, tag: str, when: str | None, text: str
    ) -> None:
        self._require_writable()
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
        self._require_writable()
        self._delete_line("MEMORY.md", line_no, _MEMORY_LINE_RE)

    def update_preference_line(self, *, line_no: int, when: str | None, text: str) -> None:
        self._require_writable()
        when_str = (when or "").strip()
        if not when_str:
            raise MemoryToolError("date must not be empty")
        try:
            date.fromisoformat(when_str)
        except ValueError:
            raise MemoryToolError(f"invalid date: {when_str!r}") from None
        text = text.strip()
        if not text:
            raise MemoryToolError("text must not be empty")
        new_line = f"- [{when_str}] {text}"
        self._replace_line("PREFERENCES.md", line_no, new_line, _PREF_LINE_RE)

    def delete_preference_line(self, *, line_no: int) -> None:
        self._require_writable()
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
    suffix = path.suffix.lower()
    if suffix == ".md":
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[:40]:
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
        except OSError:
            pass
        return path.stem
    if suffix in (".html", ".htm"):
        try:
            import re
            text = path.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"<title>([^<]+)</title>", text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        except OSError:
            pass
        return path.stem
    if suffix == ".txt":
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[:40]:
                stripped = line.strip()
                if stripped:
                    return stripped[:200]
        except OSError:
            pass
        return path.stem
    return path.name


def _fallback_type(ext: str) -> str:
    if ext == "md":
        return "markdown"
    if ext in ("html", "htm"):
        return "html"
    if ext == "txt":
        return "text"
    return ext or "doc"


# --- Namespace discovery + registry ----------------------------------------
#
# The configured memory_root holds one or more sibling namespace directories
# (e.g. /Users/foo/.memories/{main,step-ws}). The web UI lets the user browse
# any of them; the default — read from config — is writable, the rest are not.


_NAMESPACE_MARKERS = ("MEMORY.md", "PREFERENCES.md", "log", "docs")


def _looks_like_namespace_dir(p: Path) -> bool:
    if not p.is_dir() or p.name.startswith("."):
        return False
    for marker in _NAMESPACE_MARKERS:
        if (p / marker).exists():
            return True
    return False


def list_namespaces(default_adapter: MemoryAdapter) -> list[dict]:
    """Discover sibling namespaces under each configured memory root.

    Returns a list of ``{"name", "path", "is_default"}`` dicts, with the
    default namespace first. Always includes the default; empty list only if
    no config is loaded.
    """
    mt = default_adapter._mt
    config = mt.load_config(
        Path(default_adapter.config_path) if default_adapter.config_path else None,
        os.environ.get("USING_MEMORY_CONFIG"),
    )
    if not config:
        return []
    primary_list, _ = mt.collect_roots(config)
    if not primary_list:
        return []

    default_ns = default_adapter.namespace
    seen: dict[str, dict] = {}
    for root_cfg in primary_list:
        raw_path = root_cfg.get("path", "")
        if not raw_path:
            continue
        base = mt.expand_path(raw_path)
        if not base.exists() or not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not _looks_like_namespace_dir(child):
                continue
            name = child.name
            if name in seen:
                continue
            seen[name] = {
                "name": name,
                "path": str(child),
                "is_default": name == default_ns,
            }

    # Always surface the default even if its directory layout doesn't match
    # the marker heuristic (defensive — should never happen for a real repo).
    if default_ns not in seen:
        seen[default_ns] = {"name": default_ns, "path": "", "is_default": True}

    ordered = [seen[default_ns]] + [
        v for k, v in seen.items() if k != default_ns
    ]
    return ordered


class NamespaceRegistry:
    """Caches one MemoryAdapter per namespace.

    The default adapter is the writable one constructed at app startup. All
    others are constructed lazily with ``namespace_override`` set and a
    rewritten temp config that pins ``writable: false`` for safety.
    """

    def __init__(self, default_adapter: MemoryAdapter) -> None:
        self._default = default_adapter
        self._default_namespace = default_adapter.namespace
        self._others: dict[str, MemoryAdapter] = {}

    @property
    def default_namespace(self) -> str:
        return self._default_namespace

    @property
    def default(self) -> MemoryAdapter:
        return self._default

    def available(self) -> list[dict]:
        return list_namespaces(self._default)

    def resolve(self, name: str | None) -> MemoryAdapter:
        if not name or name == self._default_namespace:
            return self._default
        # Reject anything that isn't a real sibling — the picker only shows
        # discovered names, so this guards against tampered cookies.
        valid = {row["name"] for row in self.available()}
        if name not in valid:
            return self._default
        adapter = self._others.get(name)
        if adapter is None:
            adapter = MemoryAdapter(
                config_path=self._default.config_path,
                namespace_override=name,
            )
            self._others[name] = adapter
        return adapter
