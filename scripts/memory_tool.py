#!/usr/bin/env python3
"""using-memory CLI: load and write curated Markdown memory files."""

import argparse
import contextlib
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import yaml
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback for portable installs.
    fcntl = None

# Ensure the sibling package ``memory_lib`` is importable no matter how this
# file is loaded: as a script (scripts/ is already sys.path[0]) or dynamically
# via importlib.spec_from_file_location (e.g. the web adapter), which does not
# add the containing directory to sys.path.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from memory_lib.core import (
    DEFAULT_CONFIG_PATH, DOC_ENTRY_REQUIRED_FIELDS, DEFAULT_NAMESPACE,
    SUPPORTED_DOC_EXTS, DEFAULT_DOC_EXT, SETUP_HINT,
    no_memory_config, load_config, collect_roots, root_priority, expand_path,
    namespace_from_root, namespace_root, read_source, validate_single_primary,
    normalize_index_doc_path, read_json_source, validate_doc_entry,
    validate_doc_index, sha256_file, lock_path_for, exclusive_file_lock,
    atomic_write_text, append_markdown_entry, looks_like_memory_namespace_root,
    validate_primary_root_for_write, load_primary_for_write, iter_log_entries,
)

LOG_TAGS = {
    "operation",
    "progress",
    "milestone",
    "state",
    "result",
    "output",
    "verification",
    "issue",
    "debug",
    "error",
    "fix",
    "decision",
    "analysis",
    "consideration",
    "build",
    "deploy",
    "release",
    "commit",
    "test",
    "benchmark",
    "lesson",
    "fact",
    "pattern",
    "insight",
    "note",
    "context",
}
















def parse_iso_date(raw: str | None, label: str) -> date:
    try:
        return date.fromisoformat(raw or "")
    except (TypeError, ValueError):
        sys.stderr.write(f"invalid {label}; expected YYYY-MM-DD\n")
        sys.exit(2)






def validate_doc_name(doc: str | None) -> str | None:
    if doc is None:
        return None
    if not doc or doc.startswith("/") or "\\" in doc or doc in {".", ".."}:
        sys.stderr.write("invalid doc name\n")
        sys.exit(2)
    doc_path = Path(doc)
    if ".." in doc_path.parts:
        sys.stderr.write("invalid doc name\n")
        sys.exit(2)
    if doc_path.suffix:
        if doc_path.suffix.lower() not in SUPPORTED_DOC_EXTS:
            sys.stderr.write("invalid doc name\n")
            sys.exit(2)
        return doc
    return f"{doc}{DEFAULT_DOC_EXT}"




def strip_doc_ext(value: str) -> str:
    """Return ``value`` with a single trailing supported doc extension removed.

    Used by the ``--doc`` selector to match an index entry whose ``path`` is
    e.g. ``foo.md`` against a user-supplied slug ``foo`` (with or without
    extension). Unknown / missing extensions are returned unchanged.
    """
    if not value:
        return value
    suffix = Path(value).suffix.lower()
    if suffix in SUPPORTED_DOC_EXTS:
        return value[: -len(suffix)]
    return value




def normalize_doc_index(raw_index) -> list[dict]:
    if isinstance(raw_index, dict):
        raw_docs = raw_index.get("documents", [])
    elif isinstance(raw_index, list):
        raw_docs = raw_index
    else:
        return []
    return [entry for entry in raw_docs if isinstance(entry, dict)]






def doc_entry_text(entry: dict) -> str:
    values = []
    for key in ("title", "type", "created", "modified", "path", "summary"):
        value = entry.get(key)
        if value:
            values.append(str(value))
    for key in ("tags", "projects", "aliases"):
        value = entry.get(key, [])
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value:
            values.append(str(value))
    return " ".join(values).lower()


def doc_entry_matches(entry: dict, selectors: dict) -> bool:
    doc_name = selectors.get("doc")
    doc_type = selectors.get("doc_type")
    doc_tags = selectors.get("doc_tags", [])
    projects = selectors.get("projects", [])
    query = selectors.get("query")

    if doc_name:
        # Match either form: with extension (``foo.md`` against entry.path
        # ``foo.md``) or without (``foo`` matches both ``foo.md`` and the
        # ext-stripped path of any other supported format).
        normalized_input = strip_doc_ext(doc_name)
        candidates = {
            doc_name,
            normalized_input,
            str(entry.get("path", "")),
            strip_doc_ext(str(entry.get("path", ""))),
            str(entry.get("id", "")),
            strip_doc_ext(str(entry.get("id", ""))),
            str(entry.get("title", "")),
            strip_doc_ext(str(entry.get("title", ""))),
        }
        aliases = entry.get("aliases", [])
        if isinstance(aliases, list):
            for alias in aliases:
                candidates.add(str(alias))
                candidates.add(strip_doc_ext(str(alias)))
        candidates.discard("")
        if doc_name not in candidates and normalized_input not in candidates:
            return False

    if doc_type and str(entry.get("type", "")).lower() != doc_type.lower():
        return False

    entry_tags = entry.get("tags", [])
    if isinstance(entry_tags, str):
        entry_tags = [entry_tags]
    normalized_tags = {str(tag).lower() for tag in entry_tags}
    if doc_tags and not all(tag.lower() in normalized_tags for tag in doc_tags):
        return False

    entry_projects = entry.get("projects", [])
    if isinstance(entry_projects, str):
        entry_projects = [entry_projects]
    normalized_projects = {str(project).lower() for project in entry_projects}
    if projects and not all(project.lower() in normalized_projects for project in projects):
        return False

    if query and query.lower() not in doc_entry_text(entry):
        return False

    return True


def doc_path_from_entry(root: Path, entry: dict) -> Path | None:
    rel = entry.get("path") or entry.get("id")
    if not rel:
        return None
    validated = normalize_index_doc_path(str(rel))
    if validated is None:
        return None
    return root / "docs" / validated












_ANATOMY_REF_RE = re.compile(r"\[\[anatomy:([a-z0-9][a-z0-9._-]{0,63})/([^\]]+)\]\]")

# Log backlink syntax: [[log:YYYY-MM-DD#L<n>]] where n is 1-based jsonl line number.
# Used by docs to cite the source log entries they were distilled from. The
# distillation pipeline relies on this to filter out log entries that have
# already been promoted into a doc.
_LOG_REF_RE = re.compile(r"\[\[log:(\d{4}-\d{2}-\d{2})#L(\d+)\]\]")
LOG_BACKLINK_HEADING = "## Related log entries"


def format_log_backlink(date_str: str, line_no: int) -> str:
    """Return the canonical [[log:YYYY-MM-DD#L<n>]] link string."""
    if not _LOG_REF_RE.fullmatch(f"[[log:{date_str}#L{line_no}]]"):
        raise ValueError(f"invalid log backlink: date={date_str!r} line={line_no!r}")
    return f"[[log:{date_str}#L{line_no}]]"


def parse_log_backlink(raw: str) -> tuple[str, int] | None:
    """Parse a single ``[[log:YYYY-MM-DD#L<n>]]`` token. None if invalid."""
    m = _LOG_REF_RE.fullmatch(raw.strip())
    if not m:
        return None
    return m.group(1), int(m.group(2))


def extract_log_backlinks_from_text(text: str) -> set[tuple[str, int]]:
    """Return all ``(date, line_no)`` tuples cited via [[log:...]] in ``text``."""
    if not text:
        return set()
    return {(m.group(1), int(m.group(2))) for m in _LOG_REF_RE.finditer(text)}


def merge_log_backlinks_section(existing_text: str, new_links: list[str]) -> str:
    """Return ``existing_text`` with a ``## Related log entries`` section that
    includes ``new_links`` merged with any links already present, deduped and
    sorted by (date, line_no). The section is appended at the end of the doc;
    if it already exists, the existing section is replaced in place.

    ``new_links`` items must be canonical ``[[log:YYYY-MM-DD#L<n>]]`` strings.
    Invalid entries are dropped silently — caller is expected to use
    :func:`format_log_backlink` to construct them.
    """
    valid_new: set[tuple[str, int]] = set()
    for link in new_links or []:
        parsed = parse_log_backlink(link)
        if parsed is not None:
            valid_new.add(parsed)

    body = existing_text or ""
    heading_idx = body.find(LOG_BACKLINK_HEADING)
    if heading_idx == -1:
        prefix = body
        existing_links: set[tuple[str, int]] = set()
    else:
        prefix = body[:heading_idx].rstrip() + "\n"
        existing_links = extract_log_backlinks_from_text(body[heading_idx:])

    if not valid_new and not existing_links:
        return body  # nothing to add and no existing section: leave alone

    merged = sorted(existing_links | valid_new)
    section_lines = [LOG_BACKLINK_HEADING, ""]
    section_lines.extend(f"- {format_log_backlink(d, n)}" for d, n in merged)
    section = "\n".join(section_lines) + "\n"

    if not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return prefix + section


def collect_promoted_log_refs(scoped_root: Path) -> set[tuple[str, int]]:
    """Walk every ``<namespace>/docs/*.{md,html,htm,txt}`` file and return every
    ``(date, line_no)`` cited via ``[[log:YYYY-MM-DD#L<n>]]``. The distillation
    pipeline uses this set to skip log entries that have already been promoted
    into a doc.

    Backlinks may live anywhere in the doc body (not only inside the
    Related-log-entries section), so we scan the whole document.
    """
    docs_dir = scoped_root / "docs"
    refs: set[tuple[str, int]] = set()
    if not docs_dir.is_dir():
        return refs
    seen: set[Path] = set()
    for ext in SUPPORTED_DOC_EXTS:
        for path in docs_dir.rglob(f"*{ext}"):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            refs |= extract_log_backlinks_from_text(text)
    return refs



def _anatomy_link_snapshots_for_entry(scoped_root: Path, text: str) -> list[dict]:
    """Parse `[[anatomy:slug/path]]` refs from a log entry's text and return
    matching anatomy snapshots: ``{slug, rel, desc, tokens_est, kind}``.

    Missing slugs/files are silently dropped — anatomy can drift behind log
    references and we'd rather show the surviving subset than fail.
    """
    out: list[dict] = []
    if not text:
        return out
    seen: set[tuple[str, str]] = set()
    cache: dict[str, dict] = {}
    for match in _ANATOMY_REF_RE.finditer(text):
        slug = match.group(1)
        rel = match.group(2).strip()
        key = (slug, rel)
        if key in seen:
            continue
        seen.add(key)
        doc = cache.get(slug)
        if doc is None:
            doc = _anatomy_load_doc(scoped_root, slug) or {}
            cache[slug] = doc
        files = doc.get("files", {}) if isinstance(doc, dict) else {}
        entry = files.get(rel)
        if not entry:
            continue
        out.append({
            "slug": slug,
            "rel": rel,
            "desc": entry.get("desc", ""),
            "tokens_est": entry.get("tokens_est", 0),
            "kind": entry.get("kind", ""),
        })
    return out


def _anatomy_refs_for_files(scoped_root: Path, files: list[str]) -> list[str]:
    """For each file in ``files`` that lives inside a registered anatomy project,
    produce a `[[anatomy:<slug>/<relpath>]]` link string. Deduped, deterministic
    order. Returns [] when no file matched or no projects are registered.
    """
    if not files:
        return []
    index = _anatomy_load_index(scoped_root)
    if not index:
        return []
    resolved: list[tuple[Path, str]] = []
    for slug, info in index.items():
        if not isinstance(info, dict):
            continue
        raw = info.get("root")
        if not raw:
            continue
        try:
            resolved.append((Path(raw).expanduser().resolve(), slug))
        except OSError:
            continue
    if not resolved:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw_path in files:
        if not raw_path:
            continue
        try:
            fp = Path(raw_path).expanduser().resolve()
        except OSError:
            continue
        best_slug: str | None = None
        best_root: Path | None = None
        best_len = -1
        for root, slug in resolved:
            try:
                fp.relative_to(root)
            except ValueError:
                continue
            length = len(str(root))
            if length > best_len:
                best_slug = slug
                best_root = root
                best_len = length
        if best_slug is None or best_root is None:
            continue
        try:
            rel = fp.relative_to(best_root).as_posix()
        except ValueError:
            continue
        ref = f"[[anatomy:{best_slug}/{rel}]]"
        if ref in seen:
            continue
        seen.add(ref)
        out.append(ref)
    return out


def append_log_entry(
    root: Path,
    namespace: str,
    when: date,
    tag: str,
    text: str,
    level: str = "detail",
    confidence: int | None = None,
    source: str | None = None,
    files: list[str] | None = None,
    project: str | None = None,
    topic: str | None = None,
) -> Path:
    """Append one entry to the primary repo's log note (JSONL only).

    Side-effect: if ``files`` are inside a registered anatomy project root,
    appends `[[anatomy:<slug>/<rel>]]` link(s) to ``text`` so search can
    cross-reference the snapshot description later.
    """
    jsonl_target = namespace_root(root, namespace) / "log" / f"{when:%Y-%m-%d}.jsonl"
    final_text = text
    refs = _anatomy_refs_for_files(namespace_root(root, namespace), files or [])
    if refs:
        # Only append refs not already present in the body so manually-authored
        # entries that already cite anatomy don't get duplicate links.
        new_refs = [r for r in refs if r not in final_text]
        if new_refs:
            if final_text and not final_text.endswith("\n"):
                final_text += "\n"
            final_text += "\nAnatomy: " + " ".join(new_refs)
    record = {
        "ts": datetime.now().astimezone().isoformat(),
        "date": when.isoformat(),
        "tag": tag,
        "level": level,
        "source": source or "user",
        "text": final_text,
        "confidence": confidence,
        "files": files or [],
    }
    if project:
        record["project"] = project
    if topic:
        record["topic"] = topic
    jsonl_target.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(lock_path_for(jsonl_target)):
        with jsonl_target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return jsonl_target


def append_memory_entry(root: Path, when: date, tag: str, text: str) -> Path:
    DENIED = {"pref"}
    if tag.lower() in DENIED:
        sys.stderr.write(f"tag '{tag}' is not allowed for write-memory\n")
        sys.exit(2)
    mem_path = root / "MEMORY.md"
    entry = f"- [{tag}|{when:%Y-%m-%d}] {text}\n"
    return append_markdown_entry(mem_path, entry)


def append_preference_entry(root: Path, when: date, text: str) -> Path:
    pref_path = root / "PREFERENCES.md"
    entry = f"- [{when:%Y-%m-%d}] {text}\n"
    with exclusive_file_lock(lock_path_for(pref_path)):
        existing = pref_path.read_text(encoding="utf-8") if pref_path.exists() else ""
        if existing:
            # One blank line between entries — preferences are often multi-paragraph
            # (Why: / How to apply:), so a clear separator improves readability.
            existing = existing.rstrip("\n") + "\n\n"
            atomic_write_text(pref_path, existing + entry)
        else:
            atomic_write_text(pref_path, entry)
    return pref_path






def resolve_primary_file_reference(primary_root: Path, raw_path) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    ref_path = Path(raw_path)
    if ref_path.is_absolute() or ".." in ref_path.parts:
        return None
    try:
        primary_resolved = primary_root.resolve()
        candidate = (primary_resolved / ref_path).resolve()
        candidate.relative_to(primary_resolved)
    except (OSError, ValueError):
        return None
    return candidate




def load_doc_index(index_path: Path) -> dict:
    if not index_path.exists():
        return {"version": 1, "documents": []}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"invalid docs index: {exc.msg}\n")
        sys.exit(2)
    error = validate_doc_index(data)
    if error:
        sys.stderr.write(f"invalid docs index: {error}\n")
        sys.exit(2)
    data.setdefault("version", 1)
    return data


def upsert_doc_index_entry(index_path: Path, entry: dict) -> None:
    index = load_doc_index(index_path)
    index = doc_index_with_entry(index, entry)
    write_doc_index(index_path, index)


def doc_index_with_entry(index: dict, entry: dict) -> dict:
    documents = index["documents"]
    documents = [doc for doc in documents if doc.get("path") != entry["path"]]
    documents.append(entry)
    documents.sort(key=lambda doc: str(doc.get("path", "")))
    index["documents"] = documents
    return index


def write_doc_index(index_path: Path, index: dict) -> None:
    atomic_write_text(index_path, json.dumps(index, ensure_ascii=False, indent=2) + "\n")


_HTML_TITLE_TAG_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
_HTML_H1_TAG_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _slug_to_title(stem: str) -> str:
    base = stem.rsplit("/", 1)[-1]
    return base.replace("-", " ").replace("_", " ").strip().title() or base


