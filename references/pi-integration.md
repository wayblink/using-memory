# Pi Integration

`using-memory` ships a Pi package at `packages/pi`. It gives Pi the same three things the Codex and Claude Code skills provide — a memory tool, a `/umem` command, and the session hooks — plus one thing Pi needs that the others do not: a native tool call instead of a shell invocation.

## Why an extension and not just a skill

A skill alone would put `SKILL.md`'s name and description in the system prompt and leave the body unloaded until the model decided to read it. The routing rules that decide *which file a write goes to* (`SPEC.md` / `spec/<repo>.md` vs `MEMORY.md` vs `log/*.jsonl`) are load-bearing on every turn, so they live in the tool's `promptGuidelines` instead — see `packages/pi/extensions/umem/guidance.ts`.

The extension is also what carries the hooks. Pi has no `settings.json` hook table to edit: an extension registers its own handlers with `pi.on(...)`.

## Install

```bash
scripts/link.sh pi     # symlink this checkout into Pi's agent dir (development)
scripts/install.sh pi  # copy it (a normal install)
scripts/install.sh all # codex + claude-code + pi
```

`PI_AGENT_DIR` overrides the target (default `~/.pi/agent`). The two resource directories are:

| Resource | Path | What Pi does with it |
|---|---|---|
| Extension | `<agent-dir>/extensions/umem/` | loads `index.ts` via jiti at startup |
| Skill | `<agent-dir>/skills/umem/` | advertises `umem` in the system prompt, loads the body on demand |

The extension is copied/linked from `packages/pi`; the skill is the checkout root (`link.sh` symlinks it, `install.sh` copies `SKILL.md` plus `references/` and `examples/`). The skill directory **must** be named `umem`, matching the `name:` in the frontmatter, and its `SKILL.md` must sit next to `references/` and `examples/` because the body links to them relatively.

A package install (`pi install ./packages/pi`) loads the extension only. That is deliberate: `packages/pi` ships no copy of `SKILL.md`. A packaged copy is a second physical file declaring `name: umem`, and on a machine that also exposes the skill through an Agent Skills directory (`~/.agents/skills/using-memory` → this checkout) Pi reports `name "umem" collision` and silently drops one of the two. The dropped one is the copy, whose `references/...` links do not resolve anyway. Install the skill with `scripts/link.sh pi` / `scripts/install.sh pi`, or expose the checkout root in `~/.agents/skills/`.

## Event mapping

The Codex and Claude adapters share `scripts/hooks/memory_hook_common.py`, driven by a host that fires `SessionStart` / `UserPromptSubmit` / `PostToolUse` / `Stop`. Pi fires different events with different payloads.

| Codex / Claude Code | Pi | Fidelity |
|---|---|---|
| `SessionStart` | `session_start` | full |
| `UserPromptSubmit` | `before_agent_start` | full |
| `PostToolUse` / `PostToolBatch` | `tool_execution_end` + `tool_call` | full, and more precise |
| `Stop` (blocking) | `agent_before_settle` | **partial** — see below |
| `PreCompact` | `session_before_compact` | re-injects the snapshot when compaction drops messages |

What each does:

- **`session_start`** — injects the protocol reminder plus a compact snapshot (saved preferences, durable memory, recent log entries) as a non-displayed message delivered on the next turn. `reason: "reload"` re-injects nothing: the conversation already carries it. A resumed session seeds its turn counter from the existing branch, so the first settle does not look like a 50-turn delta.
- **`before_agent_start`** — resets the per-turn flags and records whether the prompt mentions memory.
- **`tool_execution_end`** — accumulates one-line summaries of substantial operations (`write`, `edit`, `bash`, …).
- **`tool_call`** — sets the `memoryWritten` flag when a `umem` call carries a **write** action. Reads (`load`, `search`, `status`, `maintain`) deliberately do not count: a `load` must not satisfy the gate.

## The gate, and how it differs from a Stop hook

Pi has no hook that can refuse to stop. The equivalent is appending a `custom_message` entry at `agent_before_settle` and returning `continue: true`, which asks Pi for **one more model request**. Two consequences:

1. **It costs a request.** The threshold is therefore looser than the hook hosts' 20 turns: `pi.detail_turn_interval` defaults to **30**.
2. **It can loop.** `continue: true` settles again. The gate is latched per turn (`firedThisTurn`) and the latch is checked before firing. Without it a bug would run until the session was killed. `packages/pi/tests/hooks.test.ts` asserts specifically that a second settle with no new turn injects nothing.

Turn counting is **branch-aware**: it walks `ctx.sessionManager.getBranch()` rather than a transcript file, so undoing to an earlier point and taking another path gives the count for *that* path. Two kinds of entries are filtered: synthetic wrapper content (`<system-reminder>`, `<command-message>`, …) and the extension's own injected messages, which would otherwise let the gate feed its own counter.

