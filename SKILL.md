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
  3. Then load only the local primary repo's recent daily notes at `daily/YYYY-MM-DD.jsonl` and local machine notes at `local/MACHINE.md`, `local/ENV.md`, and `local/WORKSPACE.md`.
- Only the local primary repo is writable by default.
- Daily notes from other machines are ignored by default.
- Canonical daily path: `daily/YYYY-MM-DD.jsonl`; do not create a `YYYY/` layer for daily notes.
- Daily loading defaults to today and yesterday, but explicit `load --daily-from/--daily-to` or `load --daily-days` may expand the primary repo daily window.
- `load --daily-query` filters the selected primary daily window against `text` and loads only matching entries into `daily_entries`.
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
- `daily_entries`
- `doc_hits`
- `sources`

## Daily JSONL Format

Each `daily/YYYY-MM-DD.jsonl` file is newline-delimited JSON with one object per line:

```json
{"ts":"2026-05-06T10:30:00Z","date":"2026-05-06","tag":"lesson","source":"user","text":"insight sentence","confidence":8,"files":["deploy.py"]}
```

| Field | Description |
|---|---|
| `ts` | UTC timestamp (auto-generated on write, ISO 8601) |
| `date` | Entry date, `YYYY-MM-DD` (matches filename) |
| `tag` | One of: `pref`, `decision`, `lesson`, `fact`, `issue`, `pattern`, `preference` |
| `source` | Origin: `user`, `auto`, `observed`, `user-stated`… |
| `text` | Entry body |
| `confidence` | Optional 1-10 score |
| `files` | Optional list of related file paths |

## Memory Tool Commands

Use `scripts/memory_tool.py` when the host can run local scripts.

### Read

- `load`: read memory snapshot. Key selectors: `--config`, `--date`, `--json`, `--daily-from` + `--daily-to`, `--daily-days`, `--daily-query`, `--doc` / `--doc-type` / `--doc-tag` / `--project` / `--doc-query`. Returns `daily_entries` as a parsed JSON list from the primary repo's `daily/*.jsonl`.
- `search <query>`: full-text search across `docs/*.md`, `MEMORY.md`, and `daily/*.jsonl`. Docs and memory cover primary plus reference roots; daily covers the primary root only. Flags: `--config`, `--daily-days N`, `--no-docs`, `--no-memory`, `--no-daily`, `--json`.
- `maintain`: scan `daily/*.jsonl` for stale `files` references and corrupt JSON lines, and add missing `docs/index.json` entries for manually added `docs/*.md` files in the writable primary repo. Generated doc entries use minimal metadata only: title from the first Markdown H1 when present, `type: wiki`, and empty `projects` / `tags`. Flags: `--config`, `--json`.
- `stats`: aggregate tag counts across primary-root `daily/*.jsonl` and `MEMORY.md`. Flags: `--config`, `--json`.
- `export`: format a Markdown summary; stdout by default or `--dest FILE` to append. Flags: `--config`, `--dest`, `--json`.

### Write

- `write-daily`: append one primary JSONL entry. Required: `--config`, `--date`, `--tag`, `--text`. Optional: `--confidence 1-10`, `--source TEXT`, `--files path1 --files path2`. Allowed tags: `pref`, `decision`, `lesson`, `fact`, `issue`, `pattern`, `preference`.
- `write-memory`: append one curated `MEMORY.md` entry. Required: `--config`, `--date`, `--tag`, `--text`; allowed tags are only `decision`, `lesson`, `fact`.
- `write-preference`: append one stable `PREFERENCES.md` entry. Required: `--config`, `--text`.
- `upsert-doc`: write one `docs/*.md` document and update `docs/index.json`. Required: `--config`, `--doc`, `--title`, `--doc-type`, `--modified`, `--text`; optional metadata: `--project`, `--doc-tag`, `--summary`.

## Hot Write Rules

At the end of each turn, make one lightweight write decision:

- `skip`: no durable or reusable information was created.
- `append_daily`: useful short-term context, parking points, or unresolved notes written to `daily/*.jsonl` via `write-daily`.
- `append_daily_and_queue_distill`: daily context should be saved now, and stable patterns should be distilled later during maintenance.
- `write_long_term_now`: allowed only for high-confidence stable preferences, facts, decisions, lessons, or reusable documents.

Write only when information is worth preserving. Prefer no write over noisy memory.

Routing:

- Stable user preferences, communication style, durable constraints, and stable workflow preferences go to `PREFERENCES.md` through `scripts/memory_tool.py write-preference`.
- Stable facts, confirmed decisions, and durable lessons go to `MEMORY.md` through `scripts/memory_tool.py write-memory`; `write-memory` accepts only `fact`, `decision`, and `lesson`.
- Reusable wiki, SOP, todo, plan, project context, and other structured notes go to `docs/*.md` through `scripts/memory_tool.py upsert-doc`, which must also update `docs/index.json`.
- Open issues, parking points, unresolved risks, and temporary execution context stay in `daily/*.jsonl` or an indexed `docs/` todo/plan, not in `MEMORY.md` by default.
- Machine-local facts belong in `local/MACHINE.md`, `local/ENV.md`, or `local/WORKSPACE.md` only through explicit maintenance; there is no automatic `write-local`.

Never write:

- every turn
- every tool call
- raw transcripts
- temporary command output
- unverified assumptions as durable memory
- open questions directly into `MEMORY.md`

## Maintenance Rules

- `maintain`: scan `daily/*.jsonl` for stale `files` references and corrupt JSON lines, then repair missing `docs/index.json` entries for manually added primary-root `docs/*.md` files.
- `search` / `stats` / `export` are available at any time for quick overview without modifying anything.
- Distill useful patterns from daily notes into curated long-term files during light maintenance moments.
- Keep wording agent-agnostic so this skill can be used by both Codex and Claude Code without edits.

## References

- `references/repo-layout.md`: read when discussing memory repo structure, file responsibilities, document metadata, or tag conventions.
- `references/startup-and-write-rules.md`: read when discussing startup load order, docs index matching, write routing, distillation, or failure behavior.
- `references/machine-setup.md`: read when installing on a new machine, wiring Codex or Claude Code startup, debugging config, or running smoke tests.
- `examples/`: sample config files, startup templates, and example memory repo content.
