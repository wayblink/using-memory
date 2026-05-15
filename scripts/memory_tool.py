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

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback for portable installs.
    fcntl = None

DEFAULT_CONFIG_PATH = "~/.skills/using-memory/config.yaml"
DOC_ENTRY_REQUIRED_FIELDS = ("path", "title", "type", "modified")
DEFAULT_NAMESPACE = "main"
SETUP_HINT = "Run `python3 scripts/memory_tool.py setup` to configure memory path, optional remote Git repo, namespace, and machine ID."
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


def no_memory_config(warning: str) -> dict:
    return {
        "version": 1,
        "memory_roots": [],
        "defaults": {
            "read_today": True,
            "read_yesterday": True,
            "load_docs_on_demand": True,
        },
        "_warnings": [warning],
    }


def load_config(config_path: Path | None, env_config: str | None) -> dict:
    raw = None
    if env_config:
        env_path = Path(os.path.expanduser(os.path.expandvars(env_config)))
        if not env_path.exists():
            return no_memory_config(
                f"USING_MEMORY_CONFIG points to missing file: {env_path}; create it with setup. {SETUP_HINT} Or unset USING_MEMORY_CONFIG to use {DEFAULT_CONFIG_PATH}."
            )
        raw = env_path.read_text(encoding="utf-8")
    elif config_path:
        if not config_path.exists():
            return no_memory_config(
                f"config file not found: {config_path}; create it with setup. {SETUP_HINT}"
            )
        raw = config_path.read_text(encoding="utf-8")
    else:
        default_config = Path(DEFAULT_CONFIG_PATH).expanduser()
        if not default_config.exists():
            return no_memory_config(
                f"config file not found: {DEFAULT_CONFIG_PATH}; create it with setup. {SETUP_HINT}"
            )
        raw = default_config.read_text(encoding="utf-8")

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        sys.stderr.write(f"invalid config yaml: {exc}\n")
        sys.exit(2)
    if data is None:
        return {}
    if not isinstance(data, dict):
        sys.stderr.write("invalid config: root must be a mapping\n")
        sys.exit(2)
    return data


def collect_roots(config: dict) -> tuple[list, list]:
    roots = config.get("memory_roots", [])
    if not isinstance(roots, list):
        sys.stderr.write("invalid config: memory_roots must be a list\n")
        sys.exit(2)
    if any(not isinstance(root, dict) for root in roots):
        sys.stderr.write("invalid config: each memory root must be a mapping\n")
        sys.exit(2)
    primaries = sorted([r for r in roots if r.get("role") == "primary"], key=root_priority, reverse=True)
    references = sorted([r for r in roots if r.get("role") == "reference"], key=root_priority, reverse=True)
    return primaries, references


def root_priority(root: dict) -> int:
    try:
        return int(root.get("priority", 0))
    except (TypeError, ValueError):
        return 0


def expand_path(raw_path: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(raw_path)))


def namespace_from_root(root_cfg: dict) -> str:
    namespace = root_cfg.get("namespace", DEFAULT_NAMESPACE)
    if namespace is None:
        namespace = DEFAULT_NAMESPACE
    if not isinstance(namespace, str) or not namespace.strip():
        sys.stderr.write("invalid namespace: expected a non-empty path segment\n")
        sys.exit(2)
    namespace = namespace.strip()
    namespace_path = Path(namespace)
    if namespace_path.is_absolute() or "\\" in namespace or namespace in {".", ".."} or ".." in namespace_path.parts or len(namespace_path.parts) != 1:
        sys.stderr.write("invalid namespace: expected a single relative path segment\n")
        sys.exit(2)
    return namespace


def namespace_root(root: Path, namespace: str) -> Path:
    return root / namespace


def parse_iso_date(raw: str | None, label: str) -> date:
    try:
        return date.fromisoformat(raw or "")
    except (TypeError, ValueError):
        sys.stderr.write(f"invalid {label}; expected YYYY-MM-DD\n")
        sys.exit(2)


def read_source(path: Path, source_type: str, role: str, machine_id: str = "") -> dict:
    source = {
        "path": str(path),
        "type": source_type,
        "role": role,
        "machine_id": machine_id,
        "loaded": False,
    }
    if path.is_file():
        source["loaded"] = True
        source["content"] = path.read_text(encoding="utf-8")
        source["sha256"] = sha256_file(path)
    else:
        source["warning"] = "missing"
    return source


