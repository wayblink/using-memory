# Memory Repo Schema

`README.md`
- Overview for humans. Explain how the repo is Git-managed and portable.
- Mention that `<namespace>/local/ENV.md` and `<namespace>/local/MACHINE.md` stay scoped to one namespace.

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

`<namespace>/local/MACHINE.md` & `<namespace>/local/ENV.md`
- Namespace-specific identity and environment facts. These files are loaded only for the configured namespace.

`<namespace>/local/WORKSPACE.md`
- Namespace-specific workspace roots, repo paths, project entry points, and mount details. Keep dated work logs out of this file; use `<namespace>/log/YYYY-MM-DD.jsonl` for dated notes.

`<namespace>/log/YYYY-MM-DD.jsonl`
- Append-only operation logs in newline-delimited JSON. Each line is a self-contained JSON object with local-timezone ISO `ts` including an offset, `date`, `tag`, `level`, `source`, `text`, and optional `confidence`, `files`. Use `scripts/memory_tool.py write-log` to append. Keeping records structured makes `search`, `maintain`, `stats`, and `load` reliable without index builds.

Allowed lightweight tags:
- `operation`, `progress`, `milestone`, `state`, `result`, `output`, `verification`, `issue`, `debug`, `error`, `fix`, `decision`, `analysis`, `consideration`, `build`, `deploy`, `release`, `commit`, `test`, `benchmark`, `lesson`, `fact`, `pattern`, `insight`, `note`, `context`
- `[issue]` is for log entries or indexed todo/plan documents only; it is not accepted by `write-memory`.

CLI write boundary:
- `write-preference` appends stable preferences to `<namespace>/PREFERENCES.md`.
- `write-memory` appends only `fact`, `decision`, or `lesson` entries to `<namespace>/MEMORY.md`.
- `upsert-doc` writes `<namespace>/docs/*.md` and updates `<namespace>/docs/index.json` in the same operation.

**Local ENV note:**
When a machine loads the repo, it reads `<namespace>/local/ENV.md` only for the configured namespace. Other namespaces' local files stay isolated even though they live in the same Git repo.
