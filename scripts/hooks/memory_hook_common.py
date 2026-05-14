#!/usr/bin/env python3
"""Shared hook logic for the using-memory Codex and Claude adapters."""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


# Threshold: every N real human user turns, escalate Stop hook to a hard block
# requiring a detail-level write-log. Other turns get a silent summary append.
STOP_DETAIL_TURN_INTERVAL = 8

# Cap on how many summary appends a single session will perform. Belt-and-braces
# against an infinite loop if a hook bug causes Stop to fire repeatedly without
# the turn counter advancing.
SUMMARY_APPEND_SESSION_CAP = 200


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
    """Block reason for the Stop gate.

    Kept short on purpose. The model already has the full operation history
    in its own conversation context for the current turn — replaying tool
    payloads through this reason is wasted tokens and noisy stderr for the
    user. We surface just enough signal (event count + tool kinds) for the
    model to know what to record.
    """
    count = len(events)
    if count:
        kinds = []
        seen: set[str] = set()
        for evt in events:
            # _compact_event_summary always produces "kind: ..." prefixes,
            # but historical state files may still hold raw payloads. Be
            # defensive about the parse so we never fall over.
            kind = evt.split(":", 1)[0].strip() if ":" in evt else evt[:20].strip()
            if kind and kind not in seen:
                seen.add(kind)
                kinds.append(kind)
            if len(kinds) >= 5:
                break
        kinds_label = ", ".join(kinds) if kinds else "operation"
        return (
            f"Before stopping, run scripts/memory_tool.py write-log to record this turn: "
            f"{count} important event(s) [{kinds_label}]. Include affected files, result, "
            f"identifiers (commit/PR/deploy), verification, and unresolved risks."
        )
    return (
        "Before stopping, run scripts/memory_tool.py write-log to record this turn's "
        "concrete operations, result, identifiers, verification, and unresolved risks."
    )


def precompact_gate_reason() -> str:
    """Compact block reason for PreCompact. Same philosophy as stop_gate_reason."""
    return (
        "Context will be compacted shortly. Run scripts/memory_tool.py write-log "
        "(level=summary) before the window shrinks: current task and unfinished "
        "subgoals, key identifiers (paths/SHAs/branches/PR/deploy), open risks. "
        "Promote any confirmed decisions or lessons to write-memory."
    )


# Compact 60-char-ish hint suffixes for the most common tools. Kept agnostic
# so both Claude Code and Codex payload shapes can feed in; missing keys are
# tolerated.
def _compact_event_summary(payload: dict[str, Any], fallback_text: str) -> str:
    """Build a short event summary like ``Bash: git push origin main`` or
    ``Write: scripts/memory_tool.py``.

    Falls back to the first 80 chars of fallback_text when the payload has no
    recognisable tool_name. Total output is hard-capped at 100 chars so the
    state file stays bounded.
    """
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "").strip()
    ti = payload.get("tool_input") or payload.get("toolInput") or {}
    hint = ""
    if isinstance(ti, dict):
        # Order matters: prefer command for shell tools, then file/path for
        # write/edit tools, then a generic stringify.
        for key in ("command", "file_path", "path", "notebook_path", "url", "query", "pattern"):
            value = ti.get(key)
            if isinstance(value, str) and value.strip():
                hint = value.strip()
                break
        if not hint:
            try:
                hint = json.dumps(ti, ensure_ascii=False)[:80]
            except Exception:
                hint = str(ti)[:80]
    if tool_name:
        hint_part = f": {hint}" if hint else ""
        summary = f"{tool_name}{hint_part}"
    else:
        # No tool_name (e.g. ConfigChange / PermissionDenied) — fall back to a
        # whitespace-collapsed snippet of the raw text.
        summary = re.sub(r"\s+", " ", fallback_text).strip()
    summary = re.sub(r"\s+", " ", summary).strip()
    return summary[:100]


def count_human_turns(transcript_path: str | None) -> int:
    """Count real human user turns in a Claude Code transcript JSONL.

    Filters out tool_result list-form user entries and synthetic str entries
    that begin with system/command tags or echo "Stop hook feedback:". Returns
    0 on any error (best-effort, hook must never fail).
    """
    if not transcript_path:
        return 0
    try:
        path = Path(transcript_path)
        if not path.exists() or not path.is_file():
            return 0
        count = 0
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "user":
                    continue
                msg = entry.get("message", {})
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content", "")
                if not isinstance(content, str):
                    # tool_result list-form — not a human turn
                    continue
                stripped = content.lstrip()
                if not stripped:
                    continue
                if stripped.startswith("<"):
                    # <system-reminder>, <command-message>, <user-prompt-submit-hook>, <command-name>, ...
                    continue
                if stripped.startswith("Stop hook feedback:"):
                    continue
                count += 1
        return count
    except Exception:
        return 0


