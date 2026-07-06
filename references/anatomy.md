# Anatomy — full details

> **DEPRECATED.** Anatomy is frozen and no longer developed. Existing data and `anatomy-*` commands still work (they now print a deprecation notice to stderr) but are unsupported and off by default. This document is retained for reference only.

Anatomy is the project-snapshot dimension. It lives at `<namespace>/anatomy/{_index.json, <slug>.json, <slug>.md}` (JSON is the source of truth; the `.md` is auto-rendered). Each file entry stores `desc / desc_source (auto|user|empty) / tokens_est / kind / mtime`.

Use it to answer "what does this project contain?" without paying for a full re-read each session. SKILL.md keeps the core discipline; this file has the full lifecycle.

## Growth path: register, then optionally let it fill incrementally

Anatomy is built lazily. Hook-driven lazy fill is opt-in; the intended lifecycle is:

1. **Registration** — manually via `anatomy-register <root>`, or automatically only when both `features.anatomy.post_tool_upsert` and `features.anatomy.auto_register` are enabled and the first PostToolUse Write/Edit is inside an eligible project (`.git` ancestor + at least one project marker file like `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `CMakeLists.txt`, `setup.py`, `pom.xml`, `build.gradle[.kts]`, `Gemfile`, `composer.json`, `Makefile`, `Pipfile`, `requirements.txt`). Either path writes a single pointer into `_index.json`. No file scan happens here.
2. When `features.anatomy.post_tool_upsert` is enabled, the PostToolUse hook calls `anatomy-upsert-file` on every `Write` / `Edit` / `MultiEdit` / `NotebookEdit` / `Create`. The snapshot grows to reflect the files you actually touched. On the first such edit in an eligible-but-unregistered project, inline repo registration happens only when `features.anatomy.auto_register` is enabled.
3. `anatomy-set <slug> <relpath> --desc "..."` to pin a short description on load-bearing files (trust boundaries, build entrypoints, config schemas). These are preserved through future scans.
4. `anatomy-scan <slug>` only when you explicitly want a project-wide map — e.g., onboarding a new repo, prepping a refactor, or producing an audit. **Skip this for projects with large vendored / build / thirdparty trees** (`ep/`, `vendor/`, generated `dist/` siblings, etc.) — they bloat the snapshot to tens of MB and slow every subsequent `upsert-file`.

Treat `anatomy-scan` as an opt-in heavy operation, not part of registration. A registered-but-unscanned project still works: `load --anatomy` returns the registered root without files, the SessionStart hook still injects the standard reminder, and PostToolUse upserts start populating files on the first edit only when `features.anatomy.post_tool_upsert` is enabled (an empty snapshot shell is created inline when needed).

## Registration is automatic when safe, explicit otherwise

Auto-registration fires only when the file being touched lives inside a `.git` repo **and** some directory between the file and the `.git` ancestor contains a recognized project marker file. This gate keeps random directories (`~/Downloads`, scratch dirs, plain text notes under `~/notes`) out of the index — they have no marker and so never auto-register. Monorepos are handled by registering the `.git` directory (repo root) as a single slug, not the marker's parent; a marker found inside `services/api/` still registers the whole repo.

Slug derivation: the base slug is the repo root's basename. If that slug is already registered to a **different** root, the auto-registration path tries up to two levels of path-segment disambiguation (`parent-base`, then `grandparent-parent-base`). If all three candidates collide, auto-registration is skipped and the SessionStart hint surfaces the conflict so the user can pick a unique slug with explicit `--slug`. Idempotent: the same root re-encountered later returns the existing slug without rewriting the index.

`anatomy-register` remains available for projects without a marker, for projects you want to opt into ahead of any write, and for picking a custom slug.

## SessionStart optional attach

The Claude Code / Codex hook calls plain `load --json` on every SessionStart to inject the memory reminder and compact saved-preferences summary. It calls `load --anatomy --cwd <session cwd>` only when `features.anatomy.session_start_attach` is enabled. With that option enabled, when cwd is inside a registered project, the rendered anatomy markdown (capped at ~2000 tokens, falling back to a top-level directory summary above the cap) is appended to the SessionStart additionalContext. When cwd is in an unregistered git repo that has a project marker, the hook injects a multi-line actionable hint: detected repo root, suggested slug (auto-disambiguated against existing entries), and a paste-ready `anatomy-register` command. When cwd is in a git repo without any project marker, the hook injects a softer note explaining no marker was found and pointing at manual registration. When cwd is anywhere else, only the standard memory-protocol reminder and preference summary are sent.

## Incremental maintenance

When `features.anatomy.post_tool_upsert` is enabled, the PostToolUse hook detects `Write` / `Edit` / `MultiEdit` / `NotebookEdit` / `Create` tool invocations, extracts the touched file path(s), and calls `anatomy-upsert-file` for each. `desc_source=user` entries are preserved through every refresh — only tokens/mtime/kind get updated. Files matching the skip set (lockfiles, binaries, `dist/`, `node_modules/`, `>2 MB`, etc.) are removed from the snapshot if previously indexed.

For full reconciliation, run `memory_tool.py maintain` periodically: it surfaces `stale_files` (in snapshot, gone from disk), `new_files` (on disk but not snapshot), and `broken_log_refs` (`[[anatomy:slug/rel]]` citations whose target was removed). Note that `new_files` after a registration-only setup will list every indexable file under the root — that is expected; do not interpret it as drift, and do not run `anatomy-scan` just to silence it.