def validate_single_primary(primary_list: list, *, required: bool) -> bool:
    if len(primary_list) > 1:
        sys.stderr.write("config must declare exactly one primary root\n")
        sys.exit(2)
    if required and not primary_list:
        sys.stderr.write("config has no primary root\n")
        sys.exit(2)
    return bool(primary_list)


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
    if doc_path.suffix and doc_path.suffix != ".md":
        sys.stderr.write("invalid doc name\n")
        sys.exit(2)
    return doc.removesuffix(".md")


def normalize_index_doc_path(doc: str) -> str | None:
    if not doc or doc.startswith("/") or "\\" in doc or doc in {".", ".."}:
        return None
    doc_path = Path(doc)
    if ".." in doc_path.parts:
        return None
    if doc_path.suffix and doc_path.suffix != ".md":
        return None
    return doc.removesuffix(".md")


def read_json_source(path: Path, source_type: str, role: str, machine_id: str = "") -> dict:
    source = read_source(path, source_type, role, machine_id)
    if not source["loaded"]:
        return source
    try:
        source["json"] = json.loads(source["content"])
    except json.JSONDecodeError as exc:
        source["loaded"] = False
        source["warning"] = f"invalid json: {exc.msg}"
        return source
    if source_type == "docs_index":
        error = validate_doc_index(source["json"])
        if error:
            source["loaded"] = False
            source["warning"] = f"invalid docs index: {error}"
    return source


def normalize_doc_index(raw_index) -> list[dict]:
    if isinstance(raw_index, dict):
        raw_docs = raw_index.get("documents", [])
    elif isinstance(raw_index, list):
        raw_docs = raw_index
    else:
        return []
    return [entry for entry in raw_docs if isinstance(entry, dict)]


def validate_doc_entry(entry: dict) -> str | None:
    for field in DOC_ENTRY_REQUIRED_FIELDS:
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            return f"document entry missing required string field: {field}"
    if normalize_index_doc_path(entry["path"]) is None:
        return f"document entry has invalid path: {entry['path']}"
    for field in ("projects", "tags", "aliases"):
        value = entry.get(field, [])
        if value is not None and not isinstance(value, list):
            return f"document entry field must be a list: {field}"
    try:
        date.fromisoformat(entry["modified"])
    except ValueError:
        return f"document entry has invalid modified date: {entry['modified']}"
    return None


def validate_doc_index(data) -> str | None:
    if not isinstance(data, dict):
        return "root must be an object"
    documents = data.get("documents", [])
    if not isinstance(documents, list):
        return "documents must be a list"
    for entry in documents:
        if not isinstance(entry, dict):
            return "document entries must be objects"
        error = validate_doc_entry(entry)
        if error:
            return error
    return None


def doc_entry_text(entry: dict) -> str:
    values = []
    for key in ("title", "type", "modified", "path", "summary"):
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
        candidates = {
            str(entry.get("path", "")).removesuffix(".md"),
            str(entry.get("id", "")).removesuffix(".md"),
            str(entry.get("title", "")).removesuffix(".md"),
        }
        aliases = entry.get("aliases", [])
        if isinstance(aliases, list):
            candidates.update(str(alias).removesuffix(".md") for alias in aliases)
        if doc_name not in candidates:
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
    return root / "docs" / f"{validated}.md"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def lock_path_for(path: Path) -> Path:
    return path.parent / f".{path.name}.lock"


@contextlib.contextmanager
def exclusive_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def append_markdown_entry(path: Path, entry: str) -> Path:
    with exclusive_file_lock(lock_path_for(path)):
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if existing:
            separator = "" if existing.endswith("\n") else "\n"
            atomic_write_text(path, existing + separator + entry)
        else:
            atomic_write_text(path, entry)
    return path


_ANATOMY_REF_RE = re.compile(r"\[\[anatomy:([a-z0-9][a-z0-9._-]{0,63})/([^\]]+)\]\]")


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


def append_preference_entry(root: Path, text: str) -> Path:
    pref_path = root / "PREFERENCES.md"
    entry = f"- [pref] {text}\n"
    return append_markdown_entry(pref_path, entry)


def looks_like_memory_namespace_root(path: Path) -> bool:
    # "local" is kept as a backward-compat marker; pre-V2.3 namespaces had it.
    markers = ("MEMORY.md", "PREFERENCES.md", "log", "docs", "anatomy", "STATS.json", "local")
    return any((path / marker).exists() for marker in markers)