def _resolve_memory_config() -> str | None:
    """Locate the using-memory config file. Returns None if not found."""
    env = os.environ.get("USING_MEMORY_CONFIG")
    if env and Path(env).expanduser().exists():
        return str(Path(env).expanduser())
    fallback = Path.home() / ".skills" / "using-memory" / "config.yaml"
    if fallback.exists():
        return str(fallback)
    return None


def _memory_tool_path() -> str:
    return str(Path.home() / ".claude" / "skills" / "using-memory" / "scripts" / "memory_tool.py")


def _stats_path() -> Path | None:
    """Resolve <primary memory root>/<namespace>/local/STATS.json.

    Returns None when the config isn't readable yet — silent fail keeps
    hook stability strict; STATS.json is best-effort accounting.
    """
    try:
        config = _resolve_memory_config()
        if not config:
            return None
        import yaml as _yaml  # local import: hook common avoids hard dep until needed
        with open(config, "r", encoding="utf-8") as fh:
            cfg = _yaml.safe_load(fh) or {}
        roots = cfg.get("memory_roots") or []
        for root in roots:
            if not isinstance(root, dict):
                continue
            if root.get("role") != "primary":
                continue
            raw = root.get("path")
            if not raw:
                continue
            namespace = root.get("namespace") or "main"
            base = Path(os.path.expanduser(os.path.expandvars(str(raw))))
            return base / str(namespace) / "local" / "STATS.json"
    except Exception:
        return None
    return None


def bump_stats(deltas: dict[str, Any]) -> None:
    """Atomically add ``deltas`` into <namespace>/local/STATS.json.

    Each key in ``deltas`` is an integer counter; missing keys initialise to
    0. Updates ``last_event_ts`` to wall-clock. Best-effort: any I/O or
    parsing failure is swallowed so hook stability isn't tied to stats.
    """
    if not deltas:
        return
    path = _stats_path()
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        except (OSError, json.JSONDecodeError):
            current = {}
        lifetime = current.setdefault("lifetime", {})
        for key, delta in deltas.items():
            try:
                delta_int = int(delta)
            except (TypeError, ValueError):
                continue
            lifetime[key] = int(lifetime.get(key, 0) or 0) + delta_int
        current["last_event_ts"] = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        return


# Tool names that produce or modify a file we want to refresh in anatomy.
_ANATOMY_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Create"}


def _extract_written_paths(payload: dict[str, Any]) -> list[str]:
    """Pull file paths out of a PostToolUse payload for anatomy upsert.

    Looks at payload.tool_name + payload.tool_input. Returns absolute path
    strings only when the tool was a write/edit-style operation. Returns []
    for read-style tools so we don't waste a subprocess on every Bash call.
    """
    tool_name = str(payload.get("tool_name") or "").strip()
    if tool_name not in _ANATOMY_WRITE_TOOLS:
        return []
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        return []
    paths: list[str] = []
    fp = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
    if isinstance(fp, str) and fp:
        paths.append(fp)
    # MultiEdit may stash a list of edits — each entry shares the same file_path,
    # so the top-level file_path above is enough. Defensive: also check edits[].
    edits = ti.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if isinstance(edit, dict):
                p = edit.get("file_path") or edit.get("path")
                if isinstance(p, str) and p and p not in paths:
                    paths.append(p)
    return paths


def anatomy_upsert_for_payload(payload: dict[str, Any]) -> None:
    """Best-effort: call `memory_tool.py anatomy-upsert-file <path>` for every
    file written/edited by this tool call. Silent on failure — anatomy drift
    is recoverable via `anatomy-scan`, blocking hooks on this is not.

    Counts each subprocess that returned action=updated|removed into
    anatomy_upserts so the dashboard can show incremental maintenance volume.
    """
    try:
        paths = _extract_written_paths(payload)
        if not paths:
            return
        config = _resolve_memory_config()
        if not config:
            return
        upserts = 0
        for raw in paths:
            try:
                cmd = [
                    sys.executable or "python3",
                    _memory_tool_path(),
                    "anatomy-upsert-file",
                    "--config", config,
                    raw,
                    "--json",
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=8, text=True)
                if result.returncode == 0:
                    try:
                        data = json.loads(result.stdout or "{}")
                        if data.get("changed"):
                            upserts += 1
                    except json.JSONDecodeError:
                        pass
            except Exception:
                continue
        if upserts:
            bump_stats({"anatomy_upserts": upserts})
    except Exception:
        return


