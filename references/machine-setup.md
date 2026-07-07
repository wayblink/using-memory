# Host Setup and Smoke Test

This file owns Codex and Claude Code setup, install/link behavior, fresh-session smoke tests, and multi-machine rollout. Runtime retrieval/write rules live in `startup-and-write-rules.md`; repo structure lives in `repo-layout.md`.

Codex and Claude Code are both first-class hosts. `using-memory` is agent-agnostic: both hosts should point at the same memory repo and use the same namespace-scoped memory repo schema, config lookup, local-primary-write/reference-read model, and `scripts/memory_tool.py` behavior. Only the host skill exposure file and skill install destination differ.

## Develop in-place
Work from `personal-skills/using-memory/` so every edit touches the same skill tree each host can read once the repo is linked. If a host appears to keep older skill text in memory, start a brand-new session instead of assuming an existing conversation reloads changed Markdown.

## Linking and installing
- `scripts/link.sh` creates live symlinks so hosts read this workspace copy directly. Rerun it only when first linking or rebuilding destination symlinks.
- `scripts/install.sh` copies the skill tree for isolated installs.
- Both scripts accept an optional host argument: `codex`, `claude-code`, or `both`; the default is `both`.
- Codex destination: `${CODEX_HOME:-~/.codex}/skills/using-memory`; default path is `~/.codex/skills/using-memory`.
- Claude Code destination: `${CLAUDE_HOME:-~/.claude}/skills/using-memory`; default path is `~/.claude/skills/using-memory`.
- On first install or link through this repo's `scripts/install.sh` or `scripts/link.sh`, the helper scripts check for the memory config and start interactive storage setup when no config exists. The prompt collects the memory repo path, optional remote Git repo URL, namespace, and machine ID. Set `USING_MEMORY_SKIP_SETUP=1` to skip this in automation.
- Some external skill installers only copy the skill directory and do not execute `scripts/install.sh`; after those installs, run `python3 scripts/memory_tool.py setup` manually.
- If a remote Git repo URL is provided, setup clones it into the requested path or pulls an existing checkout before writing config. If no remote is provided, setup initializes a local Git repo and prints the later `git remote add origin ...` / `git push -u origin main` step.
- `scripts/link.sh` refuses to replace an existing real directory. Remove the directory manually or use a copied install when the destination is not already a symlink.
- `scripts/install.sh` refuses to overwrite an existing destination unless `USING_MEMORY_INSTALL_FORCE=1` is set. Copied installs exclude development-only files such as `.git`, `tests`, Python bytecode, and editor swap files.

### Refreshing an existing Codex install

Prefer a live symlink while developing the skill:

```bash
cd /path/to/personal-skills/using-memory
./scripts/link.sh codex
umem --help
python3 ~/.codex/skills/using-memory/scripts/memory_tool.py load --json >/tmp/umem-load.json
```

Use a copied reinstall when the host should not read the working tree directly:

```bash
cd /path/to/personal-skills/using-memory
USING_MEMORY_INSTALL_FORCE=1 ./scripts/install.sh codex
umem --help
```

After either path, start a brand-new Codex session. Existing chats may keep old skill text in context.

## Host skill exposure

### Codex
Edit `~/.codex/superpowers/GEMINI.md` so it contains these lines in order:

@../skills/using-memory/SKILL.md
@./skills/using-superpowers/SKILL.md
@./skills/using-superpowers/references/gemini-tools.md

This exposes the skill for decision-based use; it must not force memory loading before every task. Codex should load memory only when the current task needs persisted cross-session context, saved preferences, prior decisions, project memory, or explicit memory read/write/search/maintenance.

`using-memory` lives under `~/.codex/skills`, while `using-superpowers` stays inside `~/.codex/superpowers/skills`; from `GEMINI.md`, the former requires `..` to reach the parallel tree.

### Claude Code
Edit `~/.claude/CLAUDE.md` so it includes the skill:

@./skills/using-memory/SKILL.md

This gives Claude Code the same skill instruction surface from its own skill tree. Claude Code should use the same config and memory repo layout as Codex, not a Claude-only memory format or a separate write pipeline.

