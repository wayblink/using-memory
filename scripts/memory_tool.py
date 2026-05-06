"""using-memory CLI: load and write curated Markdown memory files."""

import argparse
import contextlib
import hashlib
import json
import os
import sys
import tempfile
import yaml
from pathlib import Path
from datetime import UTC, date, datetime, timedelta

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback for portable installs.
    fcntl = None


DEFAULT_CONFIG_PATH = "~/.skills/using-memory/config.yaml"
LOCAL_CONTEXT_FILES = ("MACHINE.md", "ENV.md", "WORKSPACE.md")
DOC_ENTRY_REQUIRED_FIELDS = ("path", "title", "type", "modified")


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
                f"USING_MEMORY_CONFIG points to missing file: {env_path}; create it or unset USING_MEMORY_CONFIG to use {DEFAULT_CONFIG_PATH}"
            )
        raw = env_path.read_text(encoding="utf-8")
    elif config_path:
        if not config_path.exists():
            return no_memory_config(
                f"config file not found: {config_path}; create it or set USING_MEMORY_CONFIG"
            )
        raw = config_path.read_text(encoding="utf-8")
    else:
        default_config = Path(DEFAULT_CONFIG_PATH).expanduser()
        if not default_config.exists():
            return no_memory_config(
                f"config file not found: {DEFAULT_CONFIG_PATH}; create it or set USING_MEMORY_CONFIG"
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


def append_daily_entry(
    root: Path,
    when: date,
    tag: str,
    text: str,
    confidence: int | None = None,
    source: str | None = None,
    files: list[str] | None = None,
) -> Path:
    """Append one entry to the primary repo's daily note (JSONL only)."""
    jsonl_target = root / "daily" / f"{when:%Y-%m-%d}.jsonl"
    record = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "date": when.isoformat(),
        "tag": tag,
        "source": source or "user",
        "text": text,
        "confidence": confidence,
        "files": files or [],
    }
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


def validate_primary_root_for_write(root: Path) -> None:
    if not root.exists():
        sys.stderr.write(f"primary root does not exist: {root}\n")
        sys.exit(2)
    if not root.is_dir():
        sys.stderr.write(f"primary root is not a directory: {root}\n")
        sys.exit(2)
    if not (root / ".git").exists():
        sys.stderr.write(f"primary root is not a Git repo: {root}\n")
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


def load_primary_for_write(args: argparse.Namespace) -> Path:
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
    validate_primary_root_for_write(primary_root)
    return primary_root


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
        sys.stderr.write("daily range start must be before or equal to end\n")
        sys.exit(2)
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def daily_dates_for_load(args: argparse.Namespace, target: date, read_today: bool, read_yesterday: bool) -> list[date]:
    has_range = bool(args.daily_from or args.daily_to)
    has_days = args.daily_days is not None
    if has_range and has_days:
        sys.stderr.write("--daily-from/--daily-to cannot be combined with --daily-days\n")
        sys.exit(2)
    if has_range:
        if not args.daily_from or not args.daily_to:
            sys.stderr.write("--daily-from and --daily-to must be provided together\n")
            sys.exit(2)
        return date_range(
            parse_iso_date(args.daily_from, "--daily-from"),
            parse_iso_date(args.daily_to, "--daily-to"),
        )
    if has_days:
        if args.daily_days < 1:
            sys.stderr.write("--daily-days must be >= 1\n")
            sys.exit(2)
        start = target - timedelta(days=args.daily_days - 1)
        return date_range(start, target)

    dates = []
    if read_today:
        dates.append(target)
    if read_yesterday:
        dates.append(target - timedelta(days=1))
    return dates


