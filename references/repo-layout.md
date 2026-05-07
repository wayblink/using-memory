# Memory Repo Layout

This file defines only the memory repo data model: directory tree, file responsibilities, index metadata, tag format, and log JSONL schema. Startup read order, write decisions, and failure degradation are defined in `startup-and-write-rules.md`.

## Recommended Structure

```text
memory-repo/
  main/
    README.md
    SCHEMA.md
    MEMORY.md
    PREFERENCES.md
    docs/
      index.json
      workflow.md
      coding.md
    log/
      2026-04-13.jsonl
    local/
      MACHINE.md
      ENV.md
      WORKSPACE.md
```

This tree keeps every memory file under one namespace directory. The repo root is only the Git checkout that contains namespace directories.

## Notes

- A config `path` points to the Git repo root. `namespace` is a single first-level directory under that root and defaults to `main` when omitted.
- Reference repos are always read-only. The current session treats only the primary repo root as writable.
- Only the primary repo's configured `<namespace>/local/*` content is loaded for the current namespace. Other namespaces remain reference material and do not affect local state.
- The sample `main/log/2026-04-13.jsonl` shows the structure. Real log files follow `<namespace>/log/YYYY-MM-DD.jsonl` and use the actual date.
- Do not create a `YYYY/` subdirectory. Legacy year-layered log files should be migrated to `<namespace>/log/YYYY-MM-DD.jsonl`.

## File and Directory Responsibilities

- `<namespace>/README.md`: user-facing overview, repo migration notes, and sync guidance.
- `<namespace>/SCHEMA.md`: structure conventions, version, write boundaries, and tag rules for the skill and maintainers.
- `<namespace>/MEMORY.md`: stable facts, verified decisions, and key lessons only; it no longer acts as a topic document index.
- `<namespace>/PREFERENCES.md`: communication and working preferences that help agents adjust tone, pace, and format.
- `<namespace>/log/`: newline-delimited JSON (one entry per line), optimized for append-only context, search, and structured queries. Legacy `.md` log files may exist but are no longer written to.
- `<namespace>/docs/`: on-demand indexed documents such as `workflow.md`, `coding.md`, and other core knowledge.
- `<namespace>/docs/index.json`: document index with each document's `title`, `type`, `modified`, `projects`, `tags`, and `path`; loaders browse this index before selecting Markdown bodies. Stable `type` values include `wiki`, `SOP`, `todo`, and `plan`.
- `<namespace>/local/MACHINE.md`: namespace-local identity, role, hardware, or network traits; loaded only from the primary repo's configured namespace.
- `<namespace>/local/ENV.md`: namespace-local environment, toolchain versions, and default paths, kept scoped to avoid contaminating other namespaces.
- `<namespace>/local/WORKSPACE.md`: namespace-local workspaces, repo paths, project entry points, and mount points; loaded only from the primary repo's configured namespace.

## Log JSONL Schema

Each line in `<namespace>/log/YYYY-MM-DD.jsonl` is a self-contained JSON object:

```json
{"ts":"2026-05-06T10:30:00Z","date":"2026-05-06","tag":"lesson","level":"summary","source":"user","text":"insight sentence","confidence":8,"files":["deploy.py"]}
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

## Memory Tag Examples

- `[note]` marks a lightweight log note: `[note] Prefer concise, direct answers with execution before explanation`.
- `[decision|2026-04-13]` marks a key decision in MEMORY.md: `[decision|2026-04-13] Use one Git repo with namespace-scoped memory files`.
- `[lesson|2026-04-13]` marks a lesson in MEMORY.md: `[lesson|2026-04-13] Namespace-local ENV.md files should not leak into other namespaces`.
- `[fact]` marks a fact: `[fact] The memory repo is Git-managed Markdown for migration and review`.
- `[issue]` belongs only in JSONL log entries or `<namespace>/docs/` todo/plan documents; it does not go to `<namespace>/MEMORY.md` by default.