## Configuration
The default config path is `~/.skills/using-memory/config.yaml`. Run `python3 scripts/memory_tool.py setup` to create it manually, or let `scripts/link.sh` / `scripts/install.sh` prompt during first-time setup. Override it with `USING_MEMORY_CONFIG` when a machine needs a different location. Keep config outside the memory repo so each machine can declare the local checkout path, namespace, machine ID, optional reference repos, and load priorities.

Fresh setup writes the hook tuning fields below. Existing installs that do not contain these fields still get the same defaults from `memory_hook_common.py`; copy this block into `config.yaml` when you want explicit per-machine control:

```yaml
logging:
  silent_summary: false
  detail_turn_interval: 20
  hard_gate:
    memory_prompt: true
    important_interval: true

session_archive:
  enabled: false
  mode: pointer
  auto_load: false
  index_events: true
```

Optional command-forwarding backend:

```yaml
remote:
  endpoint: http://127.0.0.1:8765
  token: change-me
```

This top-level `remote` sends `umem load`, `search`, `write-log`, `write-memory`, `write-preference`, and `upsert-doc` to `memory-web` `/api/v1/*` before local file access. It is not the same as `umem setup --remote`, which is the Git remote URL for syncing the memory repo. Connection refused, timeout, and HTTP 5xx fall back to local execution with a warning; HTTP 4xx is a command error. `remote.token` is sent as `Authorization: Bearer <token>`, and `memory-web` exempts loopback clients for local development.

## Hook Enforcement

Skill text improves routing, but hooks add a deterministic pre-final gate. The bundled hook scripts live in `scripts/hooks/`:

- `codex_memory_hook.py`: Codex command hook adapter.
- `claude_memory_hook.py`: Claude Code command hook adapter.
- `memory_hook_common.py`: shared routing and Stop-gate logic.

The hook does not load memory on every turn. It injects a compact SessionStart reminder plus saved preference summary, injects a short reminder when memory triggers are present, tracks operation-like tool events, and blocks `Stop` only when the configured hard gate is reached and no memory write was observed. The continuation prompt tells the agent to write a comprehensive JSONL log entry before finalizing.

The hook intentionally gates log writing, not long-term memory curation. Use `<namespace>/log/YYYY-MM-DD.jsonl` broadly for operation facts and key events; keep `<namespace>/MEMORY.md` limited to stable facts, confirmed decisions, and durable lessons.

### Codex hook install

Codex hooks require the hooks feature flag in `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

Then add a user-level `~/.codex/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.codex/skills/using-memory/scripts/hooks/codex_memory_hook.py",
            "statusMessage": "Checking memory protocol"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.codex/skills/using-memory/scripts/hooks/codex_memory_hook.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.codex/skills/using-memory/scripts/hooks/codex_memory_hook.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.codex/skills/using-memory/scripts/hooks/codex_memory_hook.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

Codex also supports repo-local `.codex/hooks.json` and inline `[hooks]` tables in `.codex/config.toml` or `~/.codex/config.toml`. Prefer user-level hooks for machine-wide memory enforcement; use repo-local hooks only when the project `.codex/` layer is trusted.

### Claude Code hook install

Add a user-level hook block to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/using-memory/scripts/hooks/claude_session_start_hook.py"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/using-memory/scripts/hooks/claude_memory_hook.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/using-memory/scripts/hooks/claude_memory_hook.py"
          }
        ]
      }
    ],
    "PostToolBatch": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/using-memory/scripts/hooks/claude_memory_hook.py"
          }
        ]
      }
    ],
    "ConfigChange": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/using-memory/scripts/hooks/claude_memory_hook.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/using-memory/scripts/hooks/claude_memory_hook.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

Use the dedicated Claude SessionStart wrapper on purpose: it chains `using-superpowers` startup guidance with `using-memory` SessionStart context, including the compact `<namespace>/PREFERENCES.md` summary. If an older machine still points SessionStart at `~/.claude/hooks/session-start` or directly at `claude_memory_hook.py`, update it after pulling this repo.

Claude Code also supports project `.claude/settings.json`, local `.claude/settings.local.json`, plugins, and skill-scoped hooks. Prefer user-level hooks for a machine-wide memory rule; use project hooks when the project should carry its own enforcement. Run `/hooks` in Claude Code to inspect which hooks are active.

### Hook behavior and limits