def extract_doc_title_from_text(text: str, ext: str) -> str | None:
    """Multi-format doc-title extractor used by ``upsert-doc`` and ``maintain``.

    md/no-ext: first ``# Heading`` line.
    html/htm:  first ``<title>`` then first ``<h1>`` (tags stripped).
    txt:       first non-empty line (capped at 200 chars).
    Returns None when nothing usable was found so the caller can fall back
    to a slug-derived title.
    """
    if not text:
        return None
    suffix = (ext or "").lower()
    if not suffix.startswith("."):
        suffix = f".{suffix}" if suffix else ""
    if suffix in ("", ".md"):
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                candidate = stripped[2:].strip()
                if candidate:
                    return candidate
        return None
    if suffix in (".html", ".htm"):
        m = _HTML_TITLE_TAG_RE.search(text)
        if m and m.group(1).strip():
            return m.group(1).strip()
        m = _HTML_H1_TAG_RE.search(text)
        if m:
            inner = _HTML_TAG_STRIP_RE.sub("", m.group(1)).strip()
            if inner:
                return inner
        return None
    if suffix == ".txt":
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:200]
        return None
    return None


def extract_doc_title_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _slug_to_title(path.stem)
    title = extract_doc_title_from_text(text, suffix)
    if title:
        return title
    return _slug_to_title(path.stem)


# Back-compat aliases — kept for any callers that still import the old names.
def extract_markdown_title(path: Path) -> str:
    return extract_doc_title_from_file(path)


def extract_h1_from_text(text: str) -> str | None:
    """Return the first ``# Heading`` line from a markdown string, or None."""
    return extract_doc_title_from_text(text, ".md")


def doc_index_entry_for_file(docs_dir: Path, doc_path: Path) -> dict:
    rel_path = doc_path.relative_to(docs_dir).as_posix()
    modified = date.fromtimestamp(doc_path.stat().st_mtime).isoformat()
    return {
        "path": rel_path,
        "title": extract_markdown_title(doc_path),
        "type": "wiki",
        "created": modified,
        "modified": modified,
        "projects": [],
        "tags": [],
    }


def maintain_doc_index(primary_root: Path) -> list[dict]:
    docs_dir = primary_root / "docs"
    if not docs_dir.is_dir():
        return []
    index_path = docs_dir / "index.json"
    with exclusive_file_lock(docs_dir / ".docs.lock"):
        index = load_doc_index(index_path)
        indexed_paths = {
            str(entry.get("path", ""))
            for entry in normalize_doc_index(index)
        }
        added = []
        seen: set[Path] = set()
        for ext in SUPPORTED_DOC_EXTS:
            for doc_path in sorted(docs_dir.rglob(f"*{ext}")):
                if not doc_path.is_file() or doc_path in seen:
                    continue
                seen.add(doc_path)
                rel_path = doc_path.relative_to(docs_dir).as_posix()
                if rel_path in indexed_paths:
                    continue
                entry = doc_index_entry_for_file(docs_dir, doc_path)
                error = validate_doc_entry(entry)
                if error:
                    sys.stderr.write(f"invalid generated doc metadata: {error}\n")
                    sys.exit(2)
                index = doc_index_with_entry(index, entry)
                indexed_paths.add(entry["path"])
                added.append({
                    "path": entry["path"],
                    "title": entry["title"],
                    "type": entry["type"],
                })
        if added:
            write_doc_index(index_path, index)
        return added


def date_range(start: date, end: date) -> list[date]:
    if start > end:
        sys.stderr.write("log range start must be before or equal to end\n")
        sys.exit(2)
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def log_dates_for_load(args: argparse.Namespace, target: date, read_today: bool, read_yesterday: bool) -> list[date]:
    has_range = bool(args.log_from or args.log_to)
    has_days = args.log_days is not None
    if has_range and has_days:
        sys.stderr.write("--log-from/--log-to cannot be combined with --log-days\n")
        sys.exit(2)
    if has_range:
        if not args.log_from or not args.log_to:
            sys.stderr.write("--log-from and --log-to must be provided together\n")
            sys.exit(2)
        return date_range(
            parse_iso_date(args.log_from, "--log-from"),
            parse_iso_date(args.log_to, "--log-to"),
        )
    if has_days:
        if args.log_days < 1:
            sys.stderr.write("--log-days must be >= 1\n")
            sys.exit(2)
        start = target - timedelta(days=args.log_days - 1)
        return date_range(start, target)

    dates = []
    if read_today:
        dates.append(target)
    if read_yesterday:
        dates.append(target - timedelta(days=1))
    return dates


