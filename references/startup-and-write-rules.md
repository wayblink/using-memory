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
- A config `path` points to the parent directory that contains namespace directories. `namespace` selects the first-level namespace directory under that root and defaults to `main`.
- If the namespace lives at `~/.memories/main`, the config must be `path: ~/.memories` and `namespace: main`; pointing `path` at `~/.memories/main` would create `<path>/main/log` and is rejected.
- The canonical log path is fixed at `<namespace>/log/YYYY-MM-DD.jsonl`; today and yesterday are read from `<namespace>/log/*.jsonl` in the local primary repo.
- Explicit `load --log-from/--log-to` or `load --log-days` may expand the primary log read window; without those flags, only today and yesterday are read.
- Explicit `load --log-query` parses `<namespace>/log/*.jsonl` line by line and filters entries by the `text` field; only matching entries appear in `log_entries` and loaded log source content.
- When retrieval is needed, the read order is strict: first load every repo's `<namespace>/PREFERENCES.md` and `<namespace>/MEMORY.md`, then browse every repo's `<namespace>/docs/index.json`, load matching `<namespace>/docs/*.md` by indexed metadata, and finally read the local primary namespace log window. The per-machine `<namespace>/STATS.json` accounting file is never part of this snapshot.
- With `load --anatomy`, an additional anatomy block is attached for the registered project whose root is the longest prefix of cwd. SessionStart hooks pass this flag only when `features.anatomy.session_start_attach: true`.
- Log entries from other namespaces are ignored by default. The primary repo's configured namespace is the place for today's writable and readable context.

## Session Snapshot

- `preferences`
- `durable_memory`
- `log_entries` — parsed JSON objects from `<namespace>/log/*.jsonl`
- `doc_hits`
- `sources`
- `anatomy` — only present when `load --anatomy` is used

## docs On-Demand Expansion

- Each repo is first scanned lightly through `<namespace>/docs/index.json`; metadata such as `title`, `type`, `modified`, `projects`, `tags`, and `summary` determines whether a document matches the current task.
- Only matching `<namespace>/docs/*.md` files are loaded, keeping retrieval reads small.
- Reference repos remain read-only. Their docs are loaded only when the document index matches and the repo loaded successfully.

## Log JSONL Format

Each line in `<namespace>/log/YYYY-MM-DD.jsonl` is a JSON object:

```json
{"ts":"2026-05-06T18:30:00+08:00","date":"2026-05-06","tag":"lesson","level":"summary","source":"user","text":"insight","confidence":8,"files":["file.py"]}
```

| Field | Type | Req | Notes |
|---|---|---|---|
| `ts` | str | yes | Local timezone timestamp, ISO 8601 with offset |
| `date` | str | yes | `YYYY-MM-DD`, matches filename |
| `tag` | str | yes | `operation\|progress\|milestone\|state\|result\|output\|verification\|issue\|debug\|error\|fix\|decision\|analysis\|consideration\|build\|deploy\|release\|commit\|test\|benchmark\|lesson\|fact\|pattern\|insight\|note\|context` |
| `level` | str | yes | `detail` for full operation records, `summary` for key results and milestones |
| `source` | str | yes | `user` \| `auto` \| `observed` \| `user-stated` |
| `text` | str | yes | Entry body |
| `confidence` | int | no | 1–10 |
| `files` | list[str] | no | Related file paths |

## Write Rules