**`session_before_compact`** — re-injects the snapshot when the compaction actually drops messages. Rules are delivered at session start, and without this a long session depends on the compaction summary remembering them, which is a hope rather than a guarantee: measured on an 8-day session, one injection at 02:38 was followed by three compactions and no further injection. The event carries `preparation.messagesToSummarize`, so "was anything lost" is a fact — an empty list means the compaction had nothing to drop and re-injecting would only cost tokens. Re-injection happens at most once per turn, since `session_start` may have just delivered the same text.

It does not customize or block compaction; it returns `undefined` so Pi runs its normal summarization. The hook hosts used to *block* compaction to force a memory flush — that hung the pipeline and was removed there too. Re-injecting after a loss is a different thing from standing in front of it.

## Configuration

All optional, under a `pi:` block in `config.yaml`. The defaults apply when the block is absent.

```yaml
pi:
  gate: message            # message | off
  detail_turn_interval: 30
  silent_summary: false
  inject_preferences: true
  brief_snapshot: true
  memory_tool_path: ~/.skills/using-memory/scripts/memory_tool.py
  memory_web_path: ~/.local/bin/memory-web
```

| Key | Default | Meaning |
|---|---|---|
| `gate` | `message` | `off` disables the write gate entirely. |
| `detail_turn_interval` | `30` | Human turns between gate fires. |
| `silent_summary` | `false` | Reserved; hook-driven silent summaries stay off. |
| `inject_preferences` | `true` | Inject the snapshot at session start. |
| `brief_snapshot` | `true` | Use `load --json --brief` (no docs index, truncated sources). |
| `memory_tool_path` | auto | Overrides CLI resolution. |
| `memory_web_path` | auto | Overrides `memory-web` resolution for `/umem web`. |

To turn the gate off: `pi: { gate: off }`.

## The `/umem` command

```
/umem                      status (lifetime dashboard)
/umem load [--log-days N]  read the snapshot
/umem search <query>       full-text search
/umem write-log --tag T --text ...
/umem web [--port N]       start the web UI, detached
/umem web stop             stop the UI this session started
/umem setup                prints the interactive setup command
/umem help
```

`/umem web` spawns `memory-web` **detached** and reads the URL back out of its banner. It must not be awaited: `memory-web` serves until signalled, and awaiting it in a command handler freezes the TUI (the same trap `/ukb web` hit). The URL is taken from the process that bound the port rather than rebuilt from `--port`, because uvicorn prints the address it actually got. The server is stopped by the session that started it.

`memory-web` lives in the `web/` virtualenv, not on `PATH`, so resolution checks `web/.venv/bin/memory-web` and the conventional install locations.

`/umem setup` is interactive (it prompts over stdin) and Pi's `exec` has no TTY, so the command tells you where to run it instead of hanging on the first prompt.

## Why the copy lives in Python

`memory_protocol_reminder()` and `stop_gate_instruction()` take a `host` parameter in `scripts/hooks/memory_hook_common.py`. Pi gets tool-call phrasing, the other hosts get the shell command. The extension does not re-implement those strings: it calls

```bash
python3 scripts/memory_tool.py hook-context --host pi --json
```

once per process and uses the returned `reminder` and `gate_instruction`. A wording change therefore lands in one language. The default `host="generic"` output is byte-identical to the pre-Pi version, which `tests/test_pi_shared_layer.py` pins.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/umem` missing | extension not on a scanned path | `scripts/link.sh pi`, restart Pi |
| `umem: memory_tool.py not found at …` at startup | CLI not installed where expected | run `scripts/install.sh`, or set `pi.memory_tool_path` |
| Hooks silent, tool works | CLI resolved but `hook-context` failed | check `python3 <path>/scripts/memory_tool.py hook-context --host pi --json` |
| Gate never fires | `pi.gate: off`, or fewer than `detail_turn_interval` turns, or the model wrote every turn | expected; lower the interval to test |
| Gate fires on every settle | the latch broke — a session-level bug | report it; the extension stops after one fire per turn by construction |
| `/umem web` says the command was not found | `memory-web` not installed | `cd web && python3 -m venv .venv && .venv/bin/pip install -e .` |
| `/umem web` refuses in a script | json/print mode has no session to own the server | run it from the TUI |

## Tests

```bash
cd packages/pi
npm test        # node --test, 56 cases, no Pi runtime needed
npm run typecheck
cd ../.. && python3 -m pytest tests/ -q
```

The Python suite covers the shared layer, the `hook-context` contract and a cross-language check that the TypeScript and Python resolvers agree on which `memory_tool.py` to use.