def append_log_jsonl_sources(
    sources_list: list,
    log_entries: list,
    warnings: list,
    primary_root: Path,
    primary_namespace: str,
    primary_machine: str,
    dates: list[date],
    query: str | None,
    project_filter: list[str] | None = None,
    topic_filter: list[str] | None = None,
) -> None:
    normalized_query = query.lower() if query else None
    project_set = _normalize_axis_filter(project_filter)
    topic_set = _normalize_axis_filter(topic_filter)
    scoped_root = namespace_root(primary_root, primary_namespace)
    for log_date in dates:
        jsonl_path = scoped_root / "log" / f"{log_date:%Y-%m-%d}.jsonl"
        if not jsonl_path.exists():
            continue
        log_source = read_source(jsonl_path, "log", "primary", primary_machine)
        if not log_source["loaded"]:
            continue
        matched_lines = []
        if log_source["loaded"]:
            for lineno, line in enumerate(log_source["content"].splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    warnings.append(f"invalid log jsonl: {jsonl_path}:{lineno}: {exc.msg}")
                    continue
                text = entry.get("text", "")
                if normalized_query and normalized_query not in str(text).lower():
                    continue
                if project_set is not None:
                    proj = entry.get("project")
                    if not proj or proj.lower() not in project_set:
                        continue
                if topic_set is not None:
                    tp = entry.get("topic")
                    if not tp or tp.lower() not in topic_set:
                        continue
                log_entries.append(entry)
                matched_lines.append(json.dumps(entry, ensure_ascii=False))
        if (normalized_query or project_set or topic_set) and not matched_lines:
            continue
        if normalized_query or project_set or topic_set:
            log_source["content"] = "\n".join(matched_lines) + ("\n" if matched_lines else "")
        sources_list.append(log_source)


def _normalize_axis_filter(values: list[str] | None) -> set[str] | None:
    """Normalize a list of CLI axis filter values to a lowercased set.

    Returns None if no filter (caller treats as wildcard). Returns an empty
    set only if every value was empty after stripping (caller should still
    treat as wildcard, so we return None in that case).
    """
    if not values:
        return None
    out = set()
    for v in values:
        if v is None:
            continue
        s = v.strip().lower()
        if s:
            out.add(s)
    return out or None


def do_load(args: argparse.Namespace) -> dict:
    config = load_config(Path(args.config) if args.config else None, os.environ.get("USING_MEMORY_CONFIG"))
    if not config:
        primary_list = []
        ref_list = []
        roots_exist = False
    else:
        primary_list, ref_list = collect_roots(config)
        validate_single_primary(primary_list, required=False)
        roots_exist = bool(primary_list)
    doc_name = validate_doc_name(args.doc)
    doc_selectors = {
        "doc": doc_name,
        "doc_type": args.doc_type,
        "doc_tags": args.doc_tag or [],
        "projects": args.project or [],
        "query": args.doc_query,
    }
    warnings = list(config.get("_warnings", [])) if isinstance(config, dict) else []
    if not roots_exist:
        warnings.append("config not found or has no memory roots")
    defaults = config.get("defaults", {}) if config else {}
    read_today = defaults.get("read_today", True)
    read_yesterday = defaults.get("read_yesterday", True)
    load_docs = defaults.get("load_docs_on_demand", True)
    target = parse_iso_date(args.date, "--date") if args.date else date.today()
    sources_list = []
    preferences, durable_memory, doc_set = [], [], []
    log_entries = []
    if roots_exist:
        ordered_roots = primary_list + ref_list

        for root_cfg in ordered_roots:
            raw_path = root_cfg.get("path", "")
            r_path = expand_path(raw_path)
            scoped_root = namespace_root(r_path, namespace_from_root(root_cfg))
            role = root_cfg.get("role", "reference")
            machine_id = root_cfg.get("machine_id", "")
            pref_source = read_source(scoped_root / "PREFERENCES.md", "preferences", role, machine_id)
            sources_list.append(pref_source)
            if pref_source["loaded"]:
                preferences.append(pref_source["content"])

        for root_cfg in ordered_roots:
            raw_path = root_cfg.get("path", "")
            r_path = expand_path(raw_path)
            scoped_root = namespace_root(r_path, namespace_from_root(root_cfg))
            role = root_cfg.get("role", "reference")
            machine_id = root_cfg.get("machine_id", "")
            memory_source = read_source(scoped_root / "MEMORY.md", "durable_memory", role, machine_id)
            sources_list.append(memory_source)
            if memory_source["loaded"]:
                durable_memory.append(memory_source["content"])

        if load_docs:
            for root_cfg in ordered_roots:
                r_path = expand_path(root_cfg.get("path", ""))
                scoped_root = namespace_root(r_path, namespace_from_root(root_cfg))
                role = root_cfg.get("role", "reference")
                machine_id = root_cfg.get("machine_id", "")
                index_source = read_json_source(scoped_root / "docs" / "index.json", "docs_index", role, machine_id)
                sources_list.append(index_source)
                if not index_source["loaded"]:
                    continue

                index_entries = normalize_doc_index(index_source.get("json"))
                matched_entries = [
                    entry for entry in index_entries if doc_entry_matches(entry, doc_selectors)
                ]
                should_load_docs = any(
                    [
                        doc_selectors["doc"],
                        doc_selectors["doc_type"],
                        doc_selectors["doc_tags"],
                        doc_selectors["projects"],
                        doc_selectors["query"],
                    ]
                )
                if not should_load_docs:
                    continue

                for entry in matched_entries:
                    doc_path = doc_path_from_entry(scoped_root, entry)
                    if doc_path is None:
                        continue
                    doc_source = read_source(doc_path, "doc", role, machine_id)
                    sources_list.append(doc_source)
                    if doc_source["loaded"]:
                        doc_set.append(
                            {
                                "path": doc_source["path"],
                                "name": strip_doc_ext(str(entry.get("path") or entry.get("id") or "")),
                                "role": role,
                                "machine_id": machine_id,
                                "metadata": entry,
                                "content": doc_source["content"],
                            }
                        )

        primary_cfg = primary_list[0]
        primary_root = expand_path(primary_cfg.get("path", ""))
        primary_namespace = namespace_from_root(primary_cfg)
        primary_machine = primary_cfg.get("machine_id", "")
        log_dates = log_dates_for_load(args, target, read_today, read_yesterday)
        append_log_jsonl_sources(
            sources_list,
            log_entries,
            warnings,
            primary_root,
            primary_namespace,
            primary_machine,
            log_dates,
            args.log_query,
            project_filter=getattr(args, "project", None),
            topic_filter=getattr(args, "topic", None),
        )
    else:
        warnings.append("no primary root configured; read_today and read_yesterday are no-ops")

    anatomy_block: dict | None = None
    if getattr(args, "anatomy", False) and roots_exist:
        cwd_arg = getattr(args, "cwd", None)
        cwd_path = Path(cwd_arg).expanduser() if cwd_arg else Path.cwd()
        primary_cfg = primary_list[0]
        primary_scoped = namespace_root(
            expand_path(primary_cfg.get("path", "")),
            namespace_from_root(primary_cfg),
        )
        max_tokens = int(getattr(args, "anatomy_max_tokens", None) or 2000)
        anatomy_block = _anatomy_attach_for_load(primary_scoped, cwd_path, max_tokens)

    result = {
        "mode": "memory" if roots_exist else "no_memory",
        "write_enabled": roots_exist and primary_list[0].get("writable", False) if roots_exist else False,
        "sources": sources_list,
        "preferences": preferences,
        "durable_memory": durable_memory,
        "log_entries": log_entries,
        "doc_hits": doc_set,
        "warnings": warnings,
    }
    if anatomy_block is not None:
        result["anatomy"] = anatomy_block
    return result


def do_write_log(args: argparse.Namespace) -> dict:
    primary_root, primary_namespace = load_primary_for_write(args)
    when = parse_iso_date(args.date, "--date")
    tag = (args.tag or "").lower()
    if tag not in LOG_TAGS:
        sys.stderr.write(f"invalid tag '{args.tag}'; allowed: {', '.join(sorted(LOG_TAGS))}\n")
        sys.exit(2)
    level = args.level
    confidence = args.confidence if args.confidence else None
    source = args.source if args.source else None
    files = args.files if args.files else []
    project = _normalize_axis_value(getattr(args, "project", None))
    topic = _normalize_axis_value(getattr(args, "topic", None))

    # Auto-routing: when --project / --topic are not given, try to infer them.
    # project: prefer cwd → registered anatomy slug; fall back to first --files entry.
    # topic: keyword scoring on text + tag (only when not explicitly set).
    scoped_root = namespace_root(primary_root, primary_namespace)
    if project is None:
        cwd_arg = getattr(args, "cwd", None)
        candidate_cwd = Path(cwd_arg).expanduser() if cwd_arg else Path.cwd()
        slug, _ = _anatomy_match_cwd(scoped_root, candidate_cwd)
        if slug is None and files:
            for raw in files:
                if not raw:
                    continue
                slug2, _root, _rel = _anatomy_match_file(scoped_root, Path(raw).expanduser())
                if slug2:
                    slug = slug2
                    break
        if slug:
            project = slug
    if topic is None:
        topic = _infer_topic_from_text(args.text, tag)

    target = append_log_entry(
        primary_root,
        primary_namespace,
        when,
        tag,
        args.text,
        level=level,
        confidence=confidence,
        source=source,
        files=files,
        project=project,
        topic=topic,
    )
    # Stats: distinguish hook-driven silent appends from user/Claude writes so
    # the dashboard can show authorship.
    _bump_lifetime_stats(
        scoped_root,
        {"log_entries_auto" if (source or "user") == "auto" else "log_entries_user": 1},
        machine_id=_primary_machine_id(args),
    )
    return {
        "changed": True,
        "path": str(target),
        "sha256": sha256_file(target),
        "auto_project": project if project else None,
        "auto_topic": topic if topic else None,
    }


_MACHINE_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
# Field-name suffix that means "this is an ISO timestamp, take max across
# shards" instead of summing. Counter fields (anything else) are summed.
_STATS_TS_SUFFIX = "_ts"


def _safe_machine_id(value: str) -> str:
    cleaned = _MACHINE_ID_SAFE_RE.sub("-", (value or "").strip())
    return (cleaned[:64] or "unknown-machine")


def _stats_dir(scoped_root: Path) -> Path:
    return scoped_root / "STATS"


def _stats_shard_path(scoped_root: Path, machine_id: str) -> Path:
    return _stats_dir(scoped_root) / f"{_safe_machine_id(machine_id)}.json"


def _migrate_legacy_stats(scoped_root: Path, machine_id: str) -> None:
    """Move ``<ns>/STATS.json`` to ``<ns>/STATS/<machine>.json`` once.

    Idempotent: skips when the shard already exists or the legacy file is
    missing. Best-effort — failures leave both copies in place; the
    aggregate reader will still pick up either one. Also handles the
    ``<ns>/local/STATS.json`` pre-V2.4 location for completeness.
    """
    target = _stats_shard_path(scoped_root, machine_id)
    if target.exists():
        return
    candidates = [scoped_root / "STATS.json", scoped_root / "local" / "STATS.json"]
    for legacy in candidates:
        if not legacy.is_file():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            legacy.replace(target)
            return
        except OSError:
            return


def _list_stats_shards(scoped_root: Path) -> list[Path]:
    """Return every shard plus surviving legacy paths the dashboard should read."""
    shards: list[Path] = []
    stats_dir = _stats_dir(scoped_root)
    if stats_dir.is_dir():
        shards.extend(sorted(stats_dir.glob("*.json")))
    # Legacy fall-throughs: still readable when migration hasn't run yet
    # (e.g., dashboard touched before any write-* command).
    for legacy in (scoped_root / "STATS.json", scoped_root / "local" / "STATS.json"):
        if legacy.is_file() and legacy not in shards:
            shards.append(legacy)
    return shards


def aggregate_lifetime_stats(scoped_root: Path) -> dict:
    """Sum counters / max timestamps across every machine's STATS shard.

    Output schema mirrors the legacy single-file shape so callers
    (dashboard, status CLI) keep working unchanged:
      ``{"last_event_ts": str|None, "lifetime": {...}, "shard_count": int}``.
    Counters (default) are summed across shards; field names ending with
    ``_ts`` are timestamps and take the max value (ISO-8601 sorts
    lexicographically). Per-machine throttling state like
    ``last_distill_inject_turn`` and ``cumulative_human_turns`` are
    integers — summing them across shards over-states a single machine's
    progress, but the dashboard treats both as totals so the sum is the
    right rendering. The hook side reads its own shard via
    ``read_machine_stats``.
    """
    out_lifetime: dict[str, Any] = {}
    last_event_ts: str | None = None
    shards = _list_stats_shards(scoped_root)
    for path in shards:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        shard_ts = raw.get("last_event_ts")
        if isinstance(shard_ts, str):
            if last_event_ts is None or shard_ts > last_event_ts:
                last_event_ts = shard_ts
        lifetime = raw.get("lifetime")
        if not isinstance(lifetime, dict):
            continue
        for key, value in lifetime.items():
            if key.endswith(_STATS_TS_SUFFIX):
                if isinstance(value, str):
                    cur = out_lifetime.get(key)
                    if not isinstance(cur, str) or value > cur:
                        out_lifetime[key] = value
                continue
            try:
                delta = int(value)
            except (TypeError, ValueError):
                continue
            out_lifetime[key] = int(out_lifetime.get(key, 0) or 0) + delta
    return {
        "last_event_ts": last_event_ts,
        "lifetime": out_lifetime,
        "shard_count": len(shards),
    }


def read_machine_stats(scoped_root: Path, machine_id: str) -> dict:
    """Read THIS machine's STATS shard only. Used for per-machine throttling
    (the hook side) where summing across machines would corrupt thresholds.
    """
    path = _stats_shard_path(scoped_root, machine_id)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _primary_machine_id(args: argparse.Namespace) -> str:
    """Resolve the primary root's ``machine_id`` from the active config.

    Re-reads config rather than threading it through every do_* signature.
    Returns ``"unknown-machine"`` if anything fails so write paths still
    succeed (just under a fallback shard name).
    """
    try:
        config = load_config(
            Path(args.config) if getattr(args, "config", None) else None,
            os.environ.get("USING_MEMORY_CONFIG"),
        )
        if not config:
            return "unknown-machine"
        primary_list, _ = collect_roots(config)
        if not primary_list:
            return "unknown-machine"
        return _safe_machine_id(primary_list[0].get("machine_id") or "")
    except Exception:
        return "unknown-machine"


def _bump_lifetime_stats(scoped_root: Path, deltas: dict, sets: dict | None = None, *, machine_id: str = "unknown-machine") -> None:
    """Atomic update of ``<namespace>/STATS/<machine_id>.json``.

    Same contract as the hook-side bump_stats; lives here so write-* CLI
    commands can update counts independently of any hook context.
    ``deltas`` are added to existing values; ``sets`` overwrite them.
    """
    if not deltas and not sets:
        return
    _migrate_legacy_stats(scoped_root, machine_id)
    path = _stats_shard_path(scoped_root, machine_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        except (OSError, json.JSONDecodeError):
            current = {}
        lifetime = current.setdefault("lifetime", {})
        for key, delta in (deltas or {}).items():
            try:
                d = int(delta)
            except (TypeError, ValueError):
                continue
            lifetime[key] = int(lifetime.get(key, 0) or 0) + d
        for key, value in (sets or {}).items():
            lifetime[key] = value
        current["last_event_ts"] = datetime.now().astimezone().isoformat(timespec="seconds")
        atomic_write_text(path, json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except Exception:
        return


# Topic keyword routing: lightweight, regex-based, no LLM. Order matters —
# first matching topic wins so callers get deterministic results.
_TOPIC_KEYWORDS: list[tuple[str, re.Pattern]] = [
    ("hooks", re.compile(r"\b(hook|hooks|posttooluse|pretooluse|sessionstart|stop[ _-]?hook|precompact)\b", re.I)),
    ("anatomy", re.compile(r"\banatomy\b", re.I)),
    ("build", re.compile(r"\b(build|compile|docker[ _-]?build|image[ _-]?build|tsc|webpack|vite)\b", re.I)),
    ("deploy", re.compile(r"\b(deploy|release|rollout|helm|kubectl|fly\.io|render|netlify|vercel)\b", re.I)),
    ("test", re.compile(r"\b(tests?|pytest|jest|vitest|cargo[ _-]?tests?|go[ _-]?tests?|smoke[ _-]?tests?)\b", re.I)),
    ("commit", re.compile(r"\b(commit|push|rebase|merge|cherry-pick|tag\s+v\d|origin/main)\b", re.I)),
    ("debug", re.compile(r"\b(debug|stack[ _-]?trace|traceback|investigate|root[ _-]?cause)\b", re.I)),
    ("config", re.compile(r"\b(settings\.json|config\.toml|claude\.md|agents\.md|gitignore|dockerfile|tsconfig)\b", re.I)),
    ("docs", re.compile(r"\b(readme|docs/|documentation|skill\.md)\b", re.I)),
    ("search", re.compile(r"\b(search|index|retriev)\b", re.I)),
    ("axes", re.compile(r"\b(axes|topic|project axis|two[ _-]axis)\b", re.I)),
]


def _infer_topic_from_text(text: str, tag: str) -> str | None:
    """Best-effort topic detection. Returns None when no keyword pattern hits.

    The tag is consulted as a hint for ambiguous topics (a 'commit' tag with
    text mentioning 'docs' picks 'commit', not 'docs').
    """
    if not text:
        return None
    t = (tag or "").lower()
    if t in {"commit", "deploy", "release", "build", "test"}:
        return t
    for slug, pattern in _TOPIC_KEYWORDS:
        if pattern.search(text):
            return slug
    return None


_AXIS_VALUE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _normalize_axis_value(value: str | None) -> str | None:
    """Validate a project/topic axis value: lowercased, [a-z0-9._-], 1..64 chars.

    Returns None for empty / None input. Exits with code 2 on invalid syntax so
    bad data never silently lands in JSONL.
    """
    if value is None:
        return None
    stripped = value.strip().lower()
    if not stripped:
        return None
    if not _AXIS_VALUE_RE.match(stripped):
        sys.stderr.write(
            f"invalid axis value '{value}': must match {_AXIS_VALUE_RE.pattern} "
            "(lowercase alnum + . _ -, 1..64 chars)\n"
        )
        sys.exit(2)
    return stripped


def do_write_memory(args: argparse.Namespace) -> dict:
    primary_root, primary_namespace = load_primary_for_write(args)
    when = parse_iso_date(args.date, "--date")
    allowed = {"decision", "lesson", "fact"}
    tag = (args.tag or "").lower()
    if tag not in allowed:
        sys.stderr.write(f"tag is not allowed for write-memory\n")
        sys.exit(2)
    target = append_memory_entry(namespace_root(primary_root, primary_namespace), when, tag, args.text)
    return {
        "changed": True,
        "path": str(target),
        "sha256": sha256_file(target),
    }


def do_write_preference(args: argparse.Namespace) -> dict:
    primary_root, primary_namespace = load_primary_for_write(args)
    when = parse_iso_date(args.date, "--date") if args.date else date.today()
    target = append_preference_entry(namespace_root(primary_root, primary_namespace), when, args.text)
    return {
        "changed": True,
        "path": str(target),
        "sha256": sha256_file(target),
    }


def do_upsert_doc(args: argparse.Namespace) -> dict:
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)
    doc_name = validate_doc_name(args.doc)
    # ``doc_name`` is now the rel path *with* extension (default ``.md`` when
    # the caller omitted one). Stem-only fallbacks below use ``strip_doc_ext``.

    text = args.text
    if text is None:
        if getattr(args, "text_stdin", False):
            text = sys.stdin.read()
        else:
            sys.stderr.write("upsert-doc requires --text or --text-stdin\n")
            sys.exit(2)

    ext = Path(doc_name).suffix.lower()
    stem = strip_doc_ext(doc_name)

    # Fallback fields: title -> first H1 / <title> / first non-empty line ->
    # slug-derived; doc_type -> "wiki"; modified -> today; created ->
    # today for new docs and preserved from the existing index entry on edit.
    if args.title is not None:
        title = args.title
    else:
        title = (
            extract_doc_title_from_text(text, ext)
            or stem.replace("-", " ").replace("_", " ").strip().title()
            or stem
        )
    doc_type = args.doc_type or "wiki"
    today = date.today().isoformat()
    modified = args.modified or today
    parse_iso_date(modified, "--modified")
    created = args.created or modified
    parse_iso_date(created, "--created")

    doc_path = scoped_root / "docs" / doc_name
    index_path = scoped_root / "docs" / "index.json"
    rel_path = doc_name

    # Validate --link-log values up front (before the lock) so a bad input
    # surfaces a clean error instead of a partial write. Empty list = no
    # backlink section is added or rewritten beyond what's already in text.
    link_log = list(args.link_log or [])
    for link in link_log:
        if parse_log_backlink(link) is None:
            sys.stderr.write(f"invalid --link-log value (expected [[log:YYYY-MM-DD#L<n>]]): {link!r}\n")
            sys.exit(2)

    with exclusive_file_lock(scoped_root / "docs" / ".docs.lock"):
        # Preserve any [[log:...]] backlinks already in the existing doc by
        # merging them with --link-log. New text body is treated as
        # authoritative; we only touch the Related-log-entries section.
        existing_links: set[tuple[str, int]] = set()
        if doc_path.exists():
            try:
                old_body = doc_path.read_text(encoding="utf-8")
                existing_links = extract_log_backlinks_from_text(old_body)
            except OSError:
                existing_links = set()

        if link_log or existing_links:
            preserved = [format_log_backlink(d, n) for d, n in sorted(existing_links)]
            text = merge_log_backlinks_section(text, link_log + preserved)

        index = load_doc_index(index_path)
        existing_entry = next(
            (doc for doc in normalize_doc_index(index) if doc.get("path") == rel_path),
            None,
        )
        if existing_entry and not args.created:
            created = existing_entry.get("created") or created
            parse_iso_date(created, "--created")
        entry = {
            "path": rel_path,
            "title": title,
            "type": doc_type,
            "created": created,
            "modified": modified,
            "projects": args.project or [],
            "tags": args.doc_tag or [],
        }
        if args.summary:
            entry["summary"] = args.summary
        error = validate_doc_entry(entry)
        if error:
            sys.stderr.write(f"invalid doc metadata: {error}\n")
            sys.exit(2)
        index = doc_index_with_entry(index, entry)
        atomic_write_text(doc_path, text)
        write_doc_index(index_path, index)

    final_links = extract_log_backlinks_from_text(text)
    return {
        "changed": True,
        "path": str(doc_path),
        "index_path": str(index_path),
        "sha256": sha256_file(doc_path),
        "index_sha256": sha256_file(index_path),
        "title": title,
        "doc_type": doc_type,
        "created": created,
        "modified": modified,
        "log_backlinks": sorted(f"{d}#L{n}" for d, n in final_links),
    }


# ============================================================================
# Anatomy: project file-index snapshot
# ============================================================================
#
# Lives at ``<namespace>/anatomy/{_index.json, <slug>.json, <slug>.md}``.
# JSON is the source of truth; the .md file is re-rendered on every write so
# humans can grep it. Token estimates use a single shared char-to-token ratio.

_ANATOMY_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# OpenWolf-style heuristic: chars-per-token by content kind. Single source of
# truth — DO NOT clone this constant elsewhere; OpenWolf shipped three
# divergent copies of the same estimator and it created silent drift.
_TOKEN_RATIOS = {"code": 3.5, "prose": 4.0, "mixed": 3.75}

# Files we never index (binary blobs, lockfiles, build artifacts, vendored deps).
_ANATOMY_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    "target", ".idea", ".vscode", ".next", ".cache", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "out", ".gradle", ".tox",
}
_ANATOMY_SKIP_FILE_SUFFIXES = (
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".class", ".jar", ".war", ".o",
    ".a", ".lib", ".exe", ".bin", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".ico", ".pdf", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z",
    ".mp3", ".mp4", ".mov", ".avi", ".wav", ".flac", ".ttf", ".otf", ".woff",
    ".woff2", ".eot", ".svg",
)
_ANATOMY_LOCK_SUFFIXES = ("-lock.json", ".lock")
_ANATOMY_LOCK_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock",
    "Pipfile.lock", "poetry.lock", "uv.lock", "Gemfile.lock", "go.sum",
    "composer.lock",
}


def _anatomy_root(scoped_root: Path) -> Path:
    return scoped_root / "anatomy"


def _anatomy_index_path(scoped_root: Path) -> Path:
    return _anatomy_root(scoped_root) / "_index.json"


def _anatomy_json_path(scoped_root: Path, slug: str) -> Path:
    return _anatomy_root(scoped_root) / f"{slug}.json"


def _anatomy_md_path(scoped_root: Path, slug: str) -> Path:
    return _anatomy_root(scoped_root) / f"{slug}.md"


def _anatomy_validate_slug(slug: str) -> str:
    s = (slug or "").strip().lower()
    if not _ANATOMY_SLUG_RE.match(s):
        sys.stderr.write(
            f"invalid slug '{slug}': must match {_ANATOMY_SLUG_RE.pattern} "
            "(lowercase alnum + . _ -, 1..64 chars, first char alnum)\n"
        )
        sys.exit(2)
    return s


def _anatomy_default_slug(root: Path) -> str:
    """Derive a default slug from the project root basename."""
    raw = root.name.lower()
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-._")
    if not cleaned:
        cleaned = "project"
    cleaned = cleaned[:64]
    return cleaned if _ANATOMY_SLUG_RE.match(cleaned) else "project"


def _anatomy_load_index(scoped_root: Path) -> dict:
    path = _anatomy_index_path(scoped_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _anatomy_save_index(scoped_root: Path, index: dict) -> None:
    path = _anatomy_index_path(scoped_root)
    atomic_write_text(path, json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _anatomy_load_doc(scoped_root: Path, slug: str) -> dict:
    path = _anatomy_json_path(scoped_root, slug)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _anatomy_save_doc(scoped_root: Path, slug: str, doc: dict) -> None:
    path = _anatomy_json_path(scoped_root, slug)
    atomic_write_text(path, json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _classify_file_kind(rel_path: str) -> str:
    """Return 'code' / 'prose' / 'config' / 'script' / 'other'."""
    p = rel_path.lower()
    if p.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
                   ".go", ".rs", ".java", ".kt", ".kts", ".scala", ".cpp",
                   ".cc", ".c", ".h", ".hpp", ".rb", ".php", ".swift",
                   ".m", ".mm", ".cs", ".fs", ".clj", ".cljs", ".ex", ".exs",
                   ".sql", ".lua", ".dart", ".r", ".jl")):
        return "code"
    if p.endswith((".md", ".markdown", ".rst", ".txt", ".adoc")):
        return "prose"
    if p.endswith((".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd")):
        return "script"
    if p.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
                   ".conf", ".env")) or rel_path in {
                       "Dockerfile", "Makefile", ".gitignore", ".dockerignore"
                   }:
        return "config"
    return "other"


def _token_kind_for_estimate(file_kind: str) -> str:
    if file_kind == "code" or file_kind == "script":
        return "code"
    if file_kind == "prose":
        return "prose"
    return "mixed"


def estimate_tokens(text: str, kind: str = "mixed") -> int:
    """Heuristic token estimate. ratio: code=3.5, prose=4.0, mixed=3.75 chars/token.

    Strips obvious base64 blobs and very long URLs so they don't skew the
    estimate. Single source of truth — never clone this function.
    """
    if not text:
        return 0
    cleaned = re.sub(r"\bdata:[^\s\"']{200,}", "", text)              # data URIs
    cleaned = re.sub(r"\b[A-Za-z0-9+/]{200,}={0,2}\b", "", cleaned)   # base64
    cleaned = re.sub(r"https?://\S{120,}", "", cleaned)               # huge URLs
    ratio = _TOKEN_RATIOS.get(kind, _TOKEN_RATIOS["mixed"])
    return max(1, int(len(cleaned) / ratio + 0.5))