def fetch_session_start_anatomy(payload: dict[str, Any]) -> tuple[str | None, dict[str, int]]:
    """Best-effort: call `memory_tool.py load --anatomy --json` and return
    (markdown, stats_deltas) for the SessionStart context injection.

    ``stats_deltas`` is an empty dict on failure / no anatomy; otherwise it
    contains the counters this call earned (e.g. anatomy_attached_count=1,
    anatomy_attached_tokens_est=N, anatomy_truncated_count=1,
    anatomy_hint_emitted=1). Caller funnels it into bump_stats so the
    counters reflect what actually happened.
    """
    deltas: dict[str, int] = {}
    try:
        config = _resolve_memory_config()
        if not config:
            return None, deltas
        cwd = payload.get("cwd") or os.getcwd()
        cmd = [
            sys.executable or "python3",
            _memory_tool_path(),
            "load",
            "--config", config,
            "--anatomy",
            "--cwd", cwd,
            "--json",
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=20, text=True)
        if result.returncode != 0:
            return None, deltas
        data = json.loads(result.stdout or "{}")
        anatomy = data.get("anatomy") if isinstance(data, dict) else None
        if not isinstance(anatomy, dict):
            return None, deltas
        if anatomy.get("matched"):
            content = anatomy.get("content") or ""
            warning = anatomy.get("warning") or ""
            if content:
                deltas["anatomy_attached_count"] = 1
                # ``content`` is already capped by load --anatomy-max-tokens.
                # We record the rendered char count over the estimator ratio
                # (~3.75 chars/token mixed) so the dashboard shows a real
                # number, not the per-call cap.
                deltas["anatomy_attached_tokens_est"] = max(1, int(len(content) / 3.75 + 0.5))
                if anatomy.get("truncated"):
                    deltas["anatomy_truncated_count"] = 1
                return content, deltas
            if warning:
                deltas["anatomy_attached_count"] = 1  # matched but unscanned still counts as an attach attempt
                return f"## Anatomy\n\n{warning}\n", deltas
            return None, deltas
        hint = anatomy.get("hint")
        if hint:
            deltas["anatomy_hint_emitted"] = 1
            return f"## Anatomy hint\n\n{hint}\n", deltas
        return None, deltas
    except Exception:
        return None, deltas


