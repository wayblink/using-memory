# Memory Repo Schema

`README.md`
- Overview for humans. Explain how the repo is Git-managed and portable.

`SCHEMA.md`
- This file. Document the responsibilities of every sibling.

`<namespace>/MEMORY.md`
- Curated long-term memory. Append durable facts, decisions, and lessons in bullet form whenever something worth remembering emerges. Do not use this file as the document index, preference store, or issue tracker.

`<namespace>/PREFERENCES.md`
- Stable preferences and tone guidance. Keep entries minimal and actionable. Use `scripts/memory_tool.py write-preference` for preference writes.

`<namespace>/docs/index.json`
- Document index loaded before any document body. Each entry maps a Markdown file to metadata: `title`, `type`, `modified`, `projects`, `tags`, and `path`.
- `type` should stay coarse and stable, for example `wiki`, `SOP`, `todo`, or `plan`.

`<namespace>/docs/*.md`
- Indexed documents loaded only on demand after `<namespace>/docs/index.json` matches the current task. They explain reusable workflows, SOPs, plans, todo lists, wiki notes, or project context fragments. Use `scripts/memory_tool.py upsert-doc` so body and index stay synchronized.

`<namespace>/log/YYYY-MM-DD.jsonl`
- Append-only operation logs in newline-delimited JSON. Each line is a self-contained JSON object with local-timezone ISO `ts` including an offset, `date`, `tag`, `level`, `source`, `text`, and optional `confidence`, `files`, `project`, `topic`. Use `scripts/memory_tool.py write-log` to append. Keeping records structured makes `search`, `maintain`, `stats`, and `load` reliable without index builds.

`<namespace>/sessions/index.jsonl`
- Optional cold session pointer index. Written only when `session_archive.enabled: true`; each line points at a host transcript path with minimal metadata such as `session_id`, `cwd`, `human_turns`, and `important_events`. It is not part of automatic retrieval and should not replace structured operation logs.

`<namespace>/STATS.json`
- Machine-local event counter file. Maintained by hooks (`bump_stats`) and write-* commands. Counters are real events — not estimates. Never auto-loaded into a session snapshot; read by `memory_tool.py status`. Intentionally not synced to reference roots because counts are per-machine.

Allowed lightweight tags:
- `operation`, `progress`, `milestone`, `state`, `result`, `output`, `verification`, `issue`, `debug`, `error`, `fix`, `decision`, `analysis`, `consideration`, `build`, `deploy`, `release`, `commit`, `test`, `benchmark`, `lesson`, `fact`, `pattern`, `insight`, `note`, `context`
- `[issue]` is for log entries or indexed todo/plan documents only; it is not accepted by `write-memory`.

Optional log axes (`project` / `topic`):
- Lowercase `[a-z0-9._-]`, 1..64 chars; only written when present (no null pollution). Auto-routed by `write-log` from cwd / `--files` / text keywords when omitted, and filterable via `search/load --project --topic`.

CLI write boundary:
- `write-preference` appends stable preferences to `<namespace>/PREFERENCES.md`.
- `write-memory` appends only `fact`, `decision`, or `lesson` entries to `<namespace>/MEMORY.md`.
- `upsert-doc` writes `<namespace>/docs/*.md` and updates `<namespace>/docs/index.json` in the same operation.
