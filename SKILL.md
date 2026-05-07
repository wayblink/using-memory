---
name: using-memory
description: Use when a task mentions memory, remember, forget, preference, prior context, previous work, continue, resume, project history, saved decisions, or Chinese triggers like 记忆, 记住, 偏好, 上次, 之前, 继续, 恢复; also use when persisted cross-session context could change the answer.
---

# using-memory

## Retrieval Contract

- Do not load memory by default for every conversation or every turn.
- At the start of each user task, make a lightweight routing decision: could persisted memory change the answer or should this task write durable context later?
- Use this skill only when memory could change the answer or the user explicitly asks for memory work.
- Use memory when one of these is true:
  - The user explicitly asks to read, search, update, migrate, maintain, or remember memory.
  - The user uses memory trigger words such as memory, remember, forget, preference, prior context, previous work, continue, resume, 记忆, 记住, 偏好, 上次, 之前, 继续, or 恢复.
  - The user refers to prior context, saved preferences, previous work, or continuing a project.
  - The task depends on durable user preferences, long-term decisions, project memory, or cross-session facts.
  - The assistant would otherwise guess about past user choices, project direction, or saved context.
- Skip this skill for greetings, one-off questions, simple shell commands, isolated coding tasks with enough local context, generic explanations, or tasks where reading memory would not change the answer.
- When memory loading is needed, load order is strict and must happen in this exact sequence:
  1. Load all configured `<namespace>/PREFERENCES.md` and `<namespace>/MEMORY.md` files across configured repos.
  2. Browse each configured repo's `<namespace>/docs/index.json`; when the user task matches indexed metadata, load only the matching `<namespace>/docs/*.md` files.
  3. Then load only the local primary repo's configured namespace entries at `<namespace>/log/YYYY-MM-DD.jsonl` and namespace-local notes at `<namespace>/local/MACHINE.md`, `<namespace>/local/ENV.md`, and `<namespace>/local/WORKSPACE.md`.
- Only the local primary repo is writable by default.
- Log entries from other namespaces are ignored by default.
- Config `namespace` is a single repo-root path segment used for all memory files; it defaults to `main` when omitted.
- Canonical log path: `<namespace>/log/YYYY-MM-DD.jsonl`; do not create a `YYYY/` layer for log files.
- Log loading defaults to today and yesterday, but explicit `load --log-from/--log-to` or `load --log-days` may expand the primary repo log window.
- `load --log-query` filters the selected primary log window against `text` and loads only matching entries into `log_entries`.
- `<namespace>/local/` stores namespace-local facts only; do not put dated log entries under `local/`.
- On-demand document loading is allowed only when the user task clearly matches entries in `<namespace>/docs/index.json`.

## Skill Position
- `using-memory` is an on-demand context retrieval and memory maintenance skill.
- Host skill exposure may make the skill available early, but exposure is not permission to load memory automatically.
- Invocation is decision-based: first decide whether persisted memory is relevant, then call the CLI only when needed.
- Treat this skill as a memory router: cheap to consider, selective to execute.

## Config Resolution
- Read `USING_MEMORY_CONFIG` first.
- If it is unset, try `~/.skills/using-memory/config.yaml`.
- If config is missing, enter no-memory mode: do not block the session, add a warning that setup is needed, and disable automatic writes by default.

## Session Snapshot
- `preferences`
- `durable_memory`
- `local_context`
- `log_entries`
- `doc_hits`
- `sources`

## Log JSONL Format

Each `<namespace>/log/YYYY-MM-DD.jsonl` file is newline-delimited JSON with one object per line:

```json
{"ts":"2026-05-06T10:30:00Z","date":"2026-05-06","tag":"lesson","level":"summary","source":"user","text":"insight sentence","confidence":8,"files":["deploy.py"]}
```

| Field | Description |
|---|---|
| `ts` | UTC timestamp (auto-generated on write, ISO 8601) |
| `date` | Entry date, `YYYY-MM-DD` (matches filename) |
| `tag` | One of: `operation`, `progress`, `milestone`, `result`, `issue`, `debug`, `decision`, `build`, `test`, `lesson`, `fact`, `note` |
| `level` | `detail` for full operation records, `summary` for key results and milestones |
| `source` | Origin: `user`, `auto`, `observed`, `user-stated`… |
| `text` | Entry body |
| `confidence` | Optional 1-10 score |
| `files` | Optional list of related file paths |

## Memory Tool Commands

Use `scripts/memory_tool.py` when the host can run local scripts. Prefer executing it directly or with `python3`; do not assume a `python` shim exists.

### Read

