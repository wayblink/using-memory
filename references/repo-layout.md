# Memory Repo Layout

This file defines only the memory repo data model: directory tree, file responsibilities, index metadata, and tag format. Startup read order, write decisions, and failure degradation are defined in `startup-and-write-rules.md`.

## Recommended Structure

```text
memory-repo/
  README.md
  SCHEMA.md
  MEMORY.md
  PREFERENCES.md
  daily/
    2026-04-13.md
  docs/
    index.json
    workflow.md
    coding.md
  local/
    MACHINE.md
    ENV.md
    WORKSPACE.md
```

This tree separates durable facts, preferences, indexed documents, daily notes, and local machine descriptions.

## Notes

- Reference repos are always read-only. The current session treats only the local primary repo as writable.
- Only the primary repo's `local/*` content is loaded on the current machine. Other machines' `local/` files remain reference material and do not affect local state.
- The sample `daily/2026-04-13.md` shows the structure. Real daily files follow `daily/YYYY-MM-DD.md` and use the actual date.
- Do not create a `YYYY/` subdirectory. Legacy year-layered daily files should be migrated to `daily/YYYY-MM-DD.md`.

## File and Directory Responsibilities

- `README.md`: user-facing overview, repo migration notes, and sync guidance.
- `SCHEMA.md`: structure conventions, version, write boundaries, and tag rules for the skill and maintainers.
- `MEMORY.md`: stable facts, verified decisions, and key lessons only; it no longer acts as a topic document index.
- `PREFERENCES.md`: communication and working preferences that help agents adjust tone, pace, and format.
- `daily/`: raw daily notes using direct `YYYY-MM-DD.md` filenames, optimized for append-only context and history.
- `docs/`: on-demand indexed documents such as `workflow.md`, `coding.md`, and other core knowledge.
- `docs/index.json`: document index with each document's `title`, `type`, `modified`, `projects`, `tags`, and `path`; loaders browse this index before selecting Markdown bodies. Stable `type` values include `wiki`, `SOP`, `todo`, and `plan`.
- `local/MACHINE.md`: current-machine identity, role, hardware, or network traits; loaded only from the primary repo.
- `local/ENV.md`: current-machine environment, toolchain versions, and default paths, kept local to avoid contaminating other machines.
- `local/WORKSPACE.md`: current-machine workspaces, repo paths, project entry points, and mount points; loaded only from the primary repo.

## Memory Tag Examples

- The sample date `2026-04-13` demonstrates tag format; real writes should use the actual record date.
- `[pref]` marks a preference: `[pref] Prefer concise, direct answers with execution before explanation`.
- `[decision|2026-04-13]` marks a key decision: `[decision|2026-04-13] Use a single local primary repo as the writable source`.
- `[lesson|2026-04-13]` marks a lesson: `[lesson|2026-04-13] Remote machine repos stay read-only, and their local/ENV.md files are not loaded`.
- `[fact]` marks a fact: `[fact] The memory repo is Git-managed Markdown for migration and review`.
- `[issue]` belongs only in daily notes or `docs/` todo/plan documents; it does not go to `MEMORY.md` by default.