def _extract_description(file_path: Path, file_kind: str) -> str:
    """Best-effort extract a short human description from file head.

    Returns "" if nothing useful was found. Reads at most 12 KB.
    """
    try:
        head = file_path.read_text(encoding="utf-8", errors="replace")[:12_000]
    except OSError:
        return ""
    if not head.strip():
        return ""
    if file_kind == "prose":
        # First H1 + first paragraph after it; fall back to first non-empty paragraph.
        m = re.search(r"^# +(.+?)$", head, flags=re.MULTILINE)
        if m:
            after = head[m.end():]
            para = re.split(r"\n\s*\n", after.strip(), maxsplit=1)
            first = (para[0] if para else "").strip()
            return _condense(f"{m.group(1).strip()} — {first}" if first else m.group(1).strip())
        first_para = re.split(r"\n\s*\n", head.strip(), maxsplit=1)[0]
        return _condense(first_para)
    if file_kind == "code":
        # Strip a leading shebang line so it does not pollute downstream
        # heuristics. Without this, files like `#!/usr/bin/env python3\n"""docs"""`
        # fall past the docstring regex (anchored at start) and end up with
        # "!/usr/bin/env python3" as the desc.
        code_head = re.sub(r"\A#![^\n]*\n", "", head, count=1)
        # Try docstring first (Python) — also handles the case where it lives
        # at module top-of-file after the shebang.
        m = re.search(r'^\s*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', code_head, flags=re.DOTALL)
        if m:
            return _condense(m.group(1))
        # JSDoc / block comment
        m = re.search(r"^\s*/\*\*?(.*?)\*/", code_head, flags=re.DOTALL)
        if m:
            cleaned = re.sub(r"^\s*\*\s?", "", m.group(1), flags=re.MULTILINE)
            return _condense(cleaned)
        # Top-of-file line comments
        line_comment = []
        for line in code_head.splitlines()[:30]:
            s = line.strip()
            if s.startswith("#!"):
                # Defensive: should be stripped already, but guard anyway.
                continue
            if not s:
                if line_comment:
                    break
                continue
            cm = re.match(r"^(?://|#)\s?(.*)$", s)
            if cm:
                line_comment.append(cm.group(1))
            elif line_comment:
                break
        if line_comment:
            return _condense(" ".join(line_comment))
        # Inner-symbol docstring fallback: the first def/class with a
        # docstring right under it. Useful for Python test files like
        # `class FooTests(unittest.TestCase):\n    """What FooTests covers."""`
        # which otherwise resolve to a useless "first symbol: FooTests".
        m = re.search(
            r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_][\w]*)[^\n]*\n"
            r"\s*(?:\"\"\"|''')(.*?)(?:\"\"\"|''')",
            code_head,
            flags=re.DOTALL | re.MULTILINE,
        )
        if m:
            return _condense(f"{m.group(1)}: {m.group(2)}")
        # First export / def / class / function signature (last resort)
        m = re.search(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|def|interface|type)\s+([A-Za-z_][\w]*)",
                      code_head, flags=re.MULTILINE)
        if m:
            return f"first symbol: {m.group(1)}"
        return ""
    if file_kind == "script":
        line_comment = []
        for line in head.splitlines()[:30]:
            s = line.strip()
            if s.startswith("#!"):
                continue
            if not s:
                if line_comment:
                    break
                continue
            if s.startswith("#"):
                line_comment.append(s.lstrip("#").strip())
            elif line_comment:
                break
        if line_comment:
            return _condense(" ".join(line_comment))
        return ""
    if file_kind == "config":
        # Recognise common files by filename
        name = file_path.name
        known = {
            "package.json": "npm package manifest",
            "pyproject.toml": "Python project manifest",
            "Cargo.toml": "Cargo crate manifest",
            "go.mod": "Go module manifest",
            "Dockerfile": "Docker image build instructions",
            "Makefile": "Make build rules",
            ".gitignore": "git ignore patterns",
            "tsconfig.json": "TypeScript compiler config",
        }
        return known.get(name, "")
    return ""


def _condense(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) > 240:
        text = text[:237] + "..."
    return text


def _anatomy_should_skip(path: Path, project_root: Path) -> bool:
    try:
        rel = path.relative_to(project_root)
    except ValueError:
        return True
    parts = rel.parts
    if any(part in _ANATOMY_SKIP_DIRS for part in parts):
        return True
    name = path.name
    if name.startswith(".") and name not in {".gitignore", ".dockerignore", ".env.example"}:
        return True
    if name in _ANATOMY_LOCK_NAMES:
        return True
    if name.lower().endswith(_ANATOMY_LOCK_SUFFIXES) and name not in {".gitignore"}:
        return True
    if name.lower().endswith(_ANATOMY_SKIP_FILE_SUFFIXES):
        return True
    try:
        if path.is_symlink():
            return True
        if path.stat().st_size > 2_000_000:  # >2 MB: probably not source
            return True
    except OSError:
        return True
    return False


def _anatomy_walk(project_root: Path):
    """Yield (path, rel_path) pairs for indexable files under project_root."""
    keep_dotted = {".github", ".claude"}
    for current_root, dirs, files in os.walk(project_root):
        # Prune skipped dirs in-place so os.walk stops descending. Drop generic
        # dotfiles but allow specific ones (.github, .claude) that often hold
        # real config worth indexing.
        dirs[:] = [
            d for d in dirs
            if d not in _ANATOMY_SKIP_DIRS and (not d.startswith(".") or d in keep_dotted)
        ]
        for fname in files:
            p = Path(current_root) / fname
            if _anatomy_should_skip(p, project_root):
                continue
            try:
                rel = p.relative_to(project_root).as_posix()
            except ValueError:
                continue
            yield p, rel


def _anatomy_build_file_entry(path: Path, rel: str) -> dict:
    kind = _classify_file_kind(rel)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    desc = _extract_description(path, kind)
    tokens = estimate_tokens(text, _token_kind_for_estimate(kind))
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        mtime = ""
    return {
        "desc": desc,
        "desc_source": "auto" if desc else "empty",
        "tokens_est": tokens,
        "kind": kind,
        "mtime": mtime,
    }


def _anatomy_render_md(doc: dict) -> str:
    project = doc.get("project", "?")
    root = doc.get("root", "?")
    scanned = doc.get("scanned_at", "")
    totals = doc.get("totals", {})
    files = doc.get("files", {}) or {}

    lines = [
        f"# Anatomy: {project}",
        "",
        f"- Root: `{root}`",
        f"- Scanned at: {scanned}",
        f"- Files: {totals.get('files', len(files))}",
        f"- Tokens (est): {totals.get('tokens_est', 0)}",
        "",
    ]

    # Group files by top-level directory for readability.
    groups: dict[str, list[tuple[str, dict]]] = {}
    for rel, entry in files.items():
        head = rel.split("/", 1)[0] if "/" in rel else "(root)"
        groups.setdefault(head, []).append((rel, entry))
    for head in sorted(groups):
        items = groups[head]
        items.sort(key=lambda x: x[0])
        lines.append(f"## {head}/")
        lines.append("")
        for rel, entry in items:
            display = rel if head == "(root)" else rel[len(head) + 1:]
            desc = entry.get("desc") or ""
            tok = entry.get("tokens_est", 0)
            src = entry.get("desc_source", "auto")
            tag = "" if src == "auto" else f" [{src}]"
            if desc:
                lines.append(f"- `{display}` — {desc} (~{tok} tok){tag}")
            else:
                lines.append(f"- `{display}` (~{tok} tok){tag}")
        lines.append("")
    return "\n".join(lines)


def _anatomy_persist(scoped_root: Path, slug: str, doc: dict) -> tuple[Path, Path]:
    _anatomy_save_doc(scoped_root, slug, doc)
    md_path = _anatomy_md_path(scoped_root, slug)
    atomic_write_text(md_path, _anatomy_render_md(doc))
    return _anatomy_json_path(scoped_root, slug), md_path


def _anatomy_resolve_slug(scoped_root: Path, slug_or_root: str) -> str | None:
    """Accept either a slug or a project root path; return the slug or None."""
    candidate = slug_or_root.strip()
    if not candidate:
        return None
    index = _anatomy_load_index(scoped_root)
    if candidate in index:
        return candidate
    p = Path(candidate).expanduser().resolve()
    for slug, info in index.items():
        if Path(info.get("root", "")).resolve() == p:
            return slug
    return None


def _anatomy_resolve_slug_or_die(scoped_root: Path, slug_or_root: str) -> str:
    """Resolve a slug-or-root argument or exit(2) with a uniform error.

    Centralises the "no anatomy project matches '<arg>'" pattern used by
    every read-side anatomy CLI command so the message stays consistent.
    """
    slug = _anatomy_resolve_slug(scoped_root, slug_or_root)
    if slug is None:
        sys.stderr.write(
            f"no anatomy project matches '{slug_or_root}'. "
            "Run `memory_tool.py anatomy-register <root>` first, or check `anatomy-list`.\n"
        )
        sys.exit(2)
    return slug


def do_anatomy_register(args: argparse.Namespace) -> dict:
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)
    project_root = Path(args.root).expanduser().resolve()
    if not project_root.is_dir():
        sys.stderr.write(f"project root does not exist or is not a directory: {project_root}\n")
        sys.exit(2)
    slug = _anatomy_validate_slug(args.slug) if args.slug else _anatomy_default_slug(project_root)
    index = _anatomy_load_index(scoped_root)
    if slug in index and Path(index[slug].get("root", "")).resolve() != project_root:
        sys.stderr.write(
            f"slug '{slug}' already registered to {index[slug].get('root')!r}; "
            f"pick a different name with --slug\n"
        )
        sys.exit(2)
    index[slug] = {
        "root": str(project_root),
        "registered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _anatomy_save_index(scoped_root, index)
    return {
        "changed": True,
        "slug": slug,
        "root": str(project_root),
        "index_path": str(_anatomy_index_path(scoped_root)),
    }


def do_anatomy_scan(args: argparse.Namespace) -> dict:
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)
    slug = _anatomy_resolve_slug_or_die(scoped_root, args.slug)
    index = _anatomy_load_index(scoped_root)
    project_root = Path(index[slug]["root"]).expanduser().resolve()
    if not project_root.is_dir():
        sys.stderr.write(f"registered project root no longer exists: {project_root}\n")
        sys.exit(2)
    existing = _anatomy_load_doc(scoped_root, slug)
    existing_files = (existing.get("files") or {}) if isinstance(existing, dict) else {}

    files: dict = {}
    total_tokens = 0
    for path, rel in _anatomy_walk(project_root):
        new_entry = _anatomy_build_file_entry(path, rel)
        prev = existing_files.get(rel)
        if prev and prev.get("desc_source") == "user" and prev.get("desc"):
            # Preserve user-curated description; refresh tokens/mtime/kind.
            new_entry["desc"] = prev["desc"]
            new_entry["desc_source"] = "user"
        files[rel] = new_entry
        total_tokens += new_entry.get("tokens_est", 0)

    doc = {
        "project": slug,
        "root": str(project_root),
        "scanned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "totals": {"files": len(files), "tokens_est": total_tokens},
        "files": files,
    }
    json_path, md_path = _anatomy_persist(scoped_root, slug, doc)
    return {
        "changed": True,
        "slug": slug,
        "root": str(project_root),
        "files": len(files),
        "tokens_est": total_tokens,
        "json_path": str(json_path),
        "md_path": str(md_path),
    }


def do_anatomy_show(args: argparse.Namespace) -> dict:
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)
    slug = _anatomy_resolve_slug_or_die(scoped_root, args.slug)
    md_path = _anatomy_md_path(scoped_root, slug)
    if not md_path.exists():
        sys.stderr.write(
            f"anatomy not yet scanned for '{slug}'. Run anatomy-scan first.\n"
        )
        sys.exit(2)
    return {
        "slug": slug,
        "md_path": str(md_path),
        "content": md_path.read_text(encoding="utf-8"),
    }


def do_anatomy_set(args: argparse.Namespace) -> dict:
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)
    slug = _anatomy_resolve_slug_or_die(scoped_root, args.slug)
    doc = _anatomy_load_doc(scoped_root, slug)
    if not doc:
        sys.stderr.write(
            f"anatomy not yet scanned for '{slug}'. Run anatomy-scan first.\n"
        )
        sys.exit(2)
    files = doc.setdefault("files", {})
    rel = args.relpath.lstrip("/")
    entry = files.get(rel)
    if not entry:
        sys.stderr.write(
            f"file '{rel}' not in anatomy. Run anatomy-scan or check the path.\n"
        )
        sys.exit(2)
    new_desc = _condense(args.desc)
    if not new_desc:
        sys.stderr.write("--desc must be a non-empty string\n")
        sys.exit(2)
    entry["desc"] = new_desc
    entry["desc_source"] = "user"
    json_path, md_path = _anatomy_persist(scoped_root, slug, doc)
    return {
        "changed": True,
        "slug": slug,
        "relpath": rel,
        "desc": new_desc,
        "desc_source": "user",
        "json_path": str(json_path),
        "md_path": str(md_path),
    }


def do_anatomy_list(args: argparse.Namespace) -> dict:
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)
    index = _anatomy_load_index(scoped_root)
    projects = []
    for slug in sorted(index.keys()):
        info = index[slug] or {}
        doc = _anatomy_load_doc(scoped_root, slug)
        totals = (doc.get("totals") or {}) if isinstance(doc, dict) else {}
        projects.append({
            "slug": slug,
            "root": info.get("root"),
            "registered_at": info.get("registered_at"),
            "scanned_at": doc.get("scanned_at"),
            "files": totals.get("files", 0),
            "tokens_est": totals.get("tokens_est", 0),
        })
    return {"projects": projects, "count": len(projects)}


def do_status(args: argparse.Namespace) -> dict:
    """Aggregate dashboard for the using-memory installation.

    Reads every ``<namespace>/STATS/<machine_id>.json`` shard (real event
    counters, no estimates), plus the anatomy index, and computes two
    diagnostic ratios:
      - anatomy_hit_rate     = anatomy_attached_count / sessions
      - stop_block_ratio     = stop_blocks / (stop_blocks + stop_throttled_passthrough)

    Both ratios are diagnostic, not performance claims. The hit rate tells
    the user how often SessionStart found a registered project; a low rate
    suggests more anatomy-register calls would help when anatomy attach is
    enabled. The block ratio tells the user whether the configured Stop gate
    is too aggressive (high -> too many blocks) or mostly passing through
    (very low).

    Multi-machine semantics: counters are summed across shards; ``_ts``
    fields take the max value. Pre-sharded installs are migrated on first
    write; un-migrated namespaces are still readable via the legacy
    fall-through inside ``aggregate_lifetime_stats``.
    """
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)
    machine_id = _primary_machine_id(args)
    # Best-effort migrate while we have the lock-free read path; the next
    # write would do it anyway, this just makes the listing tidy sooner.
    _migrate_legacy_stats(scoped_root, machine_id)

    aggregated = aggregate_lifetime_stats(scoped_root)
    lifetime: dict = aggregated.get("lifetime") or {}
    last_event_ts: str | None = aggregated.get("last_event_ts")
    shard_count: int = int(aggregated.get("shard_count") or 0)

    def _g(k: str) -> int:
        try:
            return int(lifetime.get(k, 0) or 0)
        except (TypeError, ValueError):
            return 0

    sessions = _g("sessions")
    attached = _g("anatomy_attached_count")
    truncated = _g("anatomy_truncated_count")
    hints = _g("anatomy_hint_emitted")
    attached_tokens = _g("anatomy_attached_tokens_est")
    upserts = _g("anatomy_upserts")
    auto_registered = _g("anatomy_auto_registered")
    log_auto = _g("log_entries_auto")
    log_user = _g("log_entries_user")
    blocks = _g("stop_blocks")
    passthrough = _g("stop_throttled_passthrough")
    precompact = _g("precompact_blocks")

    hit_rate = round(attached / sessions, 3) if sessions else None
    total_stops = blocks + passthrough
    block_ratio = round(blocks / total_stops, 3) if total_stops else None

    index = _anatomy_load_index(scoped_root)
    projects: list[dict] = []
    total_files = 0
    total_tokens = 0
    for slug in sorted(index.keys()):
        info = index[slug] or {}
        doc = _anatomy_load_doc(scoped_root, slug)
        totals = (doc.get("totals") or {}) if isinstance(doc, dict) else {}
        files = int(totals.get("files", 0) or 0)
        tokens = int(totals.get("tokens_est", 0) or 0)
        total_files += files
        total_tokens += tokens
        projects.append({
            "slug": slug,
            "root": info.get("root"),
            "files": files,
            "tokens_est": tokens,
            "scanned": bool(doc),
        })

    return {
        "stats_path": str(_stats_dir(scoped_root)),
        "stats_shards": shard_count,
        "last_event_ts": last_event_ts,
        "lifetime": {
            "sessions": sessions,
            "anatomy_attached_count": attached,
            "anatomy_truncated_count": truncated,
            "anatomy_hint_emitted": hints,
            "anatomy_attached_tokens_est": attached_tokens,
            "anatomy_upserts": upserts,
            "anatomy_auto_registered": auto_registered,
            "log_entries_auto": log_auto,
            "log_entries_user": log_user,
            "stop_blocks": blocks,
            "stop_throttled_passthrough": passthrough,
            "precompact_blocks": precompact,
            "cumulative_human_turns": _g("cumulative_human_turns"),
            "last_distill_check_ts": lifetime.get("last_distill_check_ts"),
            "last_distill_inject_ts": lifetime.get("last_distill_inject_ts"),
            "last_promote_ts": lifetime.get("last_promote_ts"),
        },
        "ratios": {
            "anatomy_hit_rate": hit_rate,
            "stop_block_ratio": block_ratio,
        },
        "anatomy": {
            "registered_projects": len(projects),
            "total_files": total_files,
            "total_tokens_est": total_tokens,
            "projects": projects,
        },
    }