- `load`: read memory snapshot. Key selectors: `--config`, `--date`, `--json`, `--log-from` + `--log-to`, `--log-days`, `--log-query`, `--doc` / `--doc-type` / `--doc-tag` / `--project` / `--doc-query`. Returns `log_entries` as a parsed JSON list from the primary repo's configured namespace log.
- `search <query>`: full-text search across `<namespace>/docs/*.md`, `<namespace>/MEMORY.md`, and the configured namespace log. Docs and memory cover primary plus reference roots; log covers the primary root's configured namespace only. Flags: `--config`, `--log-days N`, `--no-docs`, `--no-memory`, `--no-log`, `--json`.
- `maintain`: scan the configured namespace log for stale `files` references and corrupt JSON lines, and add missing `<namespace>/docs/index.json` entries for manually added `<namespace>/docs/*.md` files in the writable primary repo. Generated doc entries use minimal metadata only: title from the first Markdown H1 when present, `type: wiki`, and empty `projects` / `tags`. Flags: `--config`, `--json`.
- `stats`: aggregate tag counts across the configured namespace log and `<namespace>/MEMORY.md`. Flags: `--config`, `--json`.
- `export`: format a Markdown summary; stdout by default or `--dest FILE` to append. Flags: `--config`, `--dest`, `--json`.

### Write

- `write-log`: append one primary JSONL entry. Required: `--config`, `--date`, `--tag`, `--text`. Optional: `--level detail|summary`, `--confidence 1-10`, `--source TEXT`, `--files path1 --files path2`. Allowed tags: `operation`, `progress`, `milestone`, `result`, `issue`, `debug`, `decision`, `build`, `test`, `lesson`, `fact`, `note`.
- `write-memory`: append one curated `<namespace>/MEMORY.md` entry. Required: `--config`, `--date`, `--tag`, `--text`; `write-memory` accepts only `fact`, `decision`, and `lesson`.
- `write-preference`: append one stable `<namespace>/PREFERENCES.md` entry. Required: `--config`, `--text`.
- `upsert-doc`: write one `<namespace>/docs/*.md` document and update `<namespace>/docs/index.json`. Required: `--config`, `--doc`, `--title`, `--doc-type`, `--modified`, `--text`; optional metadata: `--project`, `--doc-tag`, `--summary`.

## Write Strategy

At the end of each turn, make one write decision:

- `skip`: no information worth recording.
- `log_detail`: complete operation record with full details written to `<namespace>/log/*.jsonl` via `write-log`.
- `log_summary`: key results or milestones written to `<namespace>/log/*.jsonl` via `write-log` with `level=summary`.
- `write_doc`: mature knowledge or workflow written to `<namespace>/docs/*.md` via `upsert-doc`.
- `write_memory`: stable facts or confirmed decisions written to `<namespace>/MEMORY.md` via `write-memory`.

Write only when information is worth preserving. Prefer no write over noisy memory.

Routing:

- Complete operation records (commands, builds, deployments, debugging) go to `<namespace>/log/*.jsonl` with `level=detail`.
- Key results and milestones go to `<namespace>/log/*.jsonl` with `level=summary`.
- Mature workflows, best practices, and troubleshooting guides go to `<namespace>/docs/*.md` through `scripts/memory_tool.py upsert-doc`.
- Stable facts, confirmed decisions, and durable lessons go to `<namespace>/MEMORY.md` through `scripts/memory_tool.py write-memory`.
- Open issues, parking points, and unresolved risks stay out of `<namespace>/MEMORY.md` unless they become confirmed decisions, durable lessons, or stable facts.
- Stable user preferences go to `<namespace>/PREFERENCES.md` through `scripts/memory_tool.py write-preference`.
- Namespace-local facts belong in `<namespace>/local/MACHINE.md`, `<namespace>/local/ENV.md`, or `<namespace>/local/WORKSPACE.md` only through explicit maintenance.

Never write:

- every turn
- every tool call
- raw transcripts
- temporary command output
- unverified assumptions as durable memory
- open questions directly into `<namespace>/MEMORY.md`

## Maintenance Rules

- `maintain`: scan the configured namespace log for stale `files` references and corrupt JSON lines, then repair missing `<namespace>/docs/index.json` entries for manually added primary namespace `<namespace>/docs/*.md` files.
- `search` / `stats` / `export` are available at any time for quick overview without modifying anything.
- Distill useful patterns from log entries into curated long-term files during light maintenance moments.
- Keep wording agent-agnostic so this skill can be used by both Codex and Claude Code without edits.

## References

- `references/repo-layout.md`: read when discussing memory repo structure, file responsibilities, document metadata, or tag conventions.
- `references/startup-and-write-rules.md`: read when discussing retrieval triggers, load order, docs index matching, write routing, distillation, or failure behavior.
- `references/machine-setup.md`: read when installing on a new machine, exposing the skill to Codex or Claude Code, debugging config, or running smoke tests.
- `examples/`: sample config files, startup templates, and example memory repo content.
