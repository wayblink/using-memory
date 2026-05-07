#!/usr/bin/env python3
"""View log entries in human-friendly Markdown format."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def format_entry_markdown(entry: dict, show_metadata: bool = True) -> str:
    """Format a single entry as Markdown."""
    lines = []

    # Header with timestamp and tag
    ts = entry.get('ts', '')
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            time_str = dt.strftime('%H:%M:%S')
        except ValueError:
            time_str = ts
    else:
        time_str = '??:??:??'

    tag = entry.get('tag', 'note')
    project = entry.get('project', '')
    component = entry.get('component', '')

    header_parts = [f"**{time_str}**", f"[{tag}]"]
    if project:
        header_parts.append(f"`{project}`")
    if component:
        header_parts.append(f"`{component}`")

    lines.append(' '.join(header_parts))
    lines.append('')

    # Main text
    text = entry.get('text', '')
    lines.append(text)

    # Metadata section
    if show_metadata:
        metadata_lines = []

        # Files
        files = entry.get('files', [])
        if files:
            metadata_lines.append('**Related files:**')
            for f in files:
                metadata_lines.append(f'- `{f}`')

        # Metrics
        metrics = entry.get('metrics', {})
        if metrics:
            metadata_lines.append('**Metrics:**')
            for k, v in metrics.items():
                metadata_lines.append(f'- {k}: {v}')

        # Duration
        duration = entry.get('duration_sec')
        if duration:
            metadata_lines.append(f'**Duration:** {duration}s')

        # Confidence
        confidence = entry.get('confidence')
        if confidence:
            metadata_lines.append(f'**Confidence:** {confidence}/10')

        # Source
        source = entry.get('source')
        if source and source != 'user':
            metadata_lines.append(f'**Source:** {source}')

        if metadata_lines:
            lines.append('')
            lines.extend(metadata_lines)

    return '\n'.join(lines)


def view_log(log_file: Path, level_filter: str = None, tag_filter: str = None,
             project_filter: str = None, show_metadata: bool = True):
    """View a log file in Markdown format."""
    if not log_file.exists():
        print(f"Error: {log_file} does not exist", file=sys.stderr)
        sys.exit(1)

    # Parse filters
    levels = set(level_filter.split(',')) if level_filter else None
    tags = set(tag_filter.split(',')) if tag_filter else None
    projects = set(project_filter.split(',')) if project_filter else None

    # Print header
    date_str = log_file.stem
    print(f"# {date_str} Operation Log\n")

    entry_count = 0
    with log_file.open('r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)

                # Apply filters
                if levels and entry.get('level') not in levels:
                    continue
                if tags and entry.get('tag') not in tags:
                    continue
                if projects and entry.get('project') not in projects:
                    continue

                # Format and print
                if entry_count > 0:
                    print('\n---\n')

                print(format_entry_markdown(entry, show_metadata))
                entry_count += 1

            except json.JSONDecodeError as e:
                print(f"Warning: line {line_num} invalid JSON: {e}", file=sys.stderr)
                continue

    if entry_count == 0:
        print("(No matching log entries)")

    print(f"\n---\n**Total:** {entry_count} log entries")


def main():
    parser = argparse.ArgumentParser(description='View log entries in Markdown format')
    parser.add_argument('--date', required=True, help='Date in YYYY-MM-DD format')
    parser.add_argument('--level', help='Filter by level (comma-separated): detail,summary')
    parser.add_argument('--tag', help='Filter by tag (comma-separated)')
    parser.add_argument('--project', help='Filter by project (comma-separated)')
    parser.add_argument('--no-metadata', action='store_true', help='Hide metadata section')
    parser.add_argument('--log-dir', help='Log directory (default: ~/.memories/main/log)')

    args = parser.parse_args()

    if args.log_dir:
        log_dir = Path(args.log_dir)
    else:
        log_dir = Path.home() / '.memories/main/log'

    log_file = log_dir / f'{args.date}.jsonl'

    view_log(
        log_file,
        level_filter=args.level,
        tag_filter=args.tag,
        project_filter=args.project,
        show_metadata=not args.no_metadata
    )


if __name__ == '__main__':
    main()