- `SessionStart` and memory-relevant `UserPromptSubmit` add context reminding the agent to use the skill. SessionStart also injects a compact saved-preferences summary so host-level reply rules such as language preference are visible before the first answer.
- `PostToolUse` and Claude's `PostToolBatch` mark the turn as log-worthy when commands, edits, builds, tests, commits, pushes, deployments, hook/config changes, failures, or fixes appear.
- `Stop` is the enforcement point: when the main agent is about to finish, the hook returns `decision: "block"` if the configured memory-prompt gate or important-turn interval fires and no `memory_tool.py write-log`, `write-memory`, `write-preference`, or `upsert-doc` was observed. The default interval is 20 real human turns.
- `PreCompact` is intentionally disabled and should not be wired into new Codex or Claude Code installs. Older hook configs that still call it get `{}` from the shared handler.
- `stop_hook_active` is honored to prevent infinite loops after the agent continues from a Stop hook.
- Silent auto-summary writes are disabled by default. Set `logging.silent_summary: true` only when a machine deliberately wants best-effort summary logs on substantial pass-through turns.
- Optional `session_archive.enabled: true` writes pointer records to `<namespace>/sessions/index.jsonl`; it does not copy transcript content and `session_archive.auto_load` defaults to false.
- The hook normally does not automatically write operation summaries to the memory repo. It forces the agent to perform key writes so it can summarize accurately and include files, commit hashes, verification status, and unresolved risks.
- The hook is heuristic. It reduces missed writes, but the final quality still depends on the agent using `scripts/memory_tool.py` with accurate content.

## Fresh-session smoke test
1. Confirm the host startup file includes `using-memory`:
   - Codex: `~/.codex/superpowers/GEMINI.md`
   - `@../skills/using-memory/SKILL.md`
   - `@./skills/using-superpowers/SKILL.md`
   - `@./skills/using-superpowers/references/gemini-tools.md`
   - Claude Code: `~/.claude/CLAUDE.md`
   - `@./skills/using-memory/SKILL.md`
2. Confirm the config is reachable through `USING_MEMORY_CONFIG` or the default `~/.skills/using-memory/config.yaml`.
3. Confirm the declared Git roots are readable and the primary root is writable when you expect automatic writes.
4. Start a brand-new Codex or Claude Code session. Do not reuse an older chat that may have loaded stale skill text.
5. First probe: ask a prompt that should not need memory. A simple prompt is: `For a greeting like "hello", should using-memory load saved memory? Answer yes/no with one reason.` Expected answer: no, because greetings do not need persisted context.
6. Second probe: ask a prompt that explicitly needs saved memory. A simple prompt is: `Using saved preferences and prior project memory, what memory sources would you load? List only source categories.` Expected answer: `<namespace>/PREFERENCES.md`, `<namespace>/MEMORY.md`, relevant local context, and relevant indexed docs when the config is reachable.
7. SessionStart preference probe: on a fresh Claude or Codex session, ask `Before I say anything else, what saved reply-language preference is already active?` Expected answer: it should mention the stored language preference from `<namespace>/PREFERENCES.md` instead of claiming no preference is loaded.
8. Third probe: ask the agent to state its automatic write decision for the current turn. A simple prompt is: `If this turn only had a greeting and no operation history, what is your automatic write decision? Answer only skip/log_detail/log_summary/write_memory, with one reason.`
9. Optional durable-write probe: tell the agent one durable preference and ask what it would write. For example: `Remember: I prefer concise direct replies. Where would you write it?` Expected answer: `<namespace>/PREFERENCES.md` through `write-preference`.
10. Optional hook probe: in a test repo, ask the agent to make a tiny harmless file edit and finish. Expected behavior: before the final answer, the Stop hook should force a `write-log` entry unless the agent already wrote one.

## Pass conditions
- The first probe says memory retrieval should be skipped for the greeting.
- The second probe mentions the configured primary repo and any readable reference repos in `sources` when source details are available.
- The second probe mentions retrieval from `<namespace>/PREFERENCES.md` and `<namespace>/MEMORY.md`, plus log or `<namespace>/local/*` context when relevant.
- The SessionStart preference probe surfaces the saved reply-language preference without waiting for a memory-specific user prompt.
- The third probe returns one of `skip`, `log_detail`, `log_summary`, or `write_memory`.
- The agent does not claim that every conversation must load memory.
- The agent does not claim that every tool call must be mirrored mechanically.
- The agent does claim that concrete operation history and key events should normally be written to the JSONL log.
- If the config is missing, the agent should degrade gracefully instead of blocking the session.

