# Retrieval and Write Rules

This file defines the runtime algorithm only: config resolution, retrieval triggers, load order, docs on-demand matching, write routing, distillation, and failure degradation. Memory repo directory responsibilities and field meanings live in `repo-layout.md`.

## Config Lookup Order

1. `USING_MEMORY_CONFIG`
2. `~/.skills/using-memory/config.yaml`

## Retrieval Triggers

Do not load memory by default for every conversation or every turn. Use memory retrieval only when memory could change the answer or the user explicitly asks for memory work.

Use memory when:

- The user explicitly asks to read, search, update, migrate, maintain, or remember memory.
- The user refers to prior context, saved preferences, previous work, or continuing a project.
- The task depends on durable user preferences, long-term decisions, project memory, or cross-session facts.
- The assistant would otherwise guess about past user choices, project direction, or saved context.

Skip memory for greetings, one-off questions, simple shell commands, isolated coding tasks with enough local context, generic explanations, or tasks where reading memory would not change the answer.

## Retrieval Read Order

- Local primary repo first. It is the only writable repo root, and paths with `role: primary` are handled at the top.
- Reference repos are read-only and are added in priority order to supplement durable memory facts.
- A config `path` points to the Git repo root. `namespace` selects the first-level namespace directory under that root and defaults to `main`.
- The canonical log path is fixed at `<namespace>/log/YYYY-MM-DD.jsonl`; today and yesterday are read from `<namespace>/log/*.jsonl` in the local primary repo.
- Explicit `load --log-from/--log-to` or `load --log-days` may expand the primary log read window; without those flags, only today and yesterday are read.
- Explicit `load --log-query` parses `<namespace>/log/*.jsonl` line by line and filters entries by the `text` field; only matching entries appear in `log_entries` and loaded log source content.
- When retrieval is needed, the read order is strict: first load every repo's `<namespace>/PREFERENCES.md` and `<namespace>/MEMORY.md`, then browse every repo's `<namespace>/docs/index.json`, load matching `<namespace>/docs/*.md` by indexed metadata, and finally read the local primary namespace log window plus `<namespace>/local/MACHINE.md`, `<namespace>/local/ENV.md`, and `<namespace>/local/WORKSPACE.md`.
- `<namespace>/local/*` from other namespaces is ignored by default so environment details do not pollute the current session.
- `<namespace>/local/` stores only namespace-local facts, not dated files; dated process notes belong in `<namespace>/log/YYYY-MM-DD.jsonl`.
- Log entries from other namespaces are ignored by default. The primary repo's configured namespace is the place for today's writable and readable context.

## Session Snapshot

- `preferences`
- `durable_memory`
- `local_context`
- `log_entries` — parsed JSON objects from `<namespace>/log/*.jsonl`
- `doc_hits`
- `sources`

## docs On-Demand Expansion

- Each repo is first scanned lightly through `<namespace>/docs/index.json`; metadata such as `title`, `type`, `modified`, `projects`, `tags`, and `summary` determines whether a document matches the current task.
- Only matching `<namespace>/docs/*.md` files are loaded, keeping retrieval reads small.
- Reference repos remain read-only. Their docs are loaded only when the document index matches and the repo loaded successfully.

## Log JSONL Format

Each line in `<namespace>/log/YYYY-MM-DD.jsonl` is a JSON object:

```json
{"ts":"2026-05-06T10:30:00Z","date":"2026-05-06","tag":"lesson","level":"summary","source":"user","text":"insight","confidence":8,"files":["file.py"]}
```

| Field | Type | Req | Notes |
|---|---|---|---|
| `ts` | str | yes | UTC timestamp, ISO 8601 |
| `date` | str | yes | `YYYY-MM-DD`, matches filename |
| `tag` | str | yes | `operation\|progress\|milestone\|result\|issue\|debug\|decision\|build\|test\|lesson\|fact\|note` |
| `level` | str | yes | `detail` for full operation records, `summary` for key results and milestones |
| `source` | str | yes | `user` \| `auto` \| `observed` \| `user-stated` |
| `text` | str | yes | Entry body |
| `confidence` | int | no | 1–10 |
| `files` | list[str] | no | Related file paths |