def silent_summary_write(payload: dict[str, Any], state: dict[str, Any], last_message: str) -> bool:
    """Best-effort: write a level=summary log entry capturing this turn's events.

    Returns True if the subprocess returned 0, False otherwise. Never raises;
    hook stability is more important than log fidelity.
    """
    try:
        events = list(state.get("important_events") or [])
        if not events and not last_message.strip():
            return False
        config = _resolve_memory_config()
        if not config:
            return False
        cwd = payload.get("cwd") or os.getcwd()
        body_lines = ["## Auto-summary (silent hook append)", ""]
        body_lines.append(f"Cwd: {cwd}")
        gb = payload.get("git_branch") or payload.get("gitBranch")
        if gb:
            body_lines.append(f"Git branch: {gb}")
        if events:
            body_lines.append("")
            body_lines.append(f"Events (last {min(6, len(events))}):")
            for evt in events[-6:]:
                body_lines.append(f"- {evt[:240]}")
        if last_message:
            tail = re.sub(r"\s+", " ", last_message).strip()
            if tail:
                body_lines.append("")
                body_lines.append(f"Final: {tail[:400]}")
        text = "\n".join(body_lines)
        cmd = [
            sys.executable or "python3",
            _memory_tool_path(),
            "write-log",
            "--config", config,
            "--date", _dt.date.today().isoformat(),
            "--tag", "progress",
            "--level", "summary",
            "--source", "auto",
            "--text", text,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        return result.returncode == 0
    except Exception:
        return False


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
        reminder = memory_protocol_reminder()
        anatomy_md, anatomy_deltas = fetch_session_start_anatomy(payload)
        if anatomy_md:
            context_text = f"{reminder}\n\n---\n\n{anatomy_md}"
        else:
            context_text = reminder
        bump_stats({"sessions": 1, **anatomy_deltas})
        print(json.dumps(additional_context(event, context_text), ensure_ascii=False))
        return 0

    if event == "UserPromptSubmit":
        prompt = prompt_text(payload)
        state["turn"] = current_turn
        state["memory_written"] = False
        state["important_events"] = []
        state["prompt_mentions_memory"] = bool(MEMORY_PROMPT_RE.search(prompt))
        # NOTE: do NOT reset last_save_turn / last_summary_turn / summary_append_count
        # here. Those track lifetime-of-session counters used by the Stop throttle.
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
            summary = _compact_event_summary(payload, text)
            if summary and summary not in events:
                events.append(summary)
            state["important_events"] = events[-20:]
        save_state(payload, host, state)
        # Best-effort anatomy refresh for write/edit tools. Always last so
        # state persistence is never blocked by an anatomy subprocess.
        if event == "PostToolUse":
            anatomy_upsert_for_payload(payload)
        return 0

    if event in {"Stop", "SubagentStop"}:
        if payload.get("stop_hook_active"):
            print("{}")
            return 0
        last_message = assistant_text(payload)
        transcript_path = payload.get("transcript_path") or payload.get("transcriptPath")
        current_turns = count_human_turns(transcript_path)

        # If the model just wrote memory in this final response, record the
        # checkpoint and pass through.
        if MEMORY_WRITE_RE.search(last_message):
            state["memory_written"] = True
            state["last_save_turn"] = current_turns
            save_state(payload, host, state)
            print("{}")
            return 0

        events = list(state.get("important_events") or [])
        prompt_mentions_memory = bool(state.get("prompt_mentions_memory"))
        final_mentions_work = bool(IMPORTANT_OPERATION_RE.search(last_message))
        is_substantial = bool(events or final_mentions_work)

        last_save_turn = int(state.get("last_save_turn") or 0)
        delta = max(0, current_turns - last_save_turn)
        threshold_reached = is_substantial and delta >= STOP_DETAIL_TURN_INTERVAL

        # Hard gate fires when:
        #   (a) the user explicitly mentioned memory keywords this turn, OR
        #   (b) the throttling threshold is reached (every N=8 user turns of
        #       substantive work).
        # `memory_written` short-circuits both — no need to gate twice.
        should_gate = (prompt_mentions_memory or threshold_reached) and not state.get("memory_written")

        if should_gate:
            save_state(payload, host, state)
            bump_stats({"stop_blocks": 1})
            print(json.dumps({"decision": "block", "reason": stop_gate_reason(events, last_message)}, ensure_ascii=False))
            return 0

        # Quiet path: silently append a level=summary log for substantial work
        # we did not block on. Dedup by current_turns so the same human turn
        # never produces multiple summary entries even if Stop fires several
        # times within it (sub-agent finishes, etc.).
        last_summary_turn = int(state.get("last_summary_turn") or -1)
        summary_count = int(state.get("summary_append_count") or 0)
        wrote_summary = False
        if (
            is_substantial
            and current_turns > 0
            and current_turns != last_summary_turn
            and summary_count < SUMMARY_APPEND_SESSION_CAP
        ):
            ok = silent_summary_write(payload, state, last_message)
            if ok:
                state["last_summary_turn"] = current_turns
                state["summary_append_count"] = summary_count + 1
                wrote_summary = True

        save_state(payload, host, state)
        deltas = {"stop_throttled_passthrough": 1}
        if wrote_summary:
            deltas["log_entries_auto"] = 1
        bump_stats(deltas)
        print("{}")
        return 0

    if event == "PreCompact":
        if payload.get("stop_hook_active") or payload.get("precompact_hook_active"):
            print("{}")
            return 0
        last_message = assistant_text(payload)
        if MEMORY_WRITE_RE.search(last_message):
            state["memory_written"] = True
            save_state(payload, host, state)
            print("{}")
            return 0
        save_state(payload, host, state)
        bump_stats({"precompact_blocks": 1})
        print(json.dumps({"decision": "block", "reason": precompact_gate_reason()}, ensure_ascii=False))
        return 0

    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run("generic"))