def validate_primary_root_for_write(root: Path, namespace: str) -> None:
    if not root.exists():
        sys.stderr.write(f"primary root does not exist: {root}\n")
        sys.exit(2)
    if not root.is_dir():
        sys.stderr.write(f"primary root is not a directory: {root}\n")
        sys.exit(2)
    if looks_like_memory_namespace_root(root):
        sys.stderr.write(
            f"invalid memory root path: {root} appears to be a namespace root; "
            f"set path to its parent and namespace to '{namespace}'\n"
        )
        sys.exit(2)
    scoped_root = namespace_root(root, namespace)
    if not scoped_root.exists():
        sys.stderr.write(f"namespace root does not exist: {scoped_root}\n")
        sys.exit(2)
    if not scoped_root.is_dir():
        sys.stderr.write(f"namespace root is not a directory: {scoped_root}\n")
        sys.exit(2)
    if not (root / ".git").exists() and not (scoped_root / ".git").exists():
        sys.stderr.write(f"neither memory root nor namespace root is a Git repo: {root} / {namespace}\n")
        sys.exit(2)


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


def load_primary_for_write(args: argparse.Namespace) -> tuple[Path, str]:
    config = load_config(Path(args.config) if args.config else None, os.environ.get("USING_MEMORY_CONFIG"))
    if not config:
        sys.stderr.write("config not found\n")
        sys.exit(2)
    primary_list, _ = collect_roots(config)
    validate_single_primary(primary_list, required=True)
    if not primary_list[0].get("writable", False):
        sys.stderr.write("primary root is not writable\n")
        sys.exit(2)
    raw_path = primary_list[0].get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        sys.stderr.write("primary root path is missing\n")
        sys.exit(2)
    primary_root = expand_path(raw_path)
    primary_namespace = namespace_from_root(primary_list[0])
    validate_primary_root_for_write(primary_root, primary_namespace)
    return primary_root, primary_namespace


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