def append_daily_jsonl_sources(
    sources_list: list,
    local_context: list,
    daily_entries: list,
    warnings: list,
    primary_root: Path,
    primary_machine: str,
    dates: list[date],
    query: str | None,
) -> None:
    normalized_query = query.lower() if query else None
    for daily_date in dates:
        jsonl_path = primary_root / "daily" / f"{daily_date:%Y-%m-%d}.jsonl"
        if not jsonl_path.exists():
            continue
        daily_source = read_source(jsonl_path, "daily", "primary", primary_machine)
        if not daily_source["loaded"]:
            continue
        matched_lines = []
        if daily_source["loaded"]:
            for lineno, line in enumerate(daily_source["content"].splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    warnings.append(f"invalid daily jsonl: {jsonl_path}:{lineno}: {exc.msg}")
                    continue
                text = entry.get("text", "")
                if normalized_query and normalized_query not in str(text).lower():
                    continue
                daily_entries.append(entry)
                matched_lines.append(json.dumps(entry, ensure_ascii=False))
        if normalized_query and not matched_lines:
            continue
        if normalized_query:
            daily_source["content"] = "\n".join(matched_lines) + ("\n" if matched_lines else "")
        sources_list.append(daily_source)


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
    local_context = []
    daily_entries = []
    if roots_exist:
        ordered_roots = primary_list + ref_list

        for root_cfg in ordered_roots:
            raw_path = root_cfg.get("path", "")
            r_path = expand_path(raw_path)
            role = root_cfg.get("role", "reference")
            machine_id = root_cfg.get("machine_id", "")
            pref_source = read_source(r_path / "PREFERENCES.md", "preferences", role, machine_id)
            sources_list.append(pref_source)
            if pref_source["loaded"]:
                preferences.append(pref_source["content"])

        for root_cfg in ordered_roots:
            raw_path = root_cfg.get("path", "")
            r_path = expand_path(raw_path)
            role = root_cfg.get("role", "reference")
            machine_id = root_cfg.get("machine_id", "")
            memory_source = read_source(r_path / "MEMORY.md", "durable_memory", role, machine_id)
            sources_list.append(memory_source)
            if memory_source["loaded"]:
                durable_memory.append(memory_source["content"])

        if load_docs:
            for root_cfg in ordered_roots:
                r_path = expand_path(root_cfg.get("path", ""))
                role = root_cfg.get("role", "reference")
                machine_id = root_cfg.get("machine_id", "")
                index_source = read_json_source(r_path / "docs" / "index.json", "docs_index", role, machine_id)
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
                    doc_path = doc_path_from_entry(r_path, entry)
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
        primary_machine = primary_cfg.get("machine_id", "")
        daily_dates = daily_dates_for_load(args, target, read_today, read_yesterday)
        append_daily_jsonl_sources(
            sources_list,
            local_context,
            daily_entries,
            warnings,
            primary_root,
            primary_machine,
            daily_dates,
            args.daily_query,
        )

        for local_name in LOCAL_CONTEXT_FILES:
            local_source = read_source(
                primary_root / "local" / local_name,
                "local_context",
                "primary",
                primary_machine,
            )
            sources_list.append(local_source)
            if local_source["loaded"]:
                local_context.append(local_source["content"])
    else:
        warnings.append("no primary root configured; read_today and read_yesterday are no-ops")
    return {
        "mode": "memory" if roots_exist else "no_memory",
        "write_enabled": roots_exist and primary_list[0].get("writable", False) if roots_exist else False,
        "sources": sources_list,
        "preferences": preferences,
        "durable_memory": durable_memory,
        "local_context": local_context,
        "daily_entries": daily_entries,
        "doc_hits": doc_set,
        "warnings": warnings,
    }


def do_write_daily(args: argparse.Namespace) -> dict:
    primary_root = load_primary_for_write(args)
    when = parse_iso_date(args.date, "--date")
    allowed = {"pref", "decision", "lesson", "fact", "issue", "pattern", "preference"}
    tag = (args.tag or "").lower()
    if tag not in allowed:
        sys.stderr.write(f"invalid tag '{args.tag}'; allowed: {', '.join(sorted(allowed))}\n")
        sys.exit(2)
    confidence = args.confidence if args.confidence else None
    source = args.source if args.source else None
    files = args.files if args.files else []
    target = append_daily_entry(primary_root, when, tag, args.text, confidence=confidence, source=source, files=files)
    return {
        "changed": True,
        "path": str(target),
        "sha256": sha256_file(target),
    }


def do_write_memory(args: argparse.Namespace) -> dict:
    primary_root = load_primary_for_write(args)
    when = parse_iso_date(args.date, "--date")
    allowed = {"decision", "lesson", "fact"}
    tag = (args.tag or "").lower()
    if tag not in allowed:
        sys.stderr.write(f"tag is not allowed for write-memory\n")
        sys.exit(2)
    target = append_memory_entry(primary_root, when, tag, args.text)
    return {
        "changed": True,
        "path": str(target),
        "sha256": sha256_file(target),
    }


def do_write_preference(args: argparse.Namespace) -> dict:
    primary_root = load_primary_for_write(args)
    target = append_preference_entry(primary_root, args.text)
    return {
        "changed": True,
        "path": str(target),
        "sha256": sha256_file(target),
    }


def do_upsert_doc(args: argparse.Namespace) -> dict:
    primary_root = load_primary_for_write(args)
    doc_name = validate_doc_name(args.doc)
    parse_iso_date(args.modified, "--modified")
    doc_path = primary_root / "docs" / f"{doc_name}.md"
    index_path = primary_root / "docs" / "index.json"
    rel_path = f"{doc_name}.md"
    entry = {
        "path": rel_path,
        "title": args.title,
        "type": args.doc_type,
        "modified": args.modified,
        "projects": args.project or [],
        "tags": args.doc_tag or [],
    }
    if args.summary:
        entry["summary"] = args.summary
    error = validate_doc_entry(entry)
    if error:
        sys.stderr.write(f"invalid doc metadata: {error}\n")
        sys.exit(2)
    with exclusive_file_lock(primary_root / "docs" / ".docs.lock"):
        index = load_doc_index(index_path)
        index = doc_index_with_entry(index, entry)
        atomic_write_text(doc_path, args.text)
        write_doc_index(index_path, index)
    return {
        "changed": True,
        "path": str(doc_path),
        "index_path": str(index_path),
        "sha256": sha256_file(doc_path),
        "index_sha256": sha256_file(index_path),
    }


def _search_sources(
    config: dict,
    query: str,
    *,
    search_docs: bool,
    search_memory: bool,
    search_daily: bool,
    daily_days: int | None = None,
) -> dict:
    """Full-text search across docs, MEMORY.md, and daily JSONL."""
    hits = []
    if not config:
        return {"query": query, "hits": [], "total": 0}

    primary_list, ref_list = collect_roots(config)
    validate_single_primary(primary_list, required=False)
    ordered_roots = primary_list + ref_list

    # --- docs/*.md ---
    if search_docs:
        for root_cfg in ordered_roots:
            r_path = expand_path(root_cfg.get("path", ""))
            role = root_cfg.get("role", "reference")
            index_path = r_path / "docs" / "index.json"
            if not index_path.exists():
                continue
            index_source = read_json_source(index_path, "docs_index", role)
            if not index_source.get("loaded"):
                continue
            entries = normalize_doc_index(index_source["json"])
            for entry in entries:
                doc_path = doc_path_from_entry(r_path, entry)
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

    # --- MEMORY.md ---
    if search_memory:
        for root_cfg in ordered_roots:
            r_path = expand_path(root_cfg.get("path", ""))
            role = root_cfg.get("role", "reference")
            mem_path = r_path / "MEMORY.md"
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

    # --- daily/*.jsonl ---
    if search_daily and primary_list:
        primary_root = expand_path(primary_list[0].get("path", ""))
        if daily_days:
            target = date.today()
            start = target - timedelta(days=daily_days - 1)
            date_list = date_range(start, target)
        else:
            date_list = [date.today() - timedelta(days=i) for i in range(2)]
        for d in date_list:
            jsonl_path = primary_root / "daily" / f"{d:%Y-%m-%d}.jsonl"
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
                if query.lower() in text.lower():
                    hits.append({
                        "source": "daily",
                        "path": str(jsonl_path),
                        "line": lineno,
                        "snippet": text[:120],
                        "score": 1,
                    })

    return {
        "query": query,
        "hits": hits,
        "total": len(hits),
        "scope": {
            "docs": "primary_and_reference" if search_docs else "disabled",
            "memory": "primary_and_reference" if search_memory else "disabled",
            "daily": "primary_only" if search_daily else "disabled",
        },
    }


def do_search(args: argparse.Namespace) -> dict:
    config = load_config(Path(args.config) if args.config else None, os.environ.get("USING_MEMORY_CONFIG"))
    return _search_sources(
        config=config,
        query=args.query,
        search_docs=not args.no_docs,
        search_memory=not args.no_memory,
        search_daily=not args.no_daily,
        daily_days=args.daily_days,
    )


def do_maintain(args: argparse.Namespace) -> dict:
    """Run maintenance checks and repair missing docs index entries."""
    primary_root = load_primary_for_write(args)
    daily_dir = primary_root / "daily"
    stale = []
    corrupt = []
    ok_count = 0

    if daily_dir.is_dir():
        for jsonl_path in sorted(daily_dir.glob("*.jsonl")):
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
                    candidate = resolve_primary_file_reference(primary_root, f_path)
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

    indexed_docs = maintain_doc_index(primary_root)
    return {"stale": stale, "corrupt": corrupt, "ok": ok_count, "indexed_docs": indexed_docs}


def _collect_stats(config: dict | None) -> dict:
    """Count daily JSONL entries and MEMORY.md lines by tag."""
    daily_tags: dict = {}
    memory_tags: dict = {}
    total_daily = 0
    total_memory = 0

    if not config:
        return {
            "daily": {"total": 0, "by_tag": {}},
            "memory": {"total": 0, "by_tag": {}},
            "scope": {"daily": "primary_only", "memory": "primary_only"},
        }

    primary_list, _ = collect_roots(config)
    validate_single_primary(primary_list, required=False)
    ordered_roots = primary_list + []

    for root_cfg in ordered_roots:
        r_path = expand_path(root_cfg.get("path", ""))
        daily_dir = r_path / "daily"
        if daily_dir.is_dir():
            for jsonl_path in daily_dir.glob("*.jsonl"):
                try:
                    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        entry = json.loads(line)
                        tag = entry.get("tag", "unknown")
                        daily_tags[tag] = daily_tags.get(tag, 0) + 1
                        total_daily += 1
                except Exception:
                    continue

        mem_path = r_path / "MEMORY.md"
        if mem_path.is_file():
            for line in mem_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("- [") and "] " in line:
                    tag = line[3:].split("]")[0].split("|")[0].lower()
                    memory_tags[tag] = memory_tags.get(tag, 0) + 1
                    total_memory += 1

    return {
        "daily": {"total": total_daily, "by_tag": daily_tags},
        "memory": {"total": total_memory, "by_tag": memory_tags},
        "scope": {"daily": "primary_only", "memory": "primary_only"},
    }


def do_stats(args: argparse.Namespace) -> dict:
    config = load_config(Path(args.config) if args.config else None, os.environ.get("USING_MEMORY_CONFIG"))
    return _collect_stats(config)


def _format_export(stats: dict, config: dict | None) -> str:
    lines = ["## Project Memory Snapshot\n"]
    daily = stats.get("daily", {})
    memory = stats.get("memory", {})
    lines.append(f"**Daily JSONL entries:** {daily.get('total', 0)}")
    lines.append(f"**MEMORY.md entries:** {memory.get('total', 0)}\n")

    for section, label in [("daily", "Daily tags"), ("memory", "MEMORY.md tags")]:
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


def cmd_search(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("search", help="Full-text search across docs, MEMORY.md and daily JSONL")
    p.add_argument("query", type=str, help="Search term")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--daily-days", type=int, default=None)
    p.add_argument("--no-docs", action="store_true")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument("--no-daily", action="store_true")
    p.add_argument("--json", action="store_true")


def cmd_maintain(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("maintain", help="Run maintenance checks and repair missing docs index entries")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--json", action="store_true")


def cmd_stats(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("stats", help="Summary statistics for daily JSONL and MEMORY.md")
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
    p.add_argument("--daily-from", type=str, default=None)
    p.add_argument("--daily-to", type=str, default=None)
    p.add_argument("--daily-days", type=int, default=None)
    p.add_argument("--daily-query", type=str, default=None)
    p.add_argument("--doc", type=str, default=None)
    p.add_argument("--doc-type", type=str, default=None)
    p.add_argument("--doc-tag", action="append", default=None)
    p.add_argument("--project", action="append", default=None)
    p.add_argument("--doc-query", type=str, default=None)
    p.add_argument("--json", action="store_true")


def cmd_write_daily(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("write-daily", help="Append one entry to the primary repo's daily note (JSONL)")
    p.add_argument("--config", type=str, required=True)
    p.add_argument("--date", type=str, required=True)
    p.add_argument("--tag", type=str, required=True)
    p.add_argument("--text", type=str, required=True)
    p.add_argument("--confidence", type=int, default=None)
    p.add_argument("--source", type=str, default=None)
    p.add_argument("--files", action="append", default=None)
    p.add_argument("--json", action="store_true")


def cmd_write_memory(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("write-memory", help="Append one durable entry to MEMORY.md")
    p.add_argument("--config", type=str, required=True)
    p.add_argument("--date", type=str, required=True)
    p.add_argument("--tag", type=str, required=True)
    p.add_argument("--text", type=str, required=True)
    p.add_argument("--json", action="store_true")


def cmd_write_preference(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("write-preference", help="Append one stable preference to PREFERENCES.md")
    p.add_argument("--config", type=str, required=True)
    p.add_argument("--text", type=str, required=True)
    p.add_argument("--json", action="store_true")


def cmd_upsert_doc(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("upsert-doc", help="Write one docs/*.md file and update docs/index.json")
    p.add_argument("--config", type=str, required=True)
    p.add_argument("--doc", type=str, required=True)
    p.add_argument("--title", type=str, required=True)
    p.add_argument("--doc-type", type=str, required=True)
    p.add_argument("--modified", type=str, required=True)
    p.add_argument("--project", action="append", default=None)
    p.add_argument("--doc-tag", action="append", default=None)
    p.add_argument("--summary", type=str, default=None)
    p.add_argument("--text", type=str, required=True)
    p.add_argument("--json", action="store_true")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="using-memory CLI")
    sub = parser.add_subparsers(dest="cmd")
    cmd_load(sub)
    cmd_search(sub)
    cmd_maintain(sub)
    cmd_stats(sub)
    cmd_export(sub)
    cmd_write_daily(sub)
    cmd_write_memory(sub)
    cmd_write_preference(sub)
    cmd_upsert_doc(sub)
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        sys.exit(2)
    if args.cmd == "load":
        result = do_load(args)
    elif args.cmd == "search":
        result = do_search(args)
    elif args.cmd == "maintain":
        result = do_maintain(args)
    elif args.cmd == "stats":
        result = do_stats(args)
    elif args.cmd == "export":
        result = do_export(args)
    elif args.cmd == "write-daily":
        result = do_write_daily(args)
    elif args.cmd == "write-memory":
        result = do_write_memory(args)
    elif args.cmd == "write-preference":
        result = do_write_preference(args)
    elif args.cmd == "upsert-doc":
        result = do_upsert_doc(args)
    else:
        parser.print_help()
        sys.exit(2)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
