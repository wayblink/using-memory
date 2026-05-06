---
name: using-memory
description: Use when starting any conversation, before responding to tasks, to load and maintain shared global memory from configured Git-managed Markdown repos
---

# using-memory

## Startup Contract

- Load memory before handling the task.
- Startup comes first: complete memory loading before any task analysis, planning, coding, or response drafting.
- Load order is strict and must happen in this exact sequence:
  1. Load all configured `PREFERENCES.md` and `MEMORY.md` files across configured repos.
  2. Browse each configured repo's `docs/index.json`; when the user task matches indexed metadata, load only the matching `docs/*.md` files.
  3. Then load only the local primary repo's recent daily notes at `daily/YYYY-MM-DD.md` and local machine notes at `local/MACHINE.md`, `local/ENV.md`, and `local/WORKSPACE.md`.
- Only the local primary repo is writable by default.
- Daily notes from other machines are ignored by default.
- Canonical daily path: `daily/YYYY-MM-DD.md`; do not create a `YYYY/` layer for daily notes.
- Daily loading defaults to today and yesterday, but explicit `load --daily-from/--daily-to` or `load --daily-days` may expand the primary repo daily window.
- `load --daily-query` filters the selected primary daily window and loads only matching notes into `local_context`.
- `local/` stores machine-local facts only; do not put dated daily notes under `local/`.
- On-demand document loading is allowed only when the user task clearly matches entries in `docs/index.json`.

## Root Skill Position
- `using-memory` and `using-superpowers` are parallel root skills.
- Automatic invocation depends on host startup wiring; the skill does not force itself to run first.
- The recommended early-session order is to let `using-memory` read memory before entering the normal skill flow. This is a best-effort startup protocol, not a platform guarantee.

## Config Resolution
- Read `USING_MEMORY_CONFIG` first.
- If it is unset, try `~/.skills/using-memory/config.yaml`.
- If config is missing, enter no-memory mode: do not block the session, add a warning that setup is needed, and disable automatic writes by default.

## Session Snapshot
- `preferences`
- `durable_memory`
- `local_context`
- `doc_hits`
- `sources`

## Memory Tool Commands

Use `scripts/memory_tool.py` when the host can run local scripts.

- `load`: read memory snapshot. Key selectors: `--config`, `--date`, `--json`, `--daily-from` + `--daily-to`, `--daily-days`, `--daily-query`, `--doc` / `--doc-type` / `--doc-tag` / `--project` / `--doc-query`.
- `write-daily`: append one primary daily entry. Required args: `--config`, `--date`, `--tag`, `--text`; allowed tags are `pref`, `decision`, `lesson`, `fact`, `issue`.
- `write-memory`: append one curated `MEMORY.md` entry. Required args: `--config`, `--date`, `--tag`, `--text`; allowed tags are only `decision`, `lesson`, `fact`.
- `write-preference`: append one stable `PREFERENCES.md` entry. Required args: `--config`, `--text`.
- `upsert-doc`: write one `docs/*.md` document and update `docs/index.json`. Required args: `--config`, `--doc`, `--title`, `--doc-type`, `--modified`, `--text`; optional metadata: `--project`, `--doc-tag`, `--summary`.

## Hot Write Rules

At the end of each turn, make one lightweight write decision:

- `skip`: no durable or reusable information was created.
- `append_daily`: useful short-term context, parking points, or unresolved notes should be kept in `daily/YYYY-MM-DD.md`.
- `append_daily_and_queue_distill`: daily context should be saved now, and stable patterns should be distilled later during maintenance.
- `write_long_term_now`: allowed only for high-confidence stable preferences, facts, decisions, lessons, or reusable documents.

Write only when information is worth preserving. Prefer no write over noisy memory.

Routing:

- Stable user preferences, communication style, durable constraints, and stable workflow preferences go to `PREFERENCES.md` through `scripts/memory_tool.py write-preference`.
- Stable facts, confirmed decisions, and durable lessons go to `MEMORY.md` through `scripts/memory_tool.py write-memory`; `write-memory` accepts only `fact`, `decision`, and `lesson`.
- Reusable wiki, SOP, todo, plan, project context, and other structured notes go to `docs/*.md` through `scripts/memory_tool.py upsert-doc`, which must also update `docs/index.json`.
- Open issues, parking points, unresolved risks, and temporary execution context stay in daily notes or an indexed `docs/` todo/plan, not in `MEMORY.md` by default.
- Machine-local facts belong in `local/MACHINE.md`, `local/ENV.md`, or `local/WORKSPACE.md` only through explicit maintenance; there is no automatic `write-local`.

Never write:

- every turn
- every tool call
- raw transcripts
- temporary command output
- unverified assumptions as durable memory
- open questions directly into `MEMORY.md`

## Maintenance Rules

- Distill useful patterns from daily notes into curated long-term files during light maintenance moments.
- Keep wording agent-agnostic so this skill can be used by both Codex and Claude Code without edits.

## References

- `references/repo-layout.md`: read when discussing memory repo structure, file responsibilities, document metadata, or tag conventions.
- `references/startup-and-write-rules.md`: read when discussing startup load order, docs index matching, write routing, distillation, or failure behavior.
- `references/machine-setup.md`: read when installing on a new machine, wiring Codex or Claude Code startup, debugging config, or running smoke tests.
- `examples/`: sample config files, startup templates, and example memory repo content.