def _longest_prefix_project_match(scoped_root: Path, target: Path) -> tuple[str | None, Path | None]:
    """Find the registered project whose root is the longest prefix of target.

    Returns (slug, resolved_root) or (None, None) when no registered project
    contains target. Target is resolved first to handle macOS symlink quirks
    (e.g. /tmp → /private/tmp).
    """
    try:
        resolved = target.expanduser().resolve()
    except OSError:
        return None, None
    index = _anatomy_load_index(scoped_root)
    best_slug: str | None = None
    best_root: Path | None = None
    best_len = -1
    for slug, info in index.items():
        raw = info.get("root") if isinstance(info, dict) else None
        if not raw:
            continue
        try:
            root = Path(raw).expanduser().resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        length = len(str(root))
        if length > best_len:
            best_slug = slug
            best_root = root
            best_len = length
    return best_slug, best_root


def _anatomy_match_cwd(scoped_root: Path, cwd: Path) -> tuple[str | None, Path | None]:
    return _longest_prefix_project_match(scoped_root, cwd)


def _anatomy_match_file(scoped_root: Path, file_path: Path) -> tuple[str | None, Path | None, str | None]:
    """Same as _anatomy_match_cwd but additionally returns the file's relative
    path within the matched project root. (None, None, None) on miss.
    """
    slug, root = _longest_prefix_project_match(scoped_root, file_path)
    if slug is None or root is None:
        return None, None, None
    try:
        rel = file_path.expanduser().resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None, None, None
    return slug, root, rel


def _anatomy_render_capped(doc: dict, max_tokens: int) -> tuple[str, bool]:
    """Render anatomy md, falling back to top-level summary when over budget.

    Returns (markdown, truncated). The full render is used when its estimated
    token cost is <= max_tokens, otherwise a compact top-level-directory
    summary with per-dir file/token counts is used so the loader stays within
    its budget.
    """
    full = _anatomy_render_md(doc)
    full_tokens = estimate_tokens(full, "mixed")
    if full_tokens <= max_tokens:
        return full, False
    files = doc.get("files", {}) or {}
    groups: dict[str, dict] = {}
    for rel, entry in files.items():
        head = rel.split("/", 1)[0] if "/" in rel else "(root)"
        g = groups.setdefault(head, {"files": 0, "tokens_est": 0})
        g["files"] += 1
        g["tokens_est"] += int(entry.get("tokens_est", 0) or 0)
    lines = [
        f"# Anatomy: {doc.get('project', '?')} (summary)",
        "",
        f"- Root: `{doc.get('root', '?')}`",
        f"- Scanned at: {doc.get('scanned_at', '')}",
        f"- Files: {doc.get('totals', {}).get('files', len(files))}",
        f"- Tokens (est): {doc.get('totals', {}).get('tokens_est', 0)}",
        f"- Full anatomy ~{full_tokens} tok exceeds load cap ({max_tokens} tok); showing top-level summary.",
        f"- To see a specific path's details: `memory_tool.py anatomy-show <slug>`.",
        "",
        "## Top-level directories",
        "",
    ]
    for head in sorted(groups):
        g = groups[head]
        lines.append(f"- `{head}/` — {g['files']} files, ~{g['tokens_est']} tok")
    lines.append("")
    return "\n".join(lines), True


def _cwd_is_git_repo(cwd: Path) -> bool:
    """True if cwd or any ancestor contains a .git directory or file."""
    try:
        p = cwd.expanduser().resolve()
    except OSError:
        return False
    for candidate in [p, *p.parents]:
        if (candidate / ".git").exists():
            return True
    return False


# Files whose presence on disk indicates "this is a real software project."
# Used to gate anatomy auto-registration; bare directories (e.g. ~/Downloads)
# never satisfy this and so never auto-register.
_ANATOMY_PROJECT_MARKERS: tuple[str, ...] = (
    "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "CMakeLists.txt",
    "setup.py", "setup.cfg", "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "composer.json", "Makefile", "Pipfile", "requirements.txt",
)


def _find_repo_root_with_marker(start: Path) -> Path | None:
    """Walk up from ``start`` looking for a .git ancestor whose subtree (from
    start up to and including the .git directory) contains at least one project
    marker.

    Returns the .git ancestor path on match (the repo root), or None.

    The walk records every candidate dir from ``start`` upward, then walks the
    same chain looking for the first ``.git`` ancestor; eligibility passes when
    ANY dir between ``start`` and that ancestor (inclusive) contains a marker.
    This handles monorepos (marker in a subpackage, .git at repo root) while
    still registering the repo root as a single anatomy slug.
    """
    try:
        p = start.expanduser().resolve()
    except OSError:
        return None
    if p.is_file():
        p = p.parent
    chain = [p, *p.parents]
    repo_root: Path | None = None
    for candidate in chain:
        if (candidate / ".git").exists():
            repo_root = candidate
            break
    if repo_root is None:
        return None
    for candidate in chain:
        for marker in _ANATOMY_PROJECT_MARKERS:
            if (candidate / marker).exists():
                return repo_root
        if candidate == repo_root:
            break
    return None


def _anatomy_resolve_unique_slug(scoped_root: Path, project_root: Path, index: dict) -> str | None:
    """Return a slug for ``project_root`` that does not collide with an
    existing index entry pointing at a different root.

    Strategy: start with the project root's basename slug. If taken by a
    different root, prepend up to two parent-dir segments (so /a/api collides
    with /b/api → b-api; further collision → b-yard-api). Returns None when
    three levels of disambiguation all fail.
    """
    try:
        resolved_root = project_root.expanduser().resolve()
    except OSError:
        return None

    def _taken_by_other(candidate: str) -> bool:
        info = index.get(candidate)
        if not isinstance(info, dict):
            return False
        raw = info.get("root")
        if not raw:
            return False
        try:
            other = Path(raw).expanduser().resolve()
        except OSError:
            return False
        return other != resolved_root

    base = _anatomy_default_slug(resolved_root)
    candidates: list[str] = [base]
    parents = list(resolved_root.parents)
    if parents:
        candidates.append(_anatomy_default_slug(Path(parents[0].name + "-" + resolved_root.name)))
    if len(parents) >= 2:
        candidates.append(_anatomy_default_slug(Path(
            parents[1].name + "-" + parents[0].name + "-" + resolved_root.name
        )))
    seen: set[str] = set()
    for slug in candidates:
        if slug in seen:
            continue
        seen.add(slug)
        if not _taken_by_other(slug):
            return slug
    return None


def _anatomy_auto_register_if_eligible(
    scoped_root: Path,
    anchor: Path,
) -> tuple[str | None, Path | None]:
    """If ``anchor`` lives inside an eligible-but-unregistered project, register
    the repo root in the anatomy index and return (slug, repo_root).

    Eligibility = .git ancestor exists AND some dir between anchor and that
    ancestor contains a marker file. Idempotent: re-running on an already
    registered root returns the existing slug without rewriting the index.
    Returns (None, None) when ineligible or when all three slug-disambiguation
    candidates collide with other roots.
    """
    repo_root = _find_repo_root_with_marker(anchor)
    if repo_root is None:
        return None, None
    index = _anatomy_load_index(scoped_root)
    # Idempotent fast-path: same root already registered? return that slug.
    try:
        resolved = repo_root.expanduser().resolve()
    except OSError:
        return None, None
    for slug, info in index.items():
        if not isinstance(info, dict):
            continue
        raw = info.get("root")
        if not raw:
            continue
        try:
            other = Path(raw).expanduser().resolve()
        except OSError:
            continue
        if other == resolved:
            return slug, resolved
    slug = _anatomy_resolve_unique_slug(scoped_root, resolved, index)
    if slug is None:
        return None, None
    index[slug] = {
        "root": str(resolved),
        "registered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "auto": True,
    }
    _anatomy_save_index(scoped_root, index)
    return slug, resolved


def _anatomy_suggest_for_hint(scoped_root: Path, cwd: Path) -> dict | None:
    """Return a suggestion dict for the SessionStart hint when cwd is inside an
    eligible-but-unregistered project. Read-only: never writes the index.

    Result keys: root (str), suggested_slug (str), base_slug (str),
    conflict (bool). conflict=True means the base_slug derived from the
    project root's basename was taken; suggested_slug carries the
    path-segment-disambiguated alternative. Returns None when cwd is not
    inside an eligible repo (no .git or no marker).
    """
    repo_root = _find_repo_root_with_marker(cwd)
    if repo_root is None:
        return None
    try:
        resolved = repo_root.expanduser().resolve()
    except OSError:
        return None
    index = _anatomy_load_index(scoped_root)
    base = _anatomy_default_slug(resolved)
    suggested = _anatomy_resolve_unique_slug(scoped_root, resolved, index)
    return {
        "root": str(resolved),
        "base_slug": base,
        "suggested_slug": suggested,
        "conflict": suggested is not None and suggested != base,
    }


def _anatomy_persist_with_totals(scoped_root: Path, slug: str, doc: dict) -> None:
    """Recompute totals + bump scanned_at, then persist JSON + MD atomically."""
    files = doc.get("files", {}) or {}
    doc["totals"] = {
        "files": len(files),
        "tokens_est": sum(int((f or {}).get("tokens_est", 0) or 0) for f in files.values()),
    }
    doc["scanned_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _anatomy_persist(scoped_root, slug, doc)


def _anatomy_upsert_file(scoped_root: Path, slug: str, project_root: Path, file_path: Path, rel: str) -> str:
    """Refresh or remove the anatomy entry for one file.

    Returns one of: "updated", "removed", "skipped" (filtered/should-skip).
    On disk both <slug>.json and <slug>.md are re-written atomically when
    something changed. When the project has never been scanned, an empty
    snapshot shell is initialized inline so incremental upserts work right
    after `anatomy-register` without requiring a separate full scan.
    """
    doc = _anatomy_load_doc(scoped_root, slug)
    if not doc:
        doc = {
            "project": slug,
            "root": str(project_root),
            "scanned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "totals": {"files": 0, "tokens_est": 0},
            "files": {},
        }
    files = doc.setdefault("files", {})

    # Resolve to match project_root which has already been resolved by the
    # caller. On macOS /tmp is a symlink to /private/tmp; without this both
    # relative_to() inside _anatomy_should_skip and read_text() down below
    # silently behave differently.
    try:
        resolved_fp = file_path.expanduser().resolve()
    except OSError:
        resolved_fp = file_path

    # The file is gone OR filtered → drop any prior entry, no-op if absent.
    if not resolved_fp.exists() or _anatomy_should_skip(resolved_fp, project_root):
        if rel in files:
            del files[rel]
            _anatomy_persist_with_totals(scoped_root, slug, doc)
            return "removed"
        return "skipped"

    new_entry = _anatomy_build_file_entry(resolved_fp, rel)
    prev = files.get(rel)
    if prev and prev.get("desc_source") == "user" and prev.get("desc"):
        new_entry["desc"] = prev["desc"]
        new_entry["desc_source"] = "user"
    files[rel] = new_entry
    _anatomy_persist_with_totals(scoped_root, slug, doc)
    return "updated"


def do_anatomy_upsert_file(args: argparse.Namespace) -> dict:
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)
    file_path = Path(args.file).expanduser()
    slug, project_root, rel = _anatomy_match_file(scoped_root, file_path)
    auto_registered = False
    if (not slug or not project_root or rel is None) and getattr(args, "auto_register", False):
        new_slug, new_root = _anatomy_auto_register_if_eligible(scoped_root, file_path)
        if new_slug and new_root:
            slug, project_root, rel = _anatomy_match_file(scoped_root, file_path)
            auto_registered = True
    if not slug or not project_root or rel is None:
        return {
            "changed": False,
            "matched": False,
            "file": str(file_path),
            "reason": "no registered project contains this file",
        }
    action = _anatomy_upsert_file(scoped_root, slug, project_root, file_path, rel)
    result = {
        "changed": action in {"updated", "removed"},
        "matched": True,
        "slug": slug,
        "rel": rel,
        "action": action,
    }
    if auto_registered:
        result["auto_registered"] = True
        result["root"] = str(project_root)
    return result


def _anatomy_attach_for_load(scoped_root: Path, cwd: Path, max_tokens: int) -> dict:
    """Build the anatomy block returned by `load --anatomy`.

    Result keys:
      - matched (bool): a registered project's root contains cwd
      - slug, root, content, truncated when matched
      - hint (str) when unmatched and cwd is inside a git repo
    """
    slug, root = _anatomy_match_cwd(scoped_root, cwd)
    if slug and root:
        doc = _anatomy_load_doc(scoped_root, slug)
        if not doc:
            return {
                "matched": True,
                "slug": slug,
                "root": str(root),
                "warning": "registered but not yet scanned; run `memory_tool.py anatomy-scan {slug}`".format(slug=slug),
            }
        content, truncated = _anatomy_render_capped(doc, max_tokens)
        return {
            "matched": True,
            "slug": slug,
            "root": str(root),
            "truncated": truncated,
            "max_tokens": max_tokens,
            "content": content,
        }
    result: dict = {"matched": False}
    suggestion = _anatomy_suggest_for_hint(scoped_root, cwd)
    if suggestion:
        root_str = suggestion["root"]
        slug_use = suggestion["suggested_slug"]
        base = suggestion["base_slug"]
        conflict = suggestion["conflict"]
        lines = [
            "cwd is inside an unregistered project.",
            f"- Root: {root_str}",
        ]
        if slug_use:
            if conflict:
                lines.append(f"- Base slug `{base}` already registered to a different root.")
                lines.append(f"- Suggested unique slug: `{slug_use}`")
                lines.append(
                    f"- Command: memory_tool.py anatomy-register {root_str} --slug {slug_use}"
                )
            else:
                lines.append(f"- Suggested slug: `{slug_use}`")
                lines.append(f"- Command: memory_tool.py anatomy-register {root_str}")
        else:
            lines.append(f"- Base slug `{base}` and path-disambiguated alternatives are all taken.")
            lines.append(
                f"- Command: memory_tool.py anatomy-register {root_str} --slug <pick-a-unique-name>"
            )
        lines.append(
            "  (PostToolUse hooks will also auto-register on the next Write/Edit inside this repo.)"
        )
        result["hint"] = "\n".join(lines)
    elif _cwd_is_git_repo(cwd):
        result["hint"] = (
            "cwd is inside a git repo but no project marker found "
            "(pyproject.toml, package.json, Cargo.toml, go.mod, etc.). "
            "Run `memory_tool.py anatomy-register <root>` manually to opt in."
        )
    return result


# ============================================================================
# /Anatomy
# ============================================================================