## Common failures to check first
- `~/.codex/superpowers/GEMINI.md` still points to `@./skills/using-memory/SKILL.md` instead of `@../skills/using-memory/SKILL.md`.
- `~/.claude/CLAUDE.md` does not include `@./skills/using-memory/SKILL.md`.
- `~/.claude/settings.json` still points `SessionStart` at `~/.claude/hooks/session-start` or `claude_memory_hook.py` instead of `scripts/hooks/claude_session_start_hook.py`.
- Codex `~/.codex/config.toml` is missing `[features] codex_hooks = true`.
- An older hook config still wires `PreCompact`; remove it unless you are testing backward compatibility.
- The hook config points at a copied skill path but the skill was only linked under the other host.
- The skill was never linked or installed. Re-run `scripts/link.sh both` for live symlinks or `scripts/install.sh both` for copied installs.
- `USING_MEMORY_CONFIG` points to the wrong file, or `~/.skills/using-memory/config.yaml` does not exist.
- The declared memory repo path is wrong, not readable, or not a Git checkout you can `git pull`.
- You changed the skill text but did not start a brand-new host session.
- The primary repo is not writable even though the config declares `writable: true`.

## Multi-machine rollout
1. On the new machine, `git clone` the same memory repo or `git pull` it if the repo already exists locally.
2. On the new machine, `git clone` this `personal-skills` repo or pull the latest version that contains `using-memory`.
3. Install the skill with `scripts/link.sh both` during development or `scripts/install.sh both` for copied installs; pass `codex` or `claude-code` when only one host is present.
4. Create `~/.skills/using-memory/config.yaml` or set `USING_MEMORY_CONFIG` to a machine-local config file. `scripts/memory_tool.py setup` and `examples/new-machine/config.template.yaml` include the conservative hook defaults; on older machines, copy the `features`, `logging`, and `session_archive` blocks from the template when you want the values visible.
5. Point the primary root at the memory repo checkout, then set a stable `namespace` for this machine/user/environment. If omitted, namespace defaults to `main`.
6. Edit `~/.codex/superpowers/GEMINI.md` and/or `~/.claude/CLAUDE.md` with the startup lines above.
7. Wire the host hooks exactly as shown above. For Claude Code, make sure `SessionStart` uses `claude_session_start_hook.py`.
8. Start a brand-new host session and run the smoke test before trusting the setup.

## Ready-to-copy templates
- Start from `examples/new-machine/config.template.yaml` when creating `~/.skills/using-memory/config.yaml` on a fresh machine.
- Copy `examples/new-machine/GEMINI.template.md` into `~/.codex/superpowers/GEMINI.md` if you want the minimal startup include block without retyping it.
- Copy `examples/new-machine/CLAUDE.template.md` into `~/.claude/CLAUDE.md` if you want the minimal Claude Code startup include block without retyping it.
- After any `git pull` that changes hook behavior, rerun `scripts/link.sh` or `scripts/install.sh both` so installed host paths pick up new helper scripts before you restart Codex or Claude Code. For Codex-only refreshes, `scripts/link.sh codex` is enough when the destination is a development symlink. Also compare the local `config.yaml` with `examples/new-machine/config.template.yaml` for new opt-in fields.
- Only change machine-local values such as `path`, `namespace`, `machine_id`, and whether a reference root should exist on this machine.

## Per-machine values only
Only these values should normally differ per machine:

```yaml
version: 1

memory_roots:
  - path: /Users/your-name/.memories
    role: primary
    writable: true
    namespace: main
    machine_id: local-main
    priority: 100
```

- Change `path` to match the local filesystem checkout of the memory repo.
- Set `namespace` to a single path segment such as `main`, `shaipower`, `work-laptop`, or a user/environment name. It defaults to `main` when omitted.
- `path` must be the parent directory that contains namespace directories, not the namespace directory itself. If your memory files are under `~/.memories/main`, set `path: ~/.memories` and `namespace: main`.
- Keep exactly one local primary root with `writable: true`.
- Give each machine its own `machine_id`.
- Keep the local machine highest with `priority`.
- Reuse the same repo layout and Markdown schema everywhere else.
