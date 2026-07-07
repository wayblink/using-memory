"""Core config resolution and filesystem IO primitives for using-memory.

Bottom layer split out of memory_tool.py: config loading/validation, namespace
path resolution, and the atomic read/write/lock primitives. This module has NO
dependency on the rest of memory_tool, so it can be shared by the CLI and by
future alternate backends without import cycles.
"""

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback for portable installs.
    fcntl = None

DEFAULT_CONFIG_PATH = "~/.skills/using-memory/config.yaml"
DOC_ENTRY_REQUIRED_FIELDS = ("path", "title", "type", "modified")
DEFAULT_NAMESPACE = "main"
# Whitelisted doc filename extensions. Add a new format here and the rest of
# the docs subsystem (validate, upsert, maintain index, web list/edit) picks
# it up automatically. Keep ``DEFAULT_DOC_EXT`` in sync with the leading entry.
SUPPORTED_DOC_EXTS = (".md", ".html", ".htm", ".txt")
DEFAULT_DOC_EXT = ".md"
SETUP_HINT = "Run `python3 scripts/memory_tool.py setup` to configure memory path, optional remote Git repo, namespace, and machine ID."
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
def normalize_index_doc_path(doc: str) -> str | None:
    if not doc or doc.startswith("/") or "\\" in doc or doc in {".", ".."}:
        return None
    doc_path = Path(doc)
    if ".." in doc_path.parts:
        return None
    if doc_path.suffix:
        if doc_path.suffix.lower() not in SUPPORTED_DOC_EXTS:
            return None
        return doc
    return f"{doc}{DEFAULT_DOC_EXT}"
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
    created = entry.get("created")
    if created is not None:
        if not isinstance(created, str) or not created.strip():
            return "document entry has invalid created date"
        try:
            date.fromisoformat(created)
        except ValueError:
            return f"document entry has invalid created date: {created}"
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


def iter_log_entries(log_dir, *, with_lineno=False):
    """Yield parsed JSON log objects from every ``*.jsonl`` under ``log_dir``.

    Single funnel for the common "read all log entries, skip blanks and
    malformed lines" pattern used by search/stats/distill. Silently skips
    unreadable files and non-dict / malformed-JSON lines. With
    ``with_lineno=True`` yields ``(path, lineno, entry)`` triples, else ``entry``.

    NOTE: callers that must *report* corrupt lines (e.g. maintain) keep their
    own read loop; this helper intentionally swallows corruption.
    """
    if not log_dir.is_dir():
        return
    for jsonl_path in sorted(log_dir.glob("*.jsonl")):
        try:
            text = jsonl_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, raw in enumerate(text.splitlines(), 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if with_lineno:
                yield jsonl_path, lineno, entry
            else:
                yield entry