## Write Rules

- Write only when information is worth preserving: when the user explicitly asks to remember something, or when reusable preferences, decisions, lessons, facts, or documents are created.
- Only the local primary repo receives appended JSONL log entries, at `<namespace>/log/YYYY-MM-DD.jsonl`; other namespaces are never written.
- There is no automatic `write-local`. Changes to `<namespace>/local/MACHINE.md`, `<namespace>/local/ENV.md`, and `<namespace>/local/WORKSPACE.md` should be explicit maintenance actions.
- Stable preferences go to `<namespace>/PREFERENCES.md` through `scripts/memory_tool.py write-preference`.
- Stable facts, decisions, and lessons go to `<namespace>/MEMORY.md` through `scripts/memory_tool.py write-memory`, and only `fact`, `decision`, and `lesson` are allowed.
- Unresolved issues, parking points, todo risks, and temporary context are not written to `<namespace>/MEMORY.md` by default; keep short-term content in JSONL log entries, and write structured todo or plan material to `<namespace>/docs/`.
- Topic, workflow, wiki, SOP, todo, plan, and project context go to `<namespace>/docs/*.md` through `scripts/memory_tool.py upsert-doc`, which keeps the body and `<namespace>/docs/index.json` in sync.
- Do not manually edit only `<namespace>/docs/*.md` while forgetting `<namespace>/docs/index.json`. The index is the loader's entry point for deciding whether to open document bodies.

## End-of-Turn Write Decision

- `skip`
- `log_detail`
- `log_summary`
- `write_memory` when necessary

## Distillation Rules

- Distill long-term memory from log entries only during lightweight maintenance moments. A normal conversation turn should not trigger distillation every time.
- Topic and workflow memory belongs in `<namespace>/docs/`, with `<namespace>/docs/index.json` maintained at the same time. Each Markdown file should stay focused on one topic, workflow, plan, or project.
- Distillation should preserve enough context for future retrieval without piling up raw conversation text.

## Maintenance Commands

- `maintain` (`--config`): scan `<namespace>/log/*.jsonl` for **stale** `files` entries whose resolved path does not exist, and **corrupt** lines that fail JSON parse. Also repairs missing `<namespace>/docs/index.json` entries for manually added writable primary namespace `<namespace>/docs/*.md` files using minimal metadata (`type: wiki`, empty `projects` / `tags`). Returns `{"stale": [...], "corrupt": [...], "ok": N, "indexed_docs": [...]}`.
- `search <query>` (`--config`, `--log-days`, `--no-docs`, `--no-memory`, `--no-log`, `--json`): full-text search across `<namespace>/docs/*.md`, `<namespace>/MEMORY.md`, and `<namespace>/log/*.jsonl`. Docs and memory search cover primary plus reference roots; log search covers the primary root's configured namespace only. Returns `{"query": "...", "hits": [...], "total": N, "scope": {...}}`.
- `stats` (`--config`, `--json`): aggregate tag counts across the primary repo's configured `<namespace>/log/*.jsonl` and `<namespace>/MEMORY.md`. Returns `{"log": {"total": N, "by_tag": {...}}, "memory": {"total": N, "by_tag": {...}}, "scope": {...}}`.
- `export` (`--config`, `--dest`, `--json`): human-readable Markdown summary of stats; appends to `--dest` if given, otherwise prints to stdout.

## Failure Degradation

- primary temporarily unwritable -> read-only mode with automatic writes disabled
- reference repo unreadable -> skip it
- config missing -> no-memory mode with a setup warning; do not block the session

## Non-Goals

- no daemon: no standalone background process.
- no DB: no database or vector store; everything stays in Markdown, JSONL, and Git.
- no automatic multi-writer sync: concurrent writes from multiple namespaces still rely on normal Git sync discipline; writes only go to the configured primary repo and namespace.
- Do not record every tool call: no per-turn transcript logging, and no plan to preserve raw output from every API or tool call.
