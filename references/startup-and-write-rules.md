# Startup and Write Rules

This file defines the runtime algorithm only: config resolution, load order, docs on-demand matching, write routing, distillation, and failure degradation. Memory repo directory responsibilities and field meanings live in `repo-layout.md`.

## Config Lookup Order

1. `USING_MEMORY_CONFIG`
2. `~/.skills/using-memory/config.yaml`

## Startup Read Order

- Local primary repo first. It is the only writable repo, and paths with `role: primary` are handled at the top.
- Reference repos are read-only and are added in priority order to supplement durable memory facts.
- The canonical daily path is fixed at `daily/YYYY-MM-DD.md`; today and yesterday are read from that path in the local primary repo.
- Explicit `load --daily-from/--daily-to` or `load --daily-days` may expand the primary daily read window; without those flags, only today and yesterday are read.
- Explicit `load --daily-query` includes only selected-window daily files whose content matches the query in `local_context`.
- The read order is strict: first load every repo's `PREFERENCES.md` and `MEMORY.md`, then browse every repo's `docs/index.json`, load matching `docs/*.md` by indexed metadata, and finally read the local primary daily window plus `local/MACHINE.md`, `local/ENV.md`, and `local/WORKSPACE.md`.
- `local/*` from other machines is ignored by default so remote environment details do not pollute the current session.
- `local/` stores only machine-local facts, not dated files; dated process notes belong in `daily/YYYY-MM-DD.md`.
- Daily notes from other machines are ignored by default. The primary repo is the place for today's writable and readable context.

## Session Snapshot

- `preferences`
- `durable_memory`
- `local_context`
- `doc_hits`
- `sources`

## docs On-Demand Expansion

- Each repo is first scanned lightly through `docs/index.json`; metadata such as `title`, `type`, `modified`, `projects`, `tags`, and `summary` determines whether a document matches the current task.
- Only matching `docs/*.md` files are loaded, keeping startup reads small.
- Reference repos remain read-only. Their docs are loaded only when the document index matches and the repo loaded successfully.

## Write Rules

- Write only when information is worth preserving: when the user explicitly asks to remember something, or when reusable preferences, decisions, lessons, facts, or documents are created.
- Only the local primary repo receives appended daily entries, at `daily/YYYY-MM-DD.md`; other machines are never written.
- There is no automatic `write-local`. Changes to `local/MACHINE.md`, `local/ENV.md`, and `local/WORKSPACE.md` should be explicit maintenance actions.
- Stable preferences go to `PREFERENCES.md` through `scripts/memory_tool.py write-preference`.
- Stable facts, decisions, and lessons go to `MEMORY.md` through `scripts/memory_tool.py write-memory`, and only `fact`, `decision`, and `lesson` are allowed.
- Unresolved issues, parking points, todo risks, and temporary context are not written to `MEMORY.md` by default; keep short-term content in daily notes, and write structured todo or plan material to `docs/`.
- Topic, workflow, wiki, SOP, todo, plan, and project context go to `docs/*.md` through `scripts/memory_tool.py upsert-doc`, which keeps the body and `docs/index.json` in sync.
- Do not manually edit only `docs/*.md` while forgetting `docs/index.json`. The index is the loader's entry point for deciding whether to open document bodies.

## End-of-Turn Write Decision

- `skip`
- `append_daily`
- `append_daily_and_queue_distill`
- `write_long_term_now` when necessary

## Distillation Rules

- Distill long-term memory from daily notes only during lightweight maintenance moments. A normal conversation turn should not trigger distillation every time.
- Topic and workflow memory belongs in `docs/`, with `docs/index.json` maintained at the same time. Each Markdown file should stay focused on one topic, workflow, plan, or project.
- Distillation should preserve enough context for future retrieval without piling up raw conversation text.

## Failure Degradation

- primary temporarily unwritable -> read-only mode with automatic writes disabled
- reference repo unreadable -> skip it
- config missing -> no-memory mode with a setup warning; do not block the session

## Non-Goals

- no daemon: no standalone background process.
- no DB: no database or vector store; everything stays in Markdown and Git.
- no automatic multi-writer sync: no cross-repo automatic synchronization; writes only go to the primary repo.
- Do not record every tool call: no per-turn transcript logging, and no plan to preserve raw output from every API or tool call.
