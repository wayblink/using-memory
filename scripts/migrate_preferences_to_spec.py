#!/usr/bin/env python3
"""Split a legacy PREFERENCES.md into SPEC.md + spec/<repo>.md.

Rules became scoped: `SPEC.md` holds rules that apply to every project, and
`spec/<repo>.md` holds rules that apply only inside one repository. A namespace
created before that split keeps one flat PREFERENCES.md, which the loader still
reads as a fallback — but a flat file cannot express scope, so every
repo-specific rule stays visible in every other project forever.

This script performs that split once, by hand-checked classification.

The hard part is not the file I/O, it is deciding which rules are repo-scoped.
That is a judgement about the user's intent, so this script refuses to guess
silently: it classifies by explicit keyword match, prints the plan, and writes
nothing without --apply. Rules that match no keyword go to `SPEC.md` (global),
which is the safe default — a global rule that did not need to be global costs
tokens, while a repo rule mis-filed as global is followed in the wrong repo.

Usage:
    migrate_preferences_to_spec.py [--namespace NAME ...] [--root PATH]
                                   [--apply] [--backup-dir PATH]

With no --namespace, every namespace under --root that has a PREFERENCES.md is
processed. Always writes a backup of the original file before replacing it.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".memories"

# Repo name -> substrings that mark a rule as belonging to that repo. Extend
# this when a namespace has projects the defaults do not know about; an
# unmatched rule falls through to SPEC.md, so a miss is visible rather than
# silently wrong.
PROJECT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "using-memory": ("using-memory", "memory_hook_common", "version.txt"),
    "gala": ("Gala", "gala"),
    "dozo": ("Dozo", "dozo"),
    "xianyu": ("xianyu",),
    "civil-forest": ("civil-forest", "Civil Forest"),
    "iceberg": ("iceberg", "Iceberg"),
    "voli": ("voli",),
    "horizon": ("Horizon",),
}

# Rules that name a repo only as an example ("any project, not just iceberg").
# Classifying these per-repo would narrow a rule the user meant globally, which
# is the opposite error and also silent.
GLOBAL_MARKERS: tuple[str, ...] = (
    "\u4efb\u4f55\u9879\u76ee",  # "any project"
    "\u4efb\u4f55 repository",
    "all projects",
    "every project",
)

# "not only X" / "not just X" phrased in either language: the repo is named as
# an example, so the rule is global. Without this the worktree rule was filed
# under `iceberg` even though its own text says it applies everywhere.
GLOBAL_EXAMPLE_PATTERNS: tuple[str, ...] = (
    "not only ",
    "not just ",
    "\u4e0d\u53ea ",  # "not only"
    "\u4e0d\u4ec5\u4ec5\u662f ",
)

BULLET = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] (.*)$", re.S)


def parse_rules(path: Path) -> list[tuple[str, str]]:
    """Return [(date, body)] for each bullet in the file."""
    text = path.read_text(encoding="utf-8")
    out: list[tuple[str, str]] = []
    for chunk in re.split(r"\n\s*\n", text):
        chunk = chunk.strip()
        if not chunk.startswith("- ["):
            continue
        m = BULLET.match(chunk)
        if not m:
            print(f"  !! unparsed entry begins: {chunk[:70]!r}", file=sys.stderr)
            continue
        out.append((m.group(1), m.group(2).strip()))
    return out


def classify(body: str) -> str:
    if any(marker in body for marker in GLOBAL_MARKERS):
        return "global"
    hits = [repo for repo, words in PROJECT_KEYWORDS.items() if any(w in body for w in words)]
    if hits and any(p in body.lower() for p in GLOBAL_EXAMPLE_PATTERNS):
        return "global"
    if len(hits) > 1:
        # Ambiguous: pick the first and say so. The operator reviews the plan.
        print(f"  ?? matches {hits}; defaulting to {hits[0]}: {body[:60]!r}", file=sys.stderr)
    return hits[0] if hits else "global"


GLOBAL_HEADER = (
    "# Spec\n\n"
    "Rules and constraints that apply to every project in this namespace.\n"
    "Project-specific specs live in `spec/<repo>.md`.\n\n"
)


def project_header(repo: str) -> str:
    return (
        f"# Spec — {repo}\n\n"
        f"Constraints for the `{repo}` repository. "
        "Loaded only when working in that repo.\n\n"
    )


def migrate_namespace(ns_dir: Path, *, apply: bool, backup_dir: Path) -> int:
    source = ns_dir / "PREFERENCES.md"
    if not source.is_file():
        return 0

    target = ns_dir / "SPEC.md"
    if target.is_file():
        print(f"{ns_dir.name}: SPEC.md already exists — refusing to overwrite. "
              "Merge by hand.", file=sys.stderr)
        return 0

    rules = parse_rules(source)
    if not rules:
        print(f"{ns_dir.name}: no rules parsed; nothing to do")
        return 0

    buckets: dict[str, list[tuple[str, str]]] = {}
    for date, body in rules:
        buckets.setdefault(classify(body), []).append((date, body))

    print(f"\n{ns_dir.name}: {len(rules)} rules from {source.name}")
    for scope, rows in sorted(buckets.items(), key=lambda kv: (kv[0] != "global", kv[0])):
        print(f"  {scope:16s} {len(rows):2d}")

    if not apply:
        return len(rules)

    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup_dir / f"{ns_dir.name}-PREFERENCES.md")
    print(f"  backup -> {backup_dir / (ns_dir.name + '-PREFERENCES.md')}")

    def render(header: str, rows: list[tuple[str, str]]) -> str:
        return header + "\n\n".join(f"- [{d}] {b}" for d, b in rows) + "\n"

    target.write_text(render(GLOBAL_HEADER, buckets.get("global", [])), encoding="utf-8")
    spec_dir = ns_dir / "spec"
    for scope, rows in buckets.items():
        if scope == "global":
            continue
        spec_dir.mkdir(exist_ok=True)
        (spec_dir / f"{scope}.md").write_text(
            render(project_header(scope), rows), encoding="utf-8"
        )

    # Only after both files are on disk: a crash between the two would leave the
    # old file as the only copy, and the loader prefers SPEC.md when it exists.
    source.unlink()
    print(f"  wrote SPEC.md + {len(buckets) - (1 if 'global' in buckets else 0)} project file(s); removed {source.name}")
    return len(rules)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help=f"directory containing namespace dirs (default: {DEFAULT_ROOT})")
    parser.add_argument("--namespace", action="append", default=None,
                        help="namespace to migrate (repeatable; default: all that need it)")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument("--backup-dir", type=Path, default=None,
                        help="where to copy the original (default: <root>/.migration-backup-<ts>)")
    args = parser.parse_args(argv)

    root = args.root.expanduser()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    if args.namespace:
        namespaces = [root / n for n in args.namespace]
    else:
        namespaces = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))

    backup_dir = args.backup_dir or root / f".migration-backup-{datetime.now():%Y%m%d-%H%M%S}"

    total = 0
    for ns_dir in namespaces:
        total += migrate_namespace(ns_dir, apply=args.apply, backup_dir=backup_dir)

    if total == 0:
        print("\nnothing to migrate")
        return 0
    if not args.apply:
        print(f"\ndry run: {total} rule(s) would be migrated — pass --apply to write")
        return 0
    print(f"\nmigrated {total} rule(s)")
    print("Review the result before committing: classification is a judgement call, "
          "and a repo rule left in SPEC.md is followed in the wrong repository.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