- For `<namespace>/log/YYYY-MM-DD.jsonl`, default toward recording concrete operation history and key events. Do not apply a heavy "is this important enough forever?" filter to logs; logs are for traceability and restart continuity.
- Record commands and tool-driven operations that changed state or produced meaningful evidence: file edits, config changes, service restarts, builds, tests, debug findings, fixes, commits, pushes, PR/release/deploy state, hook behavior, and unresolved follow-up.
- Simple reads, pure browsing, repeated identical calls, and raw temporary output do not need one entry per tool call unless they produced a decision, diagnosis, verification result, or state change.
- Hook-driven silent summary writes are disabled by default. Set `logging.silent_summary: true` only when a machine deliberately wants best-effort auto summaries for substantial pass-through turns.
- Only the local primary repo receives appended JSONL log entries, at `<namespace>/log/YYYY-MM-DD.jsonl`; other namespaces are never written.
- Project file snapshots go to `<namespace>/anatomy/` via the `anatomy-*` commands; the PostToolUse hook calls `anatomy-upsert-file` for write/edit-style tools only when `features.anatomy.post_tool_upsert: true`.
- Stable preferences go to `<namespace>/PREFERENCES.md` through `scripts/memory_tool.py write-preference`.
- Stable facts, decisions, and lessons go to `<namespace>/MEMORY.md` through `scripts/memory_tool.py write-memory`, and only `fact`, `decision`, and `lesson` are allowed.
- Unresolved issues, parking points, todo risks, and temporary context are not written to `<namespace>/MEMORY.md` by default; keep short-term content in JSONL log entries, and write structured todo or plan material to `<namespace>/docs/`.
- Topic, workflow, wiki, SOP, todo, plan, and project context go to `<namespace>/docs/*.md` through `scripts/memory_tool.py upsert-doc`, which keeps the body and `<namespace>/docs/index.json` in sync.
- Do not manually edit only `<namespace>/docs/*.md` while forgetting `<namespace>/docs/index.json`. The index is the loader's entry point for deciding whether to open document bodies.

## End-of-Turn Write Decision

- `skip`: pure chat, trivial reads with no new state, or repeated tool activity with no new information.
- `log_detail`: default for concrete operations, edits, commands, tests, debugging, deployments, commits, pushes, and hook/config changes.
- `log_summary`: key outcomes, milestones, release status, or verified results.
- `write_memory` when necessary

## Log Body Discipline

The `text` field is where reconstruction value lives. Operational tags (`operation`, `build`, `deploy`, `verification`, `test`, `debug`, `fix`, `decision`, `analysis`, `milestone`, `commit`, `release`, `issue`) MUST use a structured Markdown body with explicit sections: `## <one-line title>`, then `Context`, `Operations`, `Result` or `Verification`, and `Decisions` / `Open`. See `SKILL.md` section "Log Entry Body Schema" for the full schema and a worked example.

Operational principles:

- Reproducibility: an `Operations` bullet must be specific enough that the action can be repeated without re-investigation. Include absolute paths, exact commands, parameters, commit SHAs, image references with digest or short SHA, Helm release + revision, namespace, and sampled pod names.
- Failure visibility: failures, skips, and "not done because X" facts MUST appear in `Result` / `Verification`. A log entry that hides known failures is harmful — later sessions assume the system is healthier than it is.
- Continuity: when work is unfinished, the `Decisions / Open` section is the next-session starting point. Always end an in-progress turn with a concrete next step.
- `files` field: always a JSON array of strings, one path per element. Never a comma-joined string.

Length guidance: `level=detail` entries target 800–3000 characters; `level=summary` targets 300–800. Anything under 200 characters almost certainly dropped a required section.

Knowledge tags (`note`, `lesson`, `fact`, `insight`, `pattern`, `context`) may use a relaxed format — `## <heading>` plus paragraphs — but should still cite concrete identifiers (paths, SHAs, versions) when applicable.

## Distillation Rules

- Distill long-term memory from log entries only during lightweight maintenance moments. A normal conversation turn should not trigger distillation every time.
- Topic and workflow memory belongs in `<namespace>/docs/`, with `<namespace>/docs/index.json` maintained at the same time. Each Markdown file should stay focused on one topic, workflow, plan, or project.
- Distillation should preserve enough context for future retrieval without piling up raw conversation text.
- Optional `session_archive.enabled: true` writes only pointer records to `<namespace>/sessions/index.jsonl` so a human can find raw host transcripts later. It does not copy transcript content and is never part of automatic retrieval when `session_archive.auto_load: false` (the default).

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
- Do not mirror every tool call mechanically: no per-tool transcript logging, and no plan to preserve raw output from every API or tool call. Optional session archive stores only transcript pointers by default; operation facts and key events still belong in structured logs when they matter for restart continuity.