def _search_sources(
    config: dict,
    query: str,
    *,
    search_docs: bool,
    search_memory: bool,
    search_log: bool,
    log_days: int | None = None,
    project_filter: list[str] | None = None,
    topic_filter: list[str] | None = None,
) -> dict:
    """Full-text search across configured namespace docs, MEMORY.md, and log JSONL.

    project_filter / topic_filter apply to log JSONL entries only (those fields
    do not have well-defined homes in MEMORY.md or docs/*.md yet). When either
    filter is non-empty, docs and memory hits are suppressed so the result set
    is unambiguously scoped to log entries — otherwise users would get
    misleading hits from unfiltered sources.
    """
    hits = []
    if not config:
        return {"query": query, "hits": [], "total": 0}

    primary_list, ref_list = collect_roots(config)
    validate_single_primary(primary_list, required=False)
    ordered_roots = primary_list + ref_list

    project_set = _normalize_axis_filter(project_filter)
    topic_set = _normalize_axis_filter(topic_filter)
    axes_scoped = bool(project_set or topic_set)
    # When the caller scopes by axes, restrict to log entries: only the log
    # carries project/topic metadata today. Suppressing docs/memory avoids
    # misleading "match" results from unfiltered sources.
    effective_search_docs = search_docs and not axes_scoped
    effective_search_memory = search_memory and not axes_scoped

    # --- <namespace>/docs/*.md ---
    if effective_search_docs:
        for root_cfg in ordered_roots:
            r_path = expand_path(root_cfg.get("path", ""))
            scoped_root = namespace_root(r_path, namespace_from_root(root_cfg))
            role = root_cfg.get("role", "reference")
            index_path = scoped_root / "docs" / "index.json"
            if not index_path.exists():
                continue
            index_source = read_json_source(index_path, "docs_index", role)
            if not index_source.get("loaded"):
                continue
            entries = normalize_doc_index(index_source["json"])
            for entry in entries:
                doc_path = doc_path_from_entry(scoped_root, entry)
                if doc_path is None or not doc_path.exists():
                    continue
                content = doc_path.read_text(encoding="utf-8")
                if query.lower() in content.lower():
                    snippet_start = max(0, content.lower().index(query.lower()) - 40)
                    snippet_end = min(len(content), snippet_start + 120)
                    hits.append({
                        "source": "docs",
                        "path": str(doc_path),
                        "title": entry.get("title", ""),
                        "type": entry.get("type", ""),
                        "snippet": content[snippet_start:snippet_end].strip(),
                        "score": 1,
                    })

    # --- <namespace>/MEMORY.md ---
    if effective_search_memory:
        for root_cfg in ordered_roots:
            r_path = expand_path(root_cfg.get("path", ""))
            scoped_root = namespace_root(r_path, namespace_from_root(root_cfg))
            role = root_cfg.get("role", "reference")
            mem_path = scoped_root / "MEMORY.md"
            if not mem_path.exists():
                continue
            mem_source = read_source(mem_path, "durable_memory", role)
            if not mem_source.get("loaded"):
                continue
            for line in mem_source["content"].splitlines():
                if query.lower() in line.lower():
                    hits.append({
                        "source": "MEMORY.md",
                        "path": str(mem_path),
                        "snippet": line.strip(),
                        "score": 1,
                    })

    # --- <namespace>/log/*.jsonl ---
    if search_log and primary_list:
        primary_root = expand_path(primary_list[0].get("path", ""))
        primary_namespace = namespace_from_root(primary_list[0])
        scoped_root = namespace_root(primary_root, primary_namespace)
        if log_days:
            target = date.today()
            start = target - timedelta(days=log_days - 1)
            date_list = date_range(start, target)
        else:
            date_list = [date.today() - timedelta(days=i) for i in range(2)]
        for d in date_list:
            jsonl_path = scoped_root / "log" / f"{d:%Y-%m-%d}.jsonl"
            if not jsonl_path.exists():
                continue
            try:
                lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for lineno, line in enumerate(lines, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = entry.get("text", "")
                if query.lower() not in text.lower():
                    continue
                if project_set is not None:
                    proj = entry.get("project")
                    if not proj or proj.lower() not in project_set:
                        continue
                if topic_set is not None:
                    tp = entry.get("topic")
                    if not tp or tp.lower() not in topic_set:
                        continue
                hit = {
                    "source": "log",
                    "path": str(jsonl_path),
                    "line": lineno,
                    "snippet": text[:120],
                    "score": 1,
                }
                anatomy_links = _anatomy_link_snapshots_for_entry(scoped_root, text)
                if anatomy_links:
                    hit["anatomy_links"] = anatomy_links
                hits.append(hit)

    return {
        "query": query,
        "hits": hits,
        "total": len(hits),
        "scope": {
            "docs": "primary_and_reference" if search_docs else "disabled",
            "memory": "primary_and_reference" if search_memory else "disabled",
            "log": "primary_only" if search_log else "disabled",
        },
    }


def do_search(args: argparse.Namespace) -> dict:
    config = load_config(Path(args.config) if args.config else None, os.environ.get("USING_MEMORY_CONFIG"))
    return _search_sources(
        config=config,
        query=args.query,
        search_docs=not args.no_docs,
        search_memory=not args.no_memory,
        search_log=not args.no_log,
        log_days=args.log_days,
        project_filter=getattr(args, "project", None),
        topic_filter=getattr(args, "topic", None),
    )


def do_maintain(args: argparse.Namespace) -> dict:
    """Run maintenance checks and repair missing docs index entries.

    With ``--distill`` only, skip the audit and return the bucket analysis.
    With ``--promote TOPIC[/FAMILY]``, synthesize a promote prompt for one
    bucket and return it as structured data (also printed on stdout by main).
    """
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)

    # Distill / promote are read-only fast paths; they skip the audit so
    # SessionStart / Stop hooks can call them frequently without paying the
    # full anatomy-walk cost.
    if getattr(args, "promote", None):
        return do_promote(scoped_root, args)
    if getattr(args, "distill", False):
        return do_distill(scoped_root, args)
    log_dir = scoped_root / "log"
    stale = []
    corrupt = []
    ok_count = 0

    if log_dir.is_dir():
        for jsonl_path in sorted(log_dir.glob("*.jsonl")):
            if not jsonl_path.is_file():
                continue
            try:
                lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            except Exception as exc:
                corrupt.append({"path": str(jsonl_path), "error": str(exc)})
                continue
            for lineno, raw_line in enumerate(lines, 1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    corrupt.append({"path": str(jsonl_path), "line": lineno, "error": exc.msg})
                    continue
                for f_path in entry.get("files", []):
                    candidate = resolve_primary_file_reference(scoped_root, f_path)
                    if candidate is None:
                        stale.append({
                            "path": str(jsonl_path),
                            "line": lineno,
                            "file": f_path,
                            "text": entry.get("text", "")[:80],
                            "error": "invalid file reference",
                        })
                        continue
                    if not candidate.exists():
                        stale.append({
                            "path": str(jsonl_path),
                            "line": lineno,
                            "file": f_path,
                            "text": entry.get("text", "")[:80],
                        })
                ok_count += 1

    indexed_docs = maintain_doc_index(scoped_root)
    anatomy_report = _maintain_anatomy(scoped_root)
    return {
        "stale": stale,
        "corrupt": corrupt,
        "ok": ok_count,
        "indexed_docs": indexed_docs,
        "anatomy": anatomy_report,
    }


def _maintain_anatomy(scoped_root: Path) -> dict:
    """Audit registered anatomy projects and surface drift.

    Returns:
      - projects: list of {slug, root, missing_root, scanned, file_count,
        stale_files, new_files, broken_anatomy_refs}
      - broken_log_refs: [[anatomy:slug/rel]] references in log/*.jsonl whose
        slug or file no longer exists in the anatomy snapshot.
    """
    report: dict = {"projects": [], "broken_log_refs": []}
    index = _anatomy_load_index(scoped_root)
    for slug in sorted(index.keys()):
        info = index[slug] or {}
        raw_root = info.get("root")
        proj: dict = {"slug": slug, "root": raw_root}
        if not raw_root:
            proj["error"] = "no root recorded"
            report["projects"].append(proj)
            continue
        root = Path(raw_root).expanduser()
        if not root.is_dir():
            proj["missing_root"] = True
            report["projects"].append(proj)
            continue
        doc = _anatomy_load_doc(scoped_root, slug)
        if not doc:
            proj["scanned"] = False
            report["projects"].append(proj)
            continue
        proj["scanned"] = True
        files = doc.get("files", {}) or {}
        proj["file_count"] = len(files)

        # Re-walk the project once and diff against the snapshot.
        live_rels: set[str] = set()
        for path, rel in _anatomy_walk(root):
            live_rels.add(rel)
        snapshot_rels = set(files.keys())
        stale = sorted(snapshot_rels - live_rels)
        new = sorted(live_rels - snapshot_rels)
        if stale:
            proj["stale_files"] = stale[:50]
            proj["stale_files_total"] = len(stale)
        if new:
            proj["new_files"] = new[:50]
            proj["new_files_total"] = len(new)
        report["projects"].append(proj)

    # Scan log entries for [[anatomy:slug/rel]] refs whose target no longer
    # exists. This is the "log → anatomy drift" check.
    log_dir = scoped_root / "log"
    cache: dict[str, dict] = {}
    if log_dir.is_dir():
        for jsonl_path in sorted(log_dir.glob("*.jsonl")):
            if not jsonl_path.is_file():
                continue
            try:
                lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for lineno, raw_line in enumerate(lines, 1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                text = entry.get("text", "")
                if "[[anatomy:" not in text:
                    continue
                for m in _ANATOMY_REF_RE.finditer(text):
                    slug = m.group(1)
                    rel = m.group(2).strip()
                    doc = cache.get(slug)
                    if doc is None:
                        doc = _anatomy_load_doc(scoped_root, slug) or {}
                        cache[slug] = doc
                    files = doc.get("files", {}) if isinstance(doc, dict) else {}
                    if rel in files:
                        continue
                    report["broken_log_refs"].append({
                        "path": str(jsonl_path),
                        "line": lineno,
                        "slug": slug,
                        "rel": rel,
                        "reason": "slug not registered" if not doc else "file not in anatomy snapshot",
                    })
    return report


# ============================================================================
# Distillation: log -> doc bucket analysis
# ============================================================================
#
# distill: read-only bucket analysis. Groups unpromoted log entries by
#   (topic, tag-family) and reports candidates that have accumulated enough
#   material (>= min-entries, >= min-days) to be worth synthesizing into a
#   doc. Updates last_distill_check_ts on STATS.json.
#
# promote: read-only synthesis of a prompt for one bucket. Returns
#   structured markdown that a session-side LLM (typically a subagent)
#   reads to decide whether to call upsert-doc. Never writes docs itself.
#
# Both stages are deliberately separated by two decision gates: distill
# proposes, the main session decides whether to delegate, the subagent
# decides whether to land. See SKILL.md "Distillation Pipeline".

# Tag families collapse the 26 log tags into 4 doc-shaped buckets. Tags
# not listed here (progress, state, output, note, context, ...) are skipped
# on purpose — they are noise-prone or already covered by other tags.
_TAG_FAMILIES: dict[str, str] = {
    "lesson": "lesson", "pattern": "lesson", "insight": "lesson",
    "fix": "troubleshooting", "debug": "troubleshooting", "error": "troubleshooting",
    "decision": "decision", "analysis": "decision", "consideration": "decision",
    "operation": "runbook", "build": "runbook", "deploy": "runbook",
    "commit": "runbook", "release": "runbook", "verification": "runbook",
    "fact": "lesson",
}


def _read_log_entries_with_lineno(log_dir: Path) -> list[dict]:
    """Walk log/*.jsonl and return parsed entries with `_path` and `_lineno`.

    Corrupt lines and missing files are skipped silently — distill is a
    read-only side-channel, it should never block on bad data. Built on the
    shared ``iter_log_entries`` funnel (see memory_lib/core.py).
    """
    out: list[dict] = []
    for path, lineno, entry in iter_log_entries(log_dir, with_lineno=True):
        entry["_path"] = str(path)
        entry["_lineno"] = lineno
        out.append(entry)
    return out


def _bucket_score(entries: list[dict]) -> float:
    """Score a candidate bucket. Higher = more promotion-worthy.

    Components:
      - unique-files count (signal of breadth)
      - lesson/decision-family tag ratio (signal of distilled content)
      - average confidence (caller-provided)
    Confidence and ratio are normalized so a 5-entry bucket with all lessons
    at confidence 8 scores roughly the same as a 10-entry runbook bucket.
    """
    if not entries:
        return 0.0
    files: set[str] = set()
    confidence_sum = 0.0
    confidence_count = 0
    high_value_count = 0
    for e in entries:
        for f in e.get("files") or []:
            if isinstance(f, str) and f.strip():
                files.add(f.strip())
        c = e.get("confidence")
        if isinstance(c, (int, float)) and 1 <= c <= 10:
            confidence_sum += float(c)
            confidence_count += 1
        if e.get("tag") in {"lesson", "pattern", "insight", "decision", "analysis"}:
            high_value_count += 1
    avg_conf = (confidence_sum / confidence_count) if confidence_count else 5.0
    high_value_ratio = high_value_count / len(entries)
    return round(len(files) * 1.0 + high_value_ratio * 5.0 + avg_conf * 0.5, 2)


def _suggest_doc_type(family: str) -> str:
    return {
        "lesson": "lesson",
        "troubleshooting": "troubleshooting",
        "decision": "decision-record",
        "runbook": "runbook",
    }.get(family, "wiki")


def _suggest_slug(topic: str, family: str) -> str:
    """Return a deterministic, valid doc slug for a bucket. The caller is
    free to pick a different one when calling upsert-doc."""
    base = f"{topic}-{family}"
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", base.lower()).strip("-")
    return cleaned or "rollup"


def _build_distill_buckets(
    entries: list[dict],
    promoted_refs: set[tuple[str, int]],
    min_entries: int,
    min_days: int,
) -> list[dict]:
    """Group entries by (topic, family), filter, score, and sort.

    Returns a list of bucket dicts with: topic, family, count, day_span,
    score, suggested_doc_type, suggested_slug, suggested_project, entries
    (each with date, lineno, tag, confidence, files, text_preview).
    """
    buckets: dict[tuple[str, str], list[dict]] = {}
    for e in entries:
        topic = e.get("topic")
        tag = e.get("tag")
        # Older entries pre-date auto-routing and have no topic field. Try
        # the same regex inference write-log would have used on creation,
        # so historical data isn't permanently invisible to distill.
        if not isinstance(topic, str) or not topic:
            topic = _infer_topic_from_text(e.get("text") or "", tag or "")
        family = _TAG_FAMILIES.get(tag or "")
        if not topic or not family:
            continue
        date_str = e.get("date")
        try:
            line_no = int(e.get("_lineno") or 0)
        except (TypeError, ValueError):
            line_no = 0
        if isinstance(date_str, str) and line_no and (date_str, line_no) in promoted_refs:
            continue
        buckets.setdefault((topic, family), []).append(e)

    out: list[dict] = []
    for (topic, family), bucket in buckets.items():
        if len(bucket) < min_entries:
            continue
        # Compute day span: distinct YYYY-MM-DD count is more meaningful than
        # max-min for sparse activity (5 entries on the same day shouldn't pass
        # min_days=3).
        dates = sorted({e.get("date") for e in bucket if isinstance(e.get("date"), str)})
        if len(dates) < min_days:
            continue
        score = _bucket_score(bucket)
        bucket_sorted = sorted(bucket, key=lambda e: (e.get("date") or "", e.get("_lineno") or 0))

        # Pick the most common project as the suggested doc project, if any.
        project_counts: dict[str, int] = {}
        for e in bucket_sorted:
            p = e.get("project")
            if isinstance(p, str) and p:
                project_counts[p] = project_counts.get(p, 0) + 1
        suggested_project = max(project_counts.items(), key=lambda kv: kv[1])[0] if project_counts else None

        out.append({
            "topic": topic,
            "family": family,
            "count": len(bucket_sorted),
            "day_span": len(dates),
            "score": score,
            "suggested_doc_type": _suggest_doc_type(family),
            "suggested_slug": _suggest_slug(topic, family),
            "suggested_project": suggested_project,
            "entries": [
                {
                    "date": e.get("date"),
                    "lineno": e.get("_lineno"),
                    "tag": e.get("tag"),
                    "confidence": e.get("confidence"),
                    "files": e.get("files") or [],
                    "text_preview": (e.get("text") or "").strip().splitlines()[0][:120] if e.get("text") else "",
                }
                for e in bucket_sorted
            ],
        })

    # Sort: highest score first, then largest count, then topic alpha.
    out.sort(key=lambda b: (-b["score"], -b["count"], b["topic"]))
    return out


def do_distill(scoped_root: Path, args: argparse.Namespace) -> dict:
    """Read-only bucket analysis. Updates last_distill_check_ts."""
    log_dir = scoped_root / "log"
    entries = _read_log_entries_with_lineno(log_dir)
    promoted = collect_promoted_log_refs(scoped_root)
    min_entries = max(1, int(getattr(args, "min_entries", 3) or 3))
    min_days = max(1, int(getattr(args, "min_days", 3) or 3))
    buckets = _build_distill_buckets(entries, promoted, min_entries, min_days)

    now_ts = datetime.now().astimezone().isoformat(timespec="seconds")
    _bump_lifetime_stats(
        scoped_root,
        {},
        sets={"last_distill_check_ts": now_ts},
        machine_id=_primary_machine_id(args),
    )

    return {
        "mode": "distill",
        "checked_at": now_ts,
        "total_log_entries": len(entries),
        "promoted_log_entries": len(promoted),
        "min_entries": min_entries,
        "min_days": min_days,
        "buckets": buckets,
    }


def do_promote(scoped_root: Path, args: argparse.Namespace) -> dict:
    """Synthesize a promote prompt for one distill bucket.

    Output is structured markdown suitable for a subagent to read, decide,
    and (if it judges the material worth landing) call upsert-doc with
    --link-log refs to all source entries. This function never writes docs.

    The ``--promote`` argument is ``TOPIC[/FAMILY]``. Bare ``TOPIC`` picks
    the highest-scoring family with that topic. ``FAMILY`` must be one of
    {lesson, troubleshooting, decision, runbook}.
    """
    raw = (args.promote or "").strip()
    if not raw:
        return {"mode": "promote", "error": "empty topic"}
    if "/" in raw:
        topic, family = raw.split("/", 1)
        topic = topic.strip()
        family = family.strip()
    else:
        topic = raw
        family = ""

    log_dir = scoped_root / "log"
    entries = _read_log_entries_with_lineno(log_dir)
    promoted = collect_promoted_log_refs(scoped_root)
    min_entries = max(1, int(getattr(args, "min_entries", 3) or 3))
    min_days = max(1, int(getattr(args, "min_days", 3) or 3))
    buckets = _build_distill_buckets(entries, promoted, min_entries, min_days)

    matching = [b for b in buckets if b["topic"] == topic and (not family or b["family"] == family)]
    if not matching:
        # Be helpful: list known topics so a typo is easy to spot.
        seen_topics = sorted({b["topic"] for b in buckets})
        return {
            "mode": "promote",
            "error": f"no candidate bucket for topic={topic!r}"
                     + (f" family={family!r}" if family else ""),
            "available_topics": seen_topics,
        }
    bucket = matching[0]  # already score-sorted; take the highest

    prompt = _render_promote_prompt(scoped_root, bucket)
    payload_size = len(prompt.encode("utf-8"))

    return {
        "mode": "promote",
        "topic": bucket["topic"],
        "family": bucket["family"],
        "count": bucket["count"],
        "day_span": bucket["day_span"],
        "score": bucket["score"],
        "suggested_doc_type": bucket["suggested_doc_type"],
        "suggested_slug": bucket["suggested_slug"],
        "suggested_project": bucket["suggested_project"],
        "link_log_refs": [format_log_backlink(e["date"], e["lineno"]) for e in bucket["entries"]],
        "prompt": prompt,
        "prompt_bytes": payload_size,
    }


def _render_promote_prompt(scoped_root: Path, bucket: dict) -> str:
    """Build the structured markdown prompt the subagent will read.

    The prompt embeds full ``text`` bodies of every bucket entry (loaded
    fresh from disk so it isn't truncated like the distill text_preview),
    a header with bucket stats, suggested frontmatter for upsert-doc, and
    a closing instructions block telling the subagent what to do.
    """
    log_dir = scoped_root / "log"
    # Re-read full text bodies for the entries (distill only keeps a 120-char
    # preview to keep the bucket-summary cheap).
    by_path: dict[str, list[int]] = {}
    for e in bucket["entries"]:
        # We stored only date+lineno; reconstruct path from date.
        path = log_dir / f"{e['date']}.jsonl"
        by_path.setdefault(str(path), []).append(e["lineno"])
    full_entries: list[dict] = []
    for path_str, linenos in by_path.items():
        try:
            lines = Path(path_str).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for ln in linenos:
            if 1 <= ln <= len(lines):
                try:
                    parsed = json.loads(lines[ln - 1])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    parsed["_lineno"] = ln
                    full_entries.append(parsed)
    full_entries.sort(key=lambda e: (e.get("date") or "", e.get("_lineno") or 0))

    size_bytes = sum(len((e.get("text") or "").encode("utf-8")) for e in full_entries)
    subagent_hint = (
        "💡 SUBAGENT-RECOMMENDED: this prompt is "
        f"~{max(1, size_bytes // 1024)} KB. To keep the main session lean, delegate "
        "via Agent(subagent_type=\"general-purpose\"): the subagent reads this prompt, "
        "decides whether the material is worth landing, and on yes calls "
        "upsert-doc with --link-log refs to every source entry."
    )

    lines: list[str] = []
    lines.append(f"# Distillation prompt: {bucket['topic']} / {bucket['family']}")
    lines.append("")
    lines.append(subagent_hint)
    lines.append("")
    lines.append("## Bucket")
    lines.append(f"- topic: `{bucket['topic']}`")
    lines.append(f"- family: `{bucket['family']}`")
    lines.append(f"- entries: {bucket['count']} across {bucket['day_span']} day(s)")
    lines.append(f"- score: {bucket['score']}")
    lines.append("")
    lines.append("## Suggested upsert-doc parameters")
    lines.append(f"- `--doc {bucket['suggested_slug']}`")
    lines.append(f"- `--doc-type {bucket['suggested_doc_type']}`")
    if bucket.get("suggested_project"):
        lines.append(f"- `--project {bucket['suggested_project']}`")
    lines.append("- `--link-log` (one per source entry; full list at the bottom of this prompt)")
    lines.append("")
    lines.append("## Source log entries (full text)")
    lines.append("")
    for e in full_entries:
        ts = e.get("ts") or e.get("date") or ""
        tag = e.get("tag") or ""
        lvl = e.get("level") or ""
        files = ", ".join(e.get("files") or []) or "—"
        ref = format_log_backlink(e.get("date"), int(e["_lineno"]))
        lines.append(f"### {ref}  ·  {ts}  ·  tag={tag}  ·  level={lvl}")
        lines.append(f"_files_: {files}")
        lines.append("")
        lines.append((e.get("text") or "").rstrip())
        lines.append("")
    lines.append("## All --link-log refs (copy verbatim into upsert-doc)")
    lines.append("")
    for e in full_entries:
        lines.append(f"- `--link-log '{format_log_backlink(e.get('date'), int(e['_lineno']))}'`")
    lines.append("")
    lines.append("## Instructions for the subagent")
    lines.append("")
    lines.append(
        "1. Read the source entries above end-to-end. They are all real operations "
        "from this project; do not fabricate or speculate beyond what the text says."
    )
    lines.append(
        "2. Decide whether they cohere into a single useful doc. If the bucket is "
        "actually 3+ unrelated topics that share a label, return a one-line summary "
        "explaining the mismatch and DO NOT call upsert-doc."
    )
    lines.append(
        "3. If they do cohere, synthesize ONE markdown body. Match the doc-type: "
        "`lesson` -> What we learned + When it applies; `troubleshooting` -> "
        "Symptom / Root cause / Fix; `decision-record` -> Context / Options / "
        "Decision / Consequences; `runbook` -> Prereqs / Steps / Verification."
    )
    lines.append(
        "4. Cite each source entry inline using its `[[log:YYYY-MM-DD#L<n>]]` ref."
    )
    lines.append(
        "5. Call `memory_tool.py upsert-doc --doc <slug> --text-stdin "
        "--doc-type <type> [--project <slug>] --link-log <ref> ...` with one "
        "`--link-log` per source entry. Pipe the synthesized body via stdin."
    )
    lines.append(
        "6. Return ONLY the final doc slug + one sentence summarizing what was "
        "written. The main session does not need to see the body."
    )
    return "\n".join(lines)


def _collect_stats(config: dict | None) -> dict:
    """Count configured namespace log JSONL entries and MEMORY.md lines by tag."""
    log_tags: dict = {}
    memory_tags: dict = {}
    total_log = 0
    total_memory = 0

    if not config:
        return {
            "log": {"total": 0, "by_tag": {}},
            "memory": {"total": 0, "by_tag": {}},
            "scope": {"log": "primary_only", "memory": "primary_only"},
        }

    primary_list, _ = collect_roots(config)
    validate_single_primary(primary_list, required=False)
    ordered_roots = primary_list + []

    for root_cfg in ordered_roots:
        r_path = expand_path(root_cfg.get("path", ""))
        scoped_root = namespace_root(r_path, namespace_from_root(root_cfg))
        log_dir = scoped_root / "log"
        if log_dir.is_dir():
            for jsonl_path in log_dir.glob("*.jsonl"):
                try:
                    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        entry = json.loads(line)
                        tag = entry.get("tag", "unknown")
                        log_tags[tag] = log_tags.get(tag, 0) + 1
                        total_log += 1
                except Exception:
                    continue

        mem_path = scoped_root / "MEMORY.md"
        if mem_path.is_file():
            for line in mem_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("- [") and "] " in line:
                    tag = line[3:].split("]")[0].split("|")[0].lower()
                    memory_tags[tag] = memory_tags.get(tag, 0) + 1
                    total_memory += 1

    return {
        "log": {"total": total_log, "by_tag": log_tags},
        "memory": {"total": total_memory, "by_tag": memory_tags},
        "scope": {"log": "primary_only", "memory": "primary_only"},
    }


def do_stats(args: argparse.Namespace) -> dict:
    config = load_config(Path(args.config) if args.config else None, os.environ.get("USING_MEMORY_CONFIG"))
    return _collect_stats(config)


def _format_export(stats: dict, config: dict | None) -> str:
    lines = ["## Project Memory Snapshot\n"]
    log = stats.get("log", {})
    memory = stats.get("memory", {})
    lines.append(f"**Log JSONL entries:** {log.get('total', 0)}")
    lines.append(f"**MEMORY.md entries:** {memory.get('total', 0)}\n")

    for section, label in [("log", "Log tags"), ("memory", "MEMORY.md tags")]:
        by_tag = stats.get(section, {}).get("by_tag", {})
        if by_tag:
            lines.append(f"### {label}")
            for tag, count in sorted(by_tag.items(), key=lambda x: -x[1]):
                lines.append(f"- **[{tag}]**: {count}")
            lines.append("")
    return "\n".join(lines)


def do_export(args: argparse.Namespace) -> dict:
    config = load_config(Path(args.config) if args.config else None, os.environ.get("USING_MEMORY_CONFIG"))
    stats = _collect_stats(config)
    text = _format_export(stats, config)
    if args.dest:
        dest = Path(args.dest)
        with exclusive_file_lock(lock_path_for(dest)):
            existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
            separator = "\n\n---\n\n" if existing.strip() else ""
            atomic_write_text(dest, existing + separator + text)
        return {"changed": True, "dest": str(dest)}
    return {"text": text}


def default_machine_id() -> str:
    host = socket.gethostname().split(".")[0].strip()
    return host or "local-main"


def prompt_value(label: str, default: str = "", *, required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        raw = input(f"{label}{suffix}: ").strip()
        value = raw or default
        if value or not required:
            return value
        print(f"{label} is required.", file=sys.stderr)


def git_run(args: list[str], *, cwd: Path | None = None) -> None:
    try:
        subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        sys.stderr.write("git command not found; install Git before setting up using-memory storage\n")
        sys.exit(2)
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            sys.stderr.write(exc.stderr)
        sys.stderr.write(f"git command failed ({exc.returncode}): {' '.join(args)}\n")
        sys.exit(exc.returncode or 2)


def git_output(args: list[str], *, cwd: Path | None = None) -> str:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    return proc.stdout.strip()


def path_is_empty(path: Path) -> bool:
    return not path.exists() or (path.is_dir() and not any(path.iterdir()))


def prepare_git_memory_root(memory_root: Path, remote: str) -> str:
    memory_root = memory_root.expanduser()
    if remote:
        if memory_root.exists() and (memory_root / ".git").is_dir():
            existing = git_output(["git", "remote", "get-url", "origin"], cwd=memory_root)
            if not existing:
                git_run(["git", "remote", "add", "origin", remote], cwd=memory_root)
            git_run(["git", "pull", "--ff-only"], cwd=memory_root)
            return "pulled"
        if path_is_empty(memory_root):
            memory_root.parent.mkdir(parents=True, exist_ok=True)
            git_run(["git", "clone", remote, str(memory_root)])
            return "cloned"
        sys.stderr.write(
            f"memory path exists but is not an empty directory or Git repo: {memory_root}\n"
        )
        sys.exit(2)

    memory_root.mkdir(parents=True, exist_ok=True)
    if not (memory_root / ".git").is_dir():
        git_run(["git", "init"], cwd=memory_root)
        return "initialized"
    return "exists"


def initialize_namespace(memory_root: Path, namespace: str, machine_id: str) -> list[str]:
    scoped_root = namespace_root(memory_root, namespace)
    changed = []
    for rel in ["docs", "log"]:
        target = scoped_root / rel
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            changed.append(str(target))

    seed_files = {
        scoped_root / "PREFERENCES.md": "# Preferences\n\n",
        scoped_root / "MEMORY.md": "# Memory\n\n",
        scoped_root / "docs" / "index.json": json.dumps(
            {"version": 1, "documents": []}, ensure_ascii=False, indent=2
        )
        + "\n",
    }
    for path, content in seed_files.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            changed.append(str(path))
    return changed


def write_setup_config(config_path: Path, memory_root: Path, namespace: str, machine_id: str, remote: str) -> None:
    config_path = config_path.expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    root_entry = {
        "path": str(memory_root),
        "role": "primary",
        "writable": True,
        "namespace": namespace,
        "machine_id": machine_id,
        "priority": 100,
    }
    if remote:
        root_entry["remote"] = remote
    data = {
        "version": 1,
        "memory_roots": [root_entry],
        "defaults": {
            "read_today": True,
            "read_yesterday": True,
            "load_docs_on_demand": True,
        },
        "features": {
            "anatomy": {
                "enabled": False,
                "session_start_attach": False,
                "post_tool_upsert": False,
                "auto_register": False,
            },
        },
        "logging": {
            "silent_summary": False,
            "detail_turn_interval": 20,
            "hard_gate": {
                "memory_prompt": True,
                "important_interval": True,
            },
        },
        "session_archive": {
            "enabled": False,
            "mode": "pointer",
            "auto_load": False,
            "index_events": True,
        },
    }
    config_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def do_setup(args: argparse.Namespace) -> dict:
    env_config = os.environ.get("USING_MEMORY_CONFIG")
    config_path = expand_path(args.config or env_config or DEFAULT_CONFIG_PATH)
    config_exists = config_path.exists()
    if config_exists and not args.force:
        return {
            "changed": False,
            "config": str(config_path),
            "message": "config already exists; rerun setup with --force to replace it",
        }

    interactive = sys.stdin.isatty() and not args.non_interactive
    if not interactive and not args.path:
        return {
            "changed": False,
            "config": str(config_path),
            "message": "setup needs --path when not running interactively",
        }

    print("using-memory first-time storage setup", file=sys.stderr)
    raw_path = args.path or prompt_value("Memory repo path", "~/.memories", required=True)
    if args.remote is not None:
        raw_remote = args.remote
    elif interactive:
        raw_remote = prompt_value("Remote Git repo URL (optional)", "")
    else:
        raw_remote = ""
    raw_namespace = args.namespace or (prompt_value("Namespace", DEFAULT_NAMESPACE, required=True) if interactive else DEFAULT_NAMESPACE)
    machine_id = args.machine_id or (prompt_value("Machine ID", default_machine_id(), required=True) if interactive else default_machine_id())

    memory_root = expand_path(raw_path).resolve(strict=False)
    namespace = namespace_from_root({"namespace": raw_namespace})
    remote = raw_remote.strip()

    git_action = prepare_git_memory_root(memory_root, remote)
    seeded = initialize_namespace(memory_root, namespace, machine_id)
    write_setup_config(config_path, memory_root, namespace, machine_id, remote)

    next_steps = []
    if not remote:
        next_steps.append(
            "Create a remote Git repository later, then run: "
            f"git -C {memory_root} remote add origin <url> && git -C {memory_root} push -u origin main"
        )
    return {
        "changed": True,
        "config": str(config_path),
        "memory_root": str(memory_root),
        "namespace": namespace,
        "machine_id": machine_id,
        "remote": remote,
        "git_action": git_action,
        "seeded": seeded,
        "message": "setup complete",
        "next_steps": next_steps,
    }


def cmd_setup(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("setup", help="Configure the memory repo path, optional remote Git repo, namespace, and machine ID")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--path", type=str, default=None, help="Memory repo checkout path, for example ~/.memories")
    p.add_argument("--remote", type=str, default=None, help="Optional remote Git URL to clone or pull")
    p.add_argument("--namespace", type=str, default=None, help="Single namespace path segment, default main")
    p.add_argument("--machine-id", type=str, default=None)
    p.add_argument("--force", action="store_true", help="Replace an existing config file")
    p.add_argument("--non-interactive", action="store_true", help="Do not prompt; fail gracefully when required args are missing")
    p.add_argument("--json", action="store_true")


def cmd_search(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("search", help="Full-text search across configured namespace docs, MEMORY.md and log JSONL")
    p.add_argument("query", type=str, help="Search term")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--log-days", type=int, default=None)
    p.add_argument("--no-docs", action="store_true")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument("--no-log", action="store_true")
    p.add_argument(
        "--project",
        action="append",
        default=None,
        help="Filter log entries by project axis (repeatable). Implies --no-docs --no-memory: matched scope becomes log-only.",
    )
    p.add_argument(
        "--topic",
        action="append",
        default=None,
        help="Filter log entries by topic axis (repeatable). Implies --no-docs --no-memory: matched scope becomes log-only.",
    )
    p.add_argument("--json", action="store_true")


def cmd_maintain(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("maintain", help="Run maintenance checks and repair missing docs index entries")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--distill", action="store_true",
                   help="Skip audit; run distillation bucket analysis only. "
                        "Reports candidate (topic, tag-family) buckets that have accumulated "
                        "enough unpromoted log entries to be worth synthesizing into a doc.")
    p.add_argument("--promote", type=str, default=None, metavar="TOPIC",
                   help="Synthesize a promote prompt for one distill bucket. "
                        "Format: TOPIC[/FAMILY] (e.g. 'hooks/lesson'). Bare TOPIC picks "
                        "the highest-scoring family. Output is structured markdown on stdout; "
                        "no docs are written — let a subagent decide and call upsert-doc.")
    p.add_argument("--min-entries", type=int, default=3,
                   help="Minimum entries in a bucket to qualify (default 3).")
    p.add_argument("--min-days", type=int, default=3,
                   help="Minimum time span in days for a bucket to qualify (default 3).")
    p.add_argument("--json", action="store_true")


def cmd_stats(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("stats", help="Summary statistics for configured namespace log JSONL and MEMORY.md")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--json", action="store_true")


def cmd_export(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("export", help="Export memory stats as Markdown")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--dest", type=str, default=None)
    p.add_argument("--json", action="store_true")


def cmd_load(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("load", help="Scan config and print a structured memory snapshot")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--date", type=str, default=None)
    p.add_argument("--log-from", type=str, default=None)
    p.add_argument("--log-to", type=str, default=None)
    p.add_argument("--log-days", type=int, default=None)
    p.add_argument("--log-query", type=str, default=None)
    p.add_argument("--doc", type=str, default=None)
    p.add_argument("--doc-type", type=str, default=None)
    p.add_argument("--doc-tag", action="append", default=None)
    p.add_argument(
        "--project",
        action="append",
        default=None,
        help="Filter docs index by project tag AND filter log entries by project axis (repeatable).",
    )
    p.add_argument(
        "--topic",
        action="append",
        default=None,
        help="Filter log entries by topic axis (repeatable). Does not affect docs.",
    )
    p.add_argument("--doc-query", type=str, default=None)
    p.add_argument(
        "--anatomy",
        action="store_true",
        help="Attach the anatomy snapshot for the project whose root contains cwd (longest-prefix match against the registered anatomy index). Falls back to a hint when cwd is in an unregistered git repo.",
    )
    p.add_argument(
        "--cwd",
        type=str,
        default=None,
        help="Override the cwd used for --anatomy matching. Defaults to the actual cwd.",
    )
    p.add_argument(
        "--anatomy-max-tokens",
        type=int,
        default=None,
        help="Token cap for the attached anatomy markdown (default 2000). Over-budget anatomies fall back to a top-level-directory summary.",
    )
    p.add_argument("--json", action="store_true")


def cmd_write_log(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("write-log", help="Append one entry to the primary repo's configured namespace log note (JSONL)")
    p.add_argument("--config", type=str, required=True)
    p.add_argument("--date", type=str, required=True)
    p.add_argument("--tag", type=str, required=True)
    p.add_argument("--level", choices=("detail", "summary"), default="detail")
    p.add_argument("--text", type=str, required=True)
    p.add_argument("--confidence", type=int, default=None)
    p.add_argument("--source", type=str, default=None)
    p.add_argument("--files", action="append", default=None)
    p.add_argument(
        "--project",
        type=str,
        default=None,
        help="Optional project axis (lowercase, [a-z0-9._-], 1..64 chars). Used by search/load --project filters. Auto-routed from cwd / --files if omitted.",
    )
    p.add_argument(
        "--topic",
        type=str,
        default=None,
        help="Optional topic axis (lowercase, [a-z0-9._-], 1..64 chars). Used by search/load --topic filters. Auto-routed from text keywords if omitted.",
    )
    p.add_argument(
        "--cwd",
        type=str,
        default=None,
        help="Override cwd used for project auto-routing. Defaults to actual cwd.",
    )
    p.add_argument("--json", action="store_true")


def cmd_write_memory(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("write-memory", help="Append one durable entry to the configured namespace MEMORY.md")
    p.add_argument("--config", type=str, required=True)
    p.add_argument("--date", type=str, required=True)
    p.add_argument("--tag", type=str, required=True)
    p.add_argument("--text", type=str, required=True)
    p.add_argument("--json", action="store_true")


def cmd_write_preference(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("write-preference", help="Append one stable preference to the configured namespace PREFERENCES.md")
    p.add_argument("--config", type=str, required=True)
    p.add_argument("--date", type=str, default=None,
                   help="YYYY-MM-DD; defaults to today. Recorded as the preference's effective date.")
    p.add_argument("--text", type=str, required=True)
    p.add_argument("--json", action="store_true")


def cmd_upsert_doc(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("upsert-doc", help="Write one configured namespace docs/* file and update <namespace>/docs/index.json")
    p.add_argument("--config", type=str, default=None,
                   help="Config path. Falls back to USING_MEMORY_CONFIG env or ~/.skills/using-memory/config.yaml.")
    p.add_argument("--doc", type=str, required=True,
                   help="Doc rel path. Extension defaults to .md when omitted. "
                        "Supported: .md, .html, .htm, .txt.")
    p.add_argument("--title", type=str, default=None,
                   help="Optional. Defaults to first H1 (md), <title>/<h1> (html), first non-empty line (txt), then slug-derived title.")
    p.add_argument("--doc-type", type=str, default=None,
                   help="Optional. Defaults to 'wiki'. Common values: wiki, lesson, troubleshooting, decision-record, runbook, SOP, project.")
    p.add_argument("--modified", type=str, default=None,
                   help="Optional ISO date (YYYY-MM-DD). Defaults to today.")
    p.add_argument("--created", type=str, default=None,
                   help="Optional ISO date (YYYY-MM-DD). Defaults to today for new docs and preserves the existing created date on edit.")
    p.add_argument("--project", action="append", default=None)
    p.add_argument("--doc-tag", action="append", default=None)
    p.add_argument("--summary", type=str, default=None)
    p.add_argument("--text", type=str, default=None,
                   help="Doc body. Required unless --text-stdin is set.")
    p.add_argument("--text-stdin", action="store_true",
                   help="Read --text body from stdin instead of inline.")
    p.add_argument("--link-log", action="append", default=None,
                   help="Repeatable. Cite a source log entry in '## Related log entries'. "
                        "Format: '[[log:YYYY-MM-DD#L<n>]]'. Merges with existing entries; deduped.")
    p.add_argument("--json", action="store_true")


def cmd_anatomy_register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "anatomy-register",
        help="Register a project root for anatomy snapshots. Slug must be unique; conflicts error out.",
    )
    p.add_argument("--config", type=str, default=None)
    p.add_argument("root", type=str, help="Project root directory to register")
    p.add_argument(
        "--slug",
        type=str,
        default=None,
        help="Optional slug (lowercase, [a-z0-9._-], 1..64). Defaults to root basename.",
    )
    p.add_argument("--json", action="store_true")


def cmd_anatomy_scan(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "anatomy-scan",
        help="Scan a registered project's files and rebuild its anatomy snapshot.",
    )
    p.add_argument("--config", type=str, default=None)
    p.add_argument("slug", type=str, help="Slug or absolute project root path")
    p.add_argument("--json", action="store_true")


def cmd_anatomy_show(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("anatomy-show", help="Print the rendered anatomy markdown for a project")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("slug", type=str, help="Slug or absolute project root path")
    p.add_argument("--json", action="store_true")


def cmd_anatomy_set(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "anatomy-set",
        help="Manually set or refine the description of one file. Marks desc_source=user so future scans don't overwrite it.",
    )
    p.add_argument("--config", type=str, default=None)
    p.add_argument("slug", type=str, help="Slug or absolute project root path")
    p.add_argument("relpath", type=str, help="Relative path within the project root")
    p.add_argument("--desc", type=str, required=True)
    p.add_argument("--json", action="store_true")


def cmd_anatomy_list(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("anatomy-list", help="List registered anatomy projects with file/token counts")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--json", action="store_true")


def cmd_anatomy_upsert_file(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "anatomy-upsert-file",
        help="Refresh or remove the anatomy entry for one file. Matches the file against the registered anatomy index by longest prefix; silently no-ops when the file is outside every registered project.",
    )
    p.add_argument("--config", type=str, default=None)
    p.add_argument("file", type=str, help="Absolute path to the file that changed")
    p.add_argument(
        "--auto-register",
        action="store_true",
        help="When the file is not inside any registered project, auto-register the enclosing git repo if it contains a project marker (pyproject.toml, package.json, Cargo.toml, go.mod, ...). Used by the PostToolUse hook to grow the anatomy index on real edits.",
    )
    p.add_argument("--json", action="store_true")


def cmd_status(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "status",
        help="Aggregate dashboard: lifetime hook event counts (anatomy attaches, log writes, stop blocks, precompact), diagnostic ratios, and registered anatomy projects.",
    )
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--json", action="store_true", help="Emit raw JSON instead of the human-readable dashboard.")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="using-memory CLI")
    sub = parser.add_subparsers(dest="cmd")
    cmd_load(sub)
    cmd_setup(sub)
    cmd_search(sub)
    cmd_maintain(sub)
    cmd_stats(sub)
    cmd_export(sub)
    cmd_write_log(sub)
    cmd_write_memory(sub)
    cmd_write_preference(sub)
    cmd_upsert_doc(sub)
    cmd_anatomy_register(sub)
    cmd_anatomy_scan(sub)
    cmd_anatomy_show(sub)
    cmd_anatomy_set(sub)
    cmd_anatomy_list(sub)
    cmd_anatomy_upsert_file(sub)
    cmd_status(sub)
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        sys.exit(2)
    if args.cmd == "load":
        result = do_load(args)
    elif args.cmd == "setup":
        result = do_setup(args)
    elif args.cmd == "search":
        result = do_search(args)
    elif args.cmd == "maintain":
        result = do_maintain(args)
    elif args.cmd == "stats":
        result = do_stats(args)
    elif args.cmd == "export":
        result = do_export(args)
    elif args.cmd == "write-log":
        result = do_write_log(args)
    elif args.cmd == "write-memory":
        result = do_write_memory(args)
    elif args.cmd == "write-preference":
        result = do_write_preference(args)
    elif args.cmd == "upsert-doc":
        result = do_upsert_doc(args)
    elif args.cmd == "anatomy-register":
        result = do_anatomy_register(args)
    elif args.cmd == "anatomy-scan":
        result = do_anatomy_scan(args)
    elif args.cmd == "anatomy-show":
        result = do_anatomy_show(args)
    elif args.cmd == "anatomy-set":
        result = do_anatomy_set(args)
    elif args.cmd == "anatomy-list":
        result = do_anatomy_list(args)
    elif args.cmd == "anatomy-upsert-file":
        result = do_anatomy_upsert_file(args)
    elif args.cmd == "status":
        result = do_status(args)
    else:
        parser.print_help()
        sys.exit(2)
    if args.cmd == "status" and not args.json:
        print(_format_status(result))
    elif args.cmd == "maintain" and result.get("mode") == "distill" and not args.json:
        print(_format_distill(result))
    elif args.cmd == "maintain" and result.get("mode") == "promote" and not args.json:
        if result.get("error"):
            print(result["error"])
            if result.get("available_topics"):
                print("Known topics with candidate buckets: " + ", ".join(result["available_topics"]))
        else:
            print(result["prompt"])
    elif args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def _format_distill(result: dict) -> str:
    """Format the distill bucket analysis as a compact textual summary.

    Designed to be cheap to inject into SessionStart additionalContext when
    candidates exist, and informative when run interactively for debugging.
    """
    lines = [
        "using-memory distill",
        "====================",
        f"Checked at        : {result.get('checked_at')}",
        f"Total log entries : {result.get('total_log_entries', 0)}",
        f"Already promoted  : {result.get('promoted_log_entries', 0)}",
        f"Filters           : >= {result.get('min_entries')} entries, >= {result.get('min_days')} day-span",
        "",
    ]
    buckets = result.get("buckets") or []
    if not buckets:
        lines.append("No candidate buckets. Logs are either thin, recent, or already promoted.")
        return "\n".join(lines)

    lines.append(f"Candidate buckets ({len(buckets)})")
    lines.append("-" * 18)
    for b in buckets:
        proj = f" project={b['suggested_project']}" if b.get("suggested_project") else ""
        lines.append(
            f"  topic={b['topic']:<16} family={b['family']:<15} "
            f"entries={b['count']:>3} days={b['day_span']:>2} score={b['score']:>5}"
            f"  -> doc-type={b['suggested_doc_type']} slug={b['suggested_slug']}{proj}"
        )
    lines.append("")
    lines.append("Promote a bucket via subagent (general-purpose):")
    lines.append("  memory_tool.py maintain --promote <topic>[/<family>]  # synthesize prompt")
    lines.append("  -> subagent reads, decides, calls upsert-doc with --link-log refs")
    return "\n".join(lines)


def _format_status(result: dict) -> str:
    """Render a using-memory status dict as a human-readable dashboard."""
    lt = result.get("lifetime") or {}
    ratios = result.get("ratios") or {}
    anatomy = result.get("anatomy") or {}
    last_ts = result.get("last_event_ts") or "(never)"

    def pct(v):
        return "n/a" if v is None else f"{v * 100:.1f}%"

    lines = [
        "using-memory status",
        "===================",
        f"Last event: {last_ts}",
        f"Stats file: {result.get('stats_path')}",
        "",
        "Lifetime counters",
        "-----------------",
        f"  sessions started               : {lt.get('sessions', 0)}",
        f"  anatomy attached on start      : {lt.get('anatomy_attached_count', 0)}",
        f"     of which truncated to summary: {lt.get('anatomy_truncated_count', 0)}",
        f"  anatomy hint emitted           : {lt.get('anatomy_hint_emitted', 0)}  (cwd in unregistered git repo)",
        f"  anatomy tokens injected (est)  : {lt.get('anatomy_attached_tokens_est', 0)}",
        f"  anatomy file upserts (hooks)   : {lt.get('anatomy_upserts', 0)}",
        f"  anatomy auto-registered        : {lt.get('anatomy_auto_registered', 0)}  (PostToolUse first-edit registrations)",
        f"  log entries written by user/AI : {lt.get('log_entries_user', 0)}",
        f"  log entries silent-appended    : {lt.get('log_entries_auto', 0)}",
        f"  Stop hard-blocks (detail save) : {lt.get('stop_blocks', 0)}",
        f"  Stop throttled passthroughs    : {lt.get('stop_throttled_passthrough', 0)}",
        f"  PreCompact emergency saves     : {lt.get('precompact_blocks', 0)}",
        f"  cumulative human turns         : {lt.get('cumulative_human_turns', 0)}",
        f"  last distill check ts          : {lt.get('last_distill_check_ts') or 'never'}",
        f"  last distill inject ts         : {lt.get('last_distill_inject_ts') or 'never'}",
        f"  last promote ts                : {lt.get('last_promote_ts') or 'never'}",
        "",
        "Diagnostic ratios",
        "-----------------",
        f"  anatomy hit rate (attach/sessions) : {pct(ratios.get('anatomy_hit_rate'))}",
        f"  Stop block ratio  (block/total)    : {pct(ratios.get('stop_block_ratio'))}",
        "",
        f"Registered projects: {anatomy.get('registered_projects', 0)}  "
        f"(total {anatomy.get('total_files', 0)} files, {anatomy.get('total_tokens_est', 0)} est tokens)",
    ]
    for proj in anatomy.get("projects", [])[:20]:
        scanned = "scanned" if proj.get("scanned") else "NOT SCANNED"
        lines.append(
            f"  - {proj['slug']:<24} {proj.get('files', 0):>5} files  "
            f"{proj.get('tokens_est', 0):>7} tok  [{scanned}]  → {proj.get('root', '')}"
        )
    extra = max(0, len(anatomy.get("projects", [])) - 20)
    if extra:
        lines.append(f"  ... and {extra} more")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
