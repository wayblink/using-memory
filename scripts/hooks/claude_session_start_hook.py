#!/usr/bin/env python3
"""Claude SessionStart wrapper that combines using-superpowers and using-memory."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _using_superpowers_path() -> Path:
    claude_home = Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude")).expanduser()
    return claude_home / "skills" / "using-superpowers" / "SKILL.md"


def _read_using_superpowers() -> str:
    path = _using_superpowers_path()
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return (
            "## using-superpowers warning\n\n"
            f"Expected skill file not found at `{path}`. "
            "SessionStart continues, but startup skill guidance is missing."
        )
    return (
        "<EXTREMELY-IMPORTANT>\n"
        "You have superpowers.\n\n"
        "**Below is the full content of your 'using-superpowers' skill - your "
        "introduction to using skills. For all other skills, use the 'Skill' tool:**\n\n"
        f"{content}\n\n"
        "</EXTREMELY-IMPORTANT>"
    )


def _memory_context(payload_text: str) -> str | None:
    hook_path = Path(__file__).with_name("claude_memory_hook.py")
    try:
        proc = subprocess.run(
            [sys.executable or "python3", str(hook_path)],
            input=payload_text,
            text=True,
            capture_output=True,
            timeout=20,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        output = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    hook_output = output.get("hookSpecificOutput") if isinstance(output, dict) else None
    if not isinstance(hook_output, dict):
        return None
    context = hook_output.get("additionalContext")
    return context if isinstance(context, str) and context.strip() else None


def main() -> int:
    payload_text = sys.stdin.read()
    sections = [_read_using_superpowers()]
    memory_context = _memory_context(payload_text)
    if memory_context:
        sections.append(memory_context)
    result = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n---\n\n".join(section for section in sections if section),
        }
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
