#!/usr/bin/env python3
"""Shared hook logic for the using-memory Codex and Claude adapters."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


MEMORY_WRITE_RE = re.compile(
    r"(memory_tool\.py\s+(write-log|write-memory|write-preference|upsert-doc)|\bwrite-log\b|\bwrite-memory\b|\bwrite-preference\b|\bupsert-doc\b)",
    re.IGNORECASE,
)

MEMORY_PROMPT_RE = re.compile(
    r"(memory|remember|forget|preference|prior context|previous work|continue|resume|project history|saved decisions|"
    r"log|operation|commit|push|build|test|deploy|hook)",
    re.IGNORECASE,
)

IMPORTANT_OPERATION_RE = re.compile(
    r"(apply_patch|write|edit|git\s+(commit|push|merge|rebase|cherry-pick|tag)|"
    r"npm\s+(test|run|build)|pnpm\s+(test|run|build)|yarn\s+(test|run|build)|"
    r"pytest|cargo\s+test|go\s+test|mvn\s+test|gradle|"
    r"deploy|release|restart|service|systemctl|docker|kubectl|"
    r"error|failed|failure|fix|debug|hook|settings\.json|hooks\.json|config\.toml|AGENTS\.md|CLAUDE\.md)",
    re.IGNORECASE,
)


def load_payload() -> dict[str, Any]:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


def event_name(payload: dict[str, Any]) -> str:
    return str(payload.get("hook_event_name") or payload.get("hookEventName") or payload.get("event") or "")


def turn_key(payload: dict[str, Any]) -> str:
    return str(
        payload.get("turn_id")
        or payload.get("tool_use_id")
        or payload.get("session_id")
        or payload.get("transcript_path")
        or "default"
    )


def session_key(payload: dict[str, Any], host: str) -> str:
    raw = str(payload.get("session_id") or payload.get("transcript_path") or "default")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)[-120:] or "default"
    return f"{host}-{safe}"


def state_path(payload: dict[str, Any], host: str) -> Path:
    root = Path(os.environ.get("USING_MEMORY_HOOK_STATE_DIR", Path(tempfile.gettempdir()) / "using-memory-hooks"))
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{session_key(payload, host)}.json"


def load_state(payload: dict[str, Any], host: str) -> dict[str, Any]:
    path = state_path(payload, host)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(payload: dict[str, Any], host: str, state: dict[str, Any]) -> None:
    path = state_path(payload, host)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stringify(value: Any, limit: int = 4000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = str(value)
    return text[:limit]


def prompt_text(payload: dict[str, Any]) -> str:
    return "\n".join(
        stringify(payload.get(key))
        for key in ("prompt", "user_prompt", "message", "input")
        if payload.get(key) is not None
    )


def tool_text(payload: dict[str, Any]) -> str:
    parts = [
        stringify(payload.get("tool_name")),
        stringify(payload.get("tool_input")),
        stringify(payload.get("tool_response")),
        stringify(payload.get("tool_output")),
        stringify(payload.get("result")),
    ]
    return "\n".join(part for part in parts if part)


def assistant_text(payload: dict[str, Any]) -> str:
    return stringify(payload.get("last_assistant_message"), limit=6000)


def additional_context(event: str, text: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": text,
        }
    }


def memory_protocol_reminder() -> str:
    return (
        "using-memory hook reminder: consider the using-memory skill for persisted context. "
        "Load memory only when it can change the answer. For writes, default toward recording "
        "concrete operations and key events to <namespace>/log/YYYY-MM-DD.jsonl via "
        "scripts/memory_tool.py write-log. Do not mirror every tool call or raw transcript. "
        "Stable preferences go to write-preference; stable facts, confirmed decisions, and lessons "
        "go to write-memory."
    )


def stop_gate_reason(events: list[str], last_message: str) -> str:
    event_summary = "; ".join(events[-6:]) if events else "the final answer indicates completed work"
    return (
        "Before stopping, enforce the using-memory write gate. This turn appears to contain operation "
        f"history that should survive restart: {event_summary}. Run scripts/memory_tool.py write-log "
        "against the configured memory repo and record the concrete operation facts/key events: commands "
        "or hook events when relevant, affected files, result status, commit/PR/deploy identifiers if any, "
        "verification performed, and unresolved risks. Keep durable MEMORY.md curated; use the JSONL log "
        "for comprehensive operation history. After the log write succeeds, continue with the final response."
    )


def run(host: str) -> int:
    payload = load_payload()
    event = event_name(payload)
    state = load_state(payload, host)
    current_turn = turn_key(payload)

    if event == "SessionStart":
        state.setdefault("turn", current_turn)
        state.setdefault("memory_written", False)
        state.setdefault("important_events", [])
        save_state(payload, host, state)
        print(json.dumps(additional_context(event, memory_protocol_reminder()), ensure_ascii=False))
        return 0

    if event == "UserPromptSubmit":
        prompt = prompt_text(payload)
        state["turn"] = current_turn
        state["memory_written"] = False
        state["important_events"] = []
        state["prompt_mentions_memory"] = bool(MEMORY_PROMPT_RE.search(prompt))
        save_state(payload, host, state)
        if state["prompt_mentions_memory"]:
            print(json.dumps(additional_context(event, memory_protocol_reminder()), ensure_ascii=False))
        return 0

    if event in {"PostToolUse", "PostToolBatch", "PostToolUseFailure", "PermissionDenied", "ConfigChange"}:
        text = tool_text(payload) or stringify(payload)
        if MEMORY_WRITE_RE.search(text):
            state["memory_written"] = True
        if IMPORTANT_OPERATION_RE.search(text):
            events = list(state.get("important_events") or [])
            summary = re.sub(r"\s+", " ", text).strip()[:500]
            if summary and summary not in events:
                events.append(summary)
            state["important_events"] = events[-20:]
        save_state(payload, host, state)
        return 0

    if event in {"Stop", "SubagentStop"}:
        if payload.get("stop_hook_active"):
            print("{}")
            return 0
        last_message = assistant_text(payload)
        if MEMORY_WRITE_RE.search(last_message):
            state["memory_written"] = True
            save_state(payload, host, state)
            print("{}")
            return 0
        events = list(state.get("important_events") or [])
        prompt_mentions_memory = bool(state.get("prompt_mentions_memory"))
        final_mentions_work = bool(IMPORTANT_OPERATION_RE.search(last_message))
        should_gate = (events or prompt_mentions_memory or final_mentions_work) and not state.get("memory_written")
        save_state(payload, host, state)
        if should_gate:
            print(json.dumps({"decision": "block", "reason": stop_gate_reason(events, last_message)}, ensure_ascii=False))
            return 0
        print("{}")
        return 0

    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run("generic"))