def extract_markdown_title(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip()
                if title:
                    return title
    except UnicodeDecodeError:
        pass
    return path.stem.replace("-", " ").replace("_", " ").strip().title() or path.stem


def extract_h1_from_text(text: str) -> str | None:
    """Return the first ``# Heading`` line from a markdown string, or None."""
    if not text:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            candidate = stripped[2:].strip()
            if candidate:
                return candidate
    return None


def doc_index_entry_for_file(docs_dir: Path, doc_path: Path) -> dict:
    rel_path = doc_path.relative_to(docs_dir).as_posix()
    modified = date.fromtimestamp(doc_path.stat().st_mtime).isoformat()
    return {
        "path": rel_path,
        "title": extract_markdown_title(doc_path),
        "type": "wiki",
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
        for doc_path in sorted(docs_dir.rglob("*.md")):
            if not doc_path.is_file():
                continue
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
                                "name": str(entry.get("path") or entry.get("id") or "").removesuffix(".md"),
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
    )
    return {
        "changed": True,
        "path": str(target),
        "sha256": sha256_file(target),
        "auto_project": project if project else None,
        "auto_topic": topic if topic else None,
    }


def _bump_lifetime_stats(scoped_root: Path, deltas: dict, sets: dict | None = None) -> None:
    """Atomic update of <namespace>/STATS.json.

    Same contract as the hook-side bump_stats; lives here so write-* CLI
    commands can update counts independently of any hook context.
    ``deltas`` are added to existing values; ``sets`` overwrite them.
    """
    if not deltas and not sets:
        return
    path = scoped_root / "STATS.json"
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
    target = append_preference_entry(namespace_root(primary_root, primary_namespace), args.text)
    return {
        "changed": True,
        "path": str(target),
        "sha256": sha256_file(target),
    }


def do_upsert_doc(args: argparse.Namespace) -> dict:
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)
    doc_name = validate_doc_name(args.doc)

    text = args.text
    if text is None:
        if getattr(args, "text_stdin", False):
            text = sys.stdin.read()
        else:
            sys.stderr.write("upsert-doc requires --text or --text-stdin\n")
            sys.exit(2)

    # Fallback fields: title -> first H1 -> slug-derived; doc_type -> "wiki";
    # modified -> today. Keep behaviour identical when explicit values pass.
    title = args.title or extract_h1_from_text(text) or doc_name.replace("-", " ").replace("_", " ").strip().title() or doc_name
    doc_type = args.doc_type or "wiki"
    modified = args.modified or date.today().isoformat()
    parse_iso_date(modified, "--modified")

    doc_path = scoped_root / "docs" / f"{doc_name}.md"
    index_path = scoped_root / "docs" / "index.json"
    rel_path = f"{doc_name}.md"
    entry = {
        "path": rel_path,
        "title": title,
        "type": doc_type,
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
    with exclusive_file_lock(scoped_root / "docs" / ".docs.lock"):
        index = load_doc_index(index_path)
        index = doc_index_with_entry(index, entry)
        atomic_write_text(doc_path, text)
        write_doc_index(index_path, index)
    return {
        "changed": True,
        "path": str(doc_path),
        "index_path": str(index_path),
        "sha256": sha256_file(doc_path),
        "index_sha256": sha256_file(index_path),
        "title": title,
        "doc_type": doc_type,
        "modified": modified,
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

    Reads <namespace>/STATS.json (real event counters, no estimates), plus
    the anatomy index, and computes two diagnostic ratios:
      - anatomy_hit_rate     = anatomy_attached_count / sessions
      - stop_block_ratio     = stop_blocks / (stop_blocks + stop_throttled_passthrough)

    Both ratios are diagnostic, not performance claims. The hit rate tells
    the user how often SessionStart found a registered project; a low rate
    suggests more anatomy-register calls would help. The block ratio tells
    the user whether the N=8 throttle is too aggressive (high → too many
    blocks) or too lax (very low → silent summaries doing all the work).
    """
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)
    stats_path = scoped_root / "STATS.json"
    # Backward compat: pre-V2.4 installs had it under local/. If only the old
    # path exists, surface it so the dashboard still works during transition.
    legacy_path = scoped_root / "local" / "STATS.json"
    if not stats_path.exists() and legacy_path.exists():
        stats_path = legacy_path
    lifetime: dict = {}
    last_event_ts: str | None = None
    if stats_path.exists():
        try:
            raw = json.loads(stats_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                lt = raw.get("lifetime")
                if isinstance(lt, dict):
                    lifetime = lt
                last_event_ts = raw.get("last_event_ts")
        except (OSError, json.JSONDecodeError):
            pass

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
        "stats_path": str(stats_path),
        "last_event_ts": last_event_ts,
        "lifetime": {
            "sessions": sessions,
            "anatomy_attached_count": attached,
            "anatomy_truncated_count": truncated,
            "anatomy_hint_emitted": hints,
            "anatomy_attached_tokens_est": attached_tokens,
            "anatomy_upserts": upserts,
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

    Returns one of: "updated", "removed", "skipped" (filtered/should-skip),
    "no-doc" (project never scanned yet). On disk both <slug>.json and
    <slug>.md are re-written atomically when something changed.
    """
    doc = _anatomy_load_doc(scoped_root, slug)
    if not doc:
        return "no-doc"
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
    if not slug or not project_root or rel is None:
        return {
            "changed": False,
            "matched": False,
            "file": str(file_path),
            "reason": "no registered project contains this file",
        }
    action = _anatomy_upsert_file(scoped_root, slug, project_root, file_path, rel)
    return {
        "changed": action in {"updated", "removed"},
        "matched": True,
        "slug": slug,
        "rel": rel,
        "action": action,
    }


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
    if _cwd_is_git_repo(cwd):
        result["hint"] = (
            "cwd is inside a git repo but not a registered anatomy project. "
            "Run `memory_tool.py anatomy-register <root>` to enable project-aware load."
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
    """Run maintenance checks and repair missing docs index entries."""
    primary_root, primary_namespace = load_primary_for_write(args)
    scoped_root = namespace_root(primary_root, primary_namespace)
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
    p.add_argument("--text", type=str, required=True)
    p.add_argument("--json", action="store_true")


def cmd_upsert_doc(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("upsert-doc", help="Write one configured namespace docs/*.md file and update <namespace>/docs/index.json")
    p.add_argument("--config", type=str, default=None,
                   help="Config path. Falls back to USING_MEMORY_CONFIG env or ~/.skills/using-memory/config.yaml.")
    p.add_argument("--doc", type=str, required=True,
                   help="Doc slug (filename without .md). Required.")
    p.add_argument("--title", type=str, default=None,
                   help="Optional. Defaults to first H1 in --text, then slug-derived title.")
    p.add_argument("--doc-type", type=str, default=None,
                   help="Optional. Defaults to 'wiki'. Common values: wiki, lesson, troubleshooting, decision-record, runbook, SOP, project.")
    p.add_argument("--modified", type=str, default=None,
                   help="Optional ISO date (YYYY-MM-DD). Defaults to today.")
    p.add_argument("--project", action="append", default=None)
    p.add_argument("--doc-tag", action="append", default=None)
    p.add_argument("--summary", type=str, default=None)
    p.add_argument("--text", type=str, default=None,
                   help="Doc body. Required unless --text-stdin is set.")
    p.add_argument("--text-stdin", action="store_true",
                   help="Read --text body from stdin instead of inline.")
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
    elif args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


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
