# Memory Repo Schema

`README.md`
- Overview for humans. Explain how the repo is Git-managed and portable.
- Mention that local `ENV.md`/`MACHINE.md` stay outside shared policies.

`SCHEMA.md`
- This file. Document the responsibilities of every sibling.

`MEMORY.md`
- Curated long-term memory. Append durable facts, decisions, and lessons in bullet form whenever something worth remembering emerges. Do not use this file as the document index, preference store, or issue tracker.

`PREFERENCES.md`
- Stable preferences and tone guidance. Keep entries minimal and actionable. Use `scripts/memory_tool.py write-preference` for preference writes.

`docs/index.json`
- Document index loaded before any document body. Each entry maps a Markdown file to metadata: `title`, `type`, `modified`, `projects`, `tags`, and `path`.
- `type` should stay coarse and stable, for example `wiki`, `SOP`, `todo`, or `plan`.

`docs/*.md`
- Indexed documents loaded only on demand after `docs/index.json` matches the current task. They explain reusable workflows, SOPs, plans, todo lists, wiki notes, or project context fragments. Use `scripts/memory_tool.py upsert-doc` so body and index stay synchronized.

`local/MACHINE.md` & `local/ENV.md`
- Machine-specific identity and environment facts. These files are **never** shared when another agent loads the repo; they stay local to the writable primary root.

`local/WORKSPACE.md`
- Machine-specific workspace roots, repo paths, project entry points, and mount details. Keep dated work logs out of this file; use `daily/YYYY-MM-DD.md` for dated notes.

`daily/YYYY-MM-DD.md`
- Daily append-only journals. Tag entries lightly with `[pref]`, `[decision|YYYY-MM-DD]`, `[lesson|YYYY-MM-DD]`, etc., and keep paragraphs short.

Allowed lightweight tags:
- `[pref]` — preference or style reminder
- `[decision|<date>]` — timestamped decision worth preserving
- `[lesson|<date>]` — distilled learning from a session
- `[fact]` — stable, factual statements
- `[issue]` — open questions or parking nodes for daily notes or indexed todo/plan documents only; not accepted by `write-memory`

CLI write boundary:
- `write-preference` appends stable preferences to `PREFERENCES.md`.
- `write-memory` appends only `fact`, `decision`, or `lesson` entries to `MEMORY.md`.
- `upsert-doc` writes `docs/*.md` and updates `docs/index.json` in the same operation.

**Local ENV note:**
When a machine loads the repo, it reads `local/ENV.md` only if the file exists in that writable primary root. Other machines' `local/ENV.md` files stay local and are not pulled into another host during sync.
