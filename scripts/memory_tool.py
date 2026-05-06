"""using-memory CLI: load and write curated Markdown memory files."""

import argparse
import hashlib
import json
import os
import sys
import yaml
from pathlib import Path
from datetime import date, timedelta


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


def append_markdown_entry(path: Path, entry: str) -> Path:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    if existing:
        separator = "" if existing.endswith("\n") else "\n"
        path.write_text(existing + separator + entry, encoding="utf-8")
    else:
        path.write_text(entry, encoding="utf-8")
    return path


def append_daily_entry(root: Path, when: date, tag: str, text: str) -> Path:
    target = root / "daily" / f"{when:%Y-%m-%d}.md"
    entry = f"- [{tag}|{when:%Y-%m-%d}] {text}\n"
    return append_markdown_entry(target, entry)


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
    documents = index["documents"]
    documents = [doc for doc in documents if doc.get("path") != entry["path"]]
    documents.append(entry)
    documents.sort(key=lambda doc: str(doc.get("path", "")))
    index["documents"] = documents
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def append_daily_sources(
    sources_list: list,
    local_context: list,
    primary_root: Path,
    primary_machine: str,
    dates: list[date],
    query: str | None,
) -> None:
    normalized_query = query.lower() if query else None
    for daily_date in dates:
        daily_source = read_source(
            primary_root / "daily" / f"{daily_date:%Y-%m-%d}.md",
            "daily",
            "primary",
            primary_machine,
        )
        if normalized_query:
            if not daily_source["loaded"]:
                continue
            if normalized_query not in daily_source["content"].lower():
                continue
        sources_list.append(daily_source)
        if daily_source["loaded"]:
            local_context.append(daily_source["content"])


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
        append_daily_sources(
            sources_list,
            local_context,
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
        "doc_hits": doc_set,
        "warnings": warnings,
    }


def do_write_daily(args: argparse.Namespace) -> dict:
    primary_root = load_primary_for_write(args)
    when = parse_iso_date(args.date, "--date")
    allowed = {"pref", "decision", "lesson", "fact", "issue"}
    tag = (args.tag or "").lower()
    if tag not in allowed:
        sys.stderr.write(f"invalid tag '{args.tag}'; allowed: {', '.join(sorted(allowed))}\n")
        sys.exit(2)
    target = append_daily_entry(primary_root, when, tag, args.text)
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
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(args.text, encoding="utf-8")
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
    upsert_doc_index_entry(index_path, entry)
    return {
        "changed": True,
        "path": str(doc_path),
        "index_path": str(index_path),
        "sha256": sha256_file(doc_path),
        "index_sha256": sha256_file(index_path),
    }


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
    p = sub.add_parser("write-daily", help="Append one entry to the primary repo's daily note")
    p.add_argument("--config", type=str, required=True)
    p.add_argument("--date", type=str, required=True)
    p.add_argument("--tag", type=str, required=True)
    p.add_argument("--text", type=str, required=True)
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
