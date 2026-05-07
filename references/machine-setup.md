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
- The helper scripts install the skill files only; they do not read or create the memory config.
- `scripts/link.sh` refuses to replace an existing real directory. Remove the directory manually or use a copied install when the destination is not already a symlink.
- `scripts/install.sh` refuses to overwrite an existing destination unless `USING_MEMORY_INSTALL_FORCE=1` is set. Copied installs exclude development-only files such as `.git`, `tests`, Python bytecode, and editor swap files.

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
The default config path is `~/.skills/using-memory/config.yaml`. Override it with `USING_MEMORY_CONFIG` when a machine needs a different location. Keep config outside the memory repo so each machine can declare the local checkout path, namespace, machine ID, optional reference repos, and load priorities.

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
7. Third probe: ask the agent to state its automatic write decision for the current turn. A simple prompt is: `If this turn has no new long-term information, what is your automatic write decision? Answer only skip/log_detail/log_summary/write_memory, with one reason.`
8. Optional durable-write probe: tell the agent one durable preference and ask what it would write. For example: `Remember: I prefer concise direct replies. Where would you write it?` Expected answer: `<namespace>/PREFERENCES.md` through `write-preference`.

## Pass conditions
- The first probe says memory retrieval should be skipped for the greeting.
- The second probe mentions the configured primary repo and any readable reference repos in `sources` when source details are available.
- The second probe mentions retrieval from `<namespace>/PREFERENCES.md` and `<namespace>/MEMORY.md`, plus log or `<namespace>/local/*` context when relevant.
- The third probe returns one of `skip`, `log_detail`, `log_summary`, or `write_memory`.
- The agent does not claim that every conversation must load memory.
- The agent does not claim that every turn or every tool call must be written.
- If the config is missing, the agent should degrade gracefully instead of blocking the session.

## Common failures to check first
- `~/.codex/superpowers/GEMINI.md` still points to `@./skills/using-memory/SKILL.md` instead of `@../skills/using-memory/SKILL.md`.
- `~/.claude/CLAUDE.md` does not include `@./skills/using-memory/SKILL.md`.
- The skill was never linked or installed. Re-run `scripts/link.sh both` for live symlinks or `scripts/install.sh both` for copied installs.
- `USING_MEMORY_CONFIG` points to the wrong file, or `~/.skills/using-memory/config.yaml` does not exist.
- The declared memory repo path is wrong, not readable, or not a Git checkout you can `git pull`.
- You changed the skill text but did not start a brand-new host session.
- The primary repo is not writable even though the config declares `writable: true`.

## Multi-machine rollout
1. On the new machine, `git clone` the same memory repo or `git pull` it if the repo already exists locally.
2. On the new machine, `git clone` this `personal-skills` repo or pull the latest version that contains `using-memory`.
3. Install the skill with `scripts/link.sh both` during development or `scripts/install.sh both` for copied installs; pass `codex` or `claude-code` when only one host is present.
4. Create `~/.skills/using-memory/config.yaml` or set `USING_MEMORY_CONFIG` to a machine-local config file.
5. Point the primary root at the memory repo checkout, then set a stable `namespace` for this machine/user/environment. If omitted, namespace defaults to `main`.
6. Edit `~/.codex/superpowers/GEMINI.md` and/or `~/.claude/CLAUDE.md` with the startup lines above.
7. Start a brand-new host session and run the smoke test before trusting the setup.

## Ready-to-copy templates
- Start from `examples/new-machine/config.template.yaml` when creating `~/.skills/using-memory/config.yaml` on a fresh machine.
- Copy `examples/new-machine/GEMINI.template.md` into `~/.codex/superpowers/GEMINI.md` if you want the minimal startup include block without retyping it.
- Copy `examples/new-machine/CLAUDE.template.md` into `~/.claude/CLAUDE.md` if you want the minimal Claude Code startup include block without retyping it.
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
- Keep exactly one local primary root with `writable: true`.
- Give each machine its own `machine_id`.
- Keep the local machine highest with `priority`.
- Reuse the same repo layout and Markdown schema everywhere else.
