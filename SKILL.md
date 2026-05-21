---
name: using-memory
description: Memory protocol for persisted cross-session context and operation continuity. Use when a task mentions memory, remember, forget, preference, prior context, previous work, continue, resume, project history, saved decisions, logs, operations, commits, pushes, builds, tests, deploys, hooks, or equivalent non-English memory/logging triggers; also use whenever persisted memory could change the answer or the turn may create operation history that should survive restart.
---

# using-memory

## Retrieval Contract

- Do not load memory by default for every conversation or every turn.
- At the start of each user task, make a lightweight routing decision: could persisted memory change the answer or should this task write durable context later?
- Use this skill only when memory could change the answer or the user explicitly asks for memory work.
- Use memory when one of these is true:
  - The user explicitly asks to read, search, update, migrate, maintain, or remember memory.
  - The user uses memory trigger words such as memory, remember, forget, preference, prior context, previous work, continue, resume, logs, operations, commits, pushes, builds, tests, deploys, hooks, or equivalent non-English memory/logging terms.
  - The user refers to prior context, saved preferences, previous work, or continuing a project.
  - The task depends on durable user preferences, long-term decisions, project memory, or cross-session facts.
  - The assistant would otherwise guess about past user choices, project direction, or saved context.
- Skip this skill for greetings, one-off questions, simple shell commands, isolated coding tasks with enough local context, generic explanations, or tasks where reading memory would not change the answer.
- When memory loading is needed, load order is strict and must happen in this exact sequence:
  1. Load all configured `<namespace>/PREFERENCES.md` and `<namespace>/MEMORY.md` files across configured repos.
  2. Browse each configured repo's `<namespace>/docs/index.json`; when the user task matches indexed metadata, load only the matching `<namespace>/docs/*.md` files.
  3. Then load only the local primary repo's configured namespace entries at `<namespace>/log/YYYY-MM-DD.jsonl`. The per-machine `<namespace>/STATS.json` accounting file is never auto-loaded.
- Only the local primary repo is writable by default.
- Log entries from other namespaces are ignored by default.
- Config `namespace` is a single path segment used for all memory files; it defaults to `main` when omitted.
- Config `path` must point to the parent directory that contains namespace directories. Do not point `path` at the namespace directory itself. For example, use `path: ~/.memories` with `namespace: main`, not `path: ~/.memories/main` with `namespace: main`.
- Canonical log path: `<namespace>/log/YYYY-MM-DD.jsonl`; do not create a `YYYY/` layer for log files.
- Log loading defaults to today and yesterday, but explicit `load --log-from/--log-to` or `load --log-days` may expand the primary repo log window.
- `load --log-query` filters the selected primary log window against `text` and loads only matching entries into `log_entries`.
- `<namespace>/STATS.json` is machine-local event accounting maintained by the hooks and write-* commands. It is never auto-loaded into the session snapshot and is intentionally not synced to reference roots (per-machine counts only).
- On-demand document loading is allowed only when the user task clearly matches entries in `<namespace>/docs/index.json`.

## Skill Position
- `using-memory` is an on-demand context retrieval and memory maintenance skill.
- Host skill exposure may make the skill available early, but exposure is not permission to load memory automatically.
- Invocation is decision-based: first decide whether persisted memory is relevant, then call the CLI only when needed.
- Treat this skill as a memory router plus an operation ledger: cheap to consider, selective to load, broad by default when writing logs.
- Log writing is not the same as durable memory curation. `<namespace>/log/*.jsonl` should preserve operation facts and key events with minimal filtering; `<namespace>/MEMORY.md` remains curated for stable facts, confirmed decisions, and lessons.

## Config Resolution
- Read `USING_MEMORY_CONFIG` first.
- If it is unset, try `~/.skills/using-memory/config.yaml`.
- If config is missing, enter no-memory mode: do not block the session, add a warning that setup is needed, and disable automatic writes by default.
- If the user is installing, reinstalling, debugging setup, or explicitly expects a setup prompt, tell them to run `python3 scripts/memory_tool.py setup`. That command prompts for memory path, optional remote Git repo URL, namespace, and machine ID. If a remote Git repo is provided it clones or pulls first; otherwise it initializes a local Git repo and prints the later remote-creation command.
- Do not assume package-manager style skill installation executes `scripts/install.sh`; many installers only copy the skill directory. In that case, run `python3 scripts/memory_tool.py setup` manually after install.

## Session Snapshot
- `preferences`
- `durable_memory`
- `log_entries`
- `doc_hits`
- `sources`
- `anatomy` (only when `load --anatomy` is set; see Anatomy below)

## Memory Dimensions

The skill stores four orthogonal kinds of context. Pick the right one when reading or writing:

| Axis | What | File | Lifecycle |
|---|---|---|---|
| **Time series (operation)** | What happened, in order | `<namespace>/log/YYYY-MM-DD.jsonl` | Append-only, broad |
| **Cross-project knowledge** | Stable facts / decisions / lessons | `<namespace>/MEMORY.md` | Curated, narrow |
| **Stable preferences** | User-level habits / rules | `<namespace>/PREFERENCES.md` | Curated, very narrow |
| **Project snapshot (anatomy)** | What a project *looks like right now* | `<namespace>/anatomy/<slug>.{json,md}` | Auto-refreshed on writes |

The log answers "what did I do"; anatomy answers "in what shape did I do it." The two are linked via `[[anatomy:<slug>/<rel>]]` references emitted automatically when `write-log --files` matches a registered project.

## Log JSONL Format

Each `<namespace>/log/YYYY-MM-DD.jsonl` file is newline-delimited JSON with one object per line:

```json
{"ts":"2026-05-06T18:30:00+08:00","date":"2026-05-06","tag":"lesson","level":"summary","source":"user","text":"insight sentence","confidence":8,"files":["deploy.py"],"project":"using-memory","topic":"hooks"}
```

| Field | Description |
|---|---|
| `ts` | Local timezone timestamp (auto-generated on write, ISO 8601 with offset) |
| `date` | Entry date, `YYYY-MM-DD` (matches filename) |
| `tag` | One of: `operation`, `progress`, `milestone`, `state`, `result`, `output`, `verification`, `issue`, `debug`, `error`, `fix`, `decision`, `analysis`, `consideration`, `build`, `deploy`, `release`, `commit`, `test`, `benchmark`, `lesson`, `fact`, `pattern`, `insight`, `note`, `context` |
| `level` | `detail` for full operation records, `summary` for key results and milestones |
| `source` | Origin: `user`, `auto`, `observed`, `user-stated`… (`auto` is reserved for hook-driven silent summary appends) |
| `text` | Entry body |
| `confidence` | Optional 1-10 score |
| `files` | Optional list of related file paths |
| `project` | Optional axis. Lowercase `[a-z0-9._-]`, 1..64 chars. Auto-routed from cwd or `--files` if omitted. Filterable via `search/load --project`. |
| `topic` | Optional axis. Same shape as project. Auto-routed from text keywords + tag if omitted. Filterable via `search/load --topic`. |

Within a `text` body, references like `[[anatomy:<slug>/<rel>]]` are emitted automatically when `--files` matches a registered project root, and search/load surface the matching anatomy snapshot under `anatomy_links` for each hit.

## Log Entry Body Schema

The `text` field of a log entry is the actual operation record. A one-sentence `text` is almost always under-specified and useless three days later. Treat the body as a small Markdown document with explicit sections; aim for a structured, reproducible style, not a flat sentence.

### Required structure

The `text` body MUST be structured Markdown with section headers, not a single prose sentence. For any tag of `operation`, `build`, `deploy`, `verification`, `test`, `debug`, `fix`, `decision`, `analysis`, `milestone`, `commit`, `release`, or `issue`, the body MUST contain at minimum these sections, in this order:

1. **Heading (`## <one-line title>`)** — what happened, in one sentence.
2. **`Context`** — why this was done, what triggered it, and pointers to related prior entries (date, commit SHA, ticket id, previous log entry).
3. **`Operations`** — the actual actions taken, one per bullet. Each bullet MUST be specific enough that the operation could be reproduced without re-asking. Include absolute paths, exact commands, parameters, commit SHAs, branch names, Helm release + revision, image full reference with digest or short SHA, sampled pod names, Kubernetes namespace, and host endpoints.
4. **`Result` / `Verification`** — observable outcome: exit codes, smoke results, row counts, sizes, digests, HTTP status, log lines hit. Failures and skips MUST be written explicitly here (e.g. `registry push: 401 unauthorized on hub.i.basemind.com/spark/spark`, `not pushed yet`, `smoke not run because image not pullable`) — never omit a failure to make the entry look clean.
5. **`Decisions` / `Open`** — decisions made during the turn, open questions, parking points, and the next-session starting point if work is unfinished.

For `note`, `lesson`, `fact`, `insight`, `pattern`, `context`: structure is recommended but may be relaxed to `## <heading>` plus body paragraphs. Even so, cite concrete identifiers (paths, SHAs, versions) when the entry references code or systems.

### Length and concreteness

- Target body length: **800–3000 characters** for `level=detail`, **300–800** for `level=summary`. Entries shorter than 200 characters almost always indicate a dropped Context, Operations, or Result section — go back and add it.
- Every file path mentioned in the body should be an **absolute path** (e.g. `/data/workspace/spark/build-spark-image-local.sh`), not a bare filename. The `files` field is for indexing only and does not replace inline paths.
- Quantify whenever possible: row counts, build step `N/M`, image size, commit SHA short hash, Helm revision number, pod restart count, log message verbatim.
- When something failed or was deferred, say so. A log entry that omits known failures is worse than no log entry, because future sessions trust it.

### `files` field discipline

- `files` MUST be a JSON array of strings; pass one `--files <path>` per file. Never join multiple paths into a single comma-separated string (`["a.py,b.py"]` is wrong; `["a.py","b.py"]` is correct).
- Prefer absolute paths in `files` when the entry references files outside the memory repo.
- `files` is for `maintain` stale-detection and grep indexing; it does not replace listing paths inline in the body.

### Good example

```text
## Spark Java 17 image build pushed to dev branch, registry push blocked

Context
- Triggered by user request 2026-05-13: produce a Java 17 Spark image consumable by Kyuubi prod and DolphinScheduler.
- Branch: spark-3.5.7-java17-image-c93fa99e, base commit c93fa99e8254. Continues the 2026-05-13 12:53 build log entry.

Operations
- Edited `/data/workspace/spark/pom.xml` and `/data/workspace/spark/assembly/pom.xml`: set `java.version=17`, removed legacy `--add-opens` entries.
- Ran `/data/workspace/spark/build-spark-image-local.sh` after `export SPARK_HOME=/data/workspace/spark/dist` to stop `docker-image-tool` from picking up `/opt/spark` from the host.
- Built images `hub.i.basemind.com/spark/spark:3.5.7-STEP-rc2-c93fa99e8254-java17` (b2015d776c99, 1.47GB) and `spark-py:<same tag>` (d211d518df6c, 1.54GB).
- Committed and pushed at 178c3a2b2d on origin/spark-3.5.7-java17-image-c93fa99e.

Verification
- Local smoke: Ubuntu 22.04 jammy, Java 17.0.18, Spark 3.5.7-STEP-rc2, PySpark import OK, SparkPi OK.
- Registry push: BLOCKED. `hub.i.basemind.com/spark/{spark,spark-py}` → 401 unauthorized; `registry.platform.shaipower.com/spark/*` → denied; `hub.i.basemind.com/wanganyang/*` project does not exist.
- Kyuubi prod baseline still alive: beeline `jdbc:hive2://10.130.33.104:10009/default`, `SELECT 1` → 1, app `spark-2c2f46fe193841378c26a7a6eb3772a5`.
- Prod validation of the new image: NOT RUN, image is not yet pushable.

Decisions / Open
- Need a writable registry path before prod can pull the new image. Ask user: which `hub.i.basemind.com` namespace has push rights for this account; or stand up a personal Harbor project.
- Until then, image lives only on the local host.
```

### Bad example — do not write entries that look like this

```text
Built local Java17 Spark image; smoke passed; not pushed yet.
```

This skips Context, hides which paths were touched, omits commit SHA, omits the failure mode (`not pushed yet` does not say why), and is unreproducible. A future session must re-investigate from scratch.

## Memory Tool Commands

Use `scripts/memory_tool.py` when the host can run local scripts. Prefer executing it directly or with `python3`; do not assume a `python` shim exists.

### Read

- `load`: read memory snapshot. Key selectors: `--config`, `--date`, `--json`, `--log-from` + `--log-to`, `--log-days`, `--log-query`, `--doc` / `--doc-type` / `--doc-tag` / `--project` / `--topic` / `--doc-query`, `--anatomy` / `--cwd PATH` / `--anatomy-max-tokens N`. Returns `log_entries` as a parsed JSON list from the primary repo's configured namespace log. With `--anatomy`, also returns an `anatomy` block matched against cwd.
- `search <query>`: full-text search across `<namespace>/docs/*.md`, `<namespace>/MEMORY.md`, and the configured namespace log. Docs and memory cover primary plus reference roots; log covers the primary root's configured namespace only. Flags: `--config`, `--log-days N`, `--no-docs`, `--no-memory`, `--no-log`, `--project` / `--topic` (repeatable; same axis is OR, different axes are AND; **scope reduces to log-only when either is set**), `--json`. Hits whose text contains `[[anatomy:slug/rel]]` references include an `anatomy_links` field with the resolved snapshot description.
- `maintain`: default mode scans the configured namespace log for stale `files` references and corrupt JSON lines, repairs missing `<namespace>/docs/index.json` entries, and audits anatomy projects (per-project `stale_files` / `new_files` drift, plus `broken_log_refs` for `[[anatomy:...]]` citations whose targets no longer exist). Generated doc entries use minimal metadata only: title from the first Markdown H1 when present, `type: wiki`, and empty `projects` / `tags`. Flags: `--config`, `--json`.
  - `maintain --distill`: read-only bucket analysis for the log-to-doc distillation pipeline. Groups unpromoted log entries by `(topic, tag-family)`, filters by `--min-entries` (default 3) and `--min-days` (default 3), scores, and returns candidate buckets ready for synthesis into a doc. Updates `last_distill_check_ts` only — never writes log or docs. See "Distillation Pipeline" below.
  - `maintain --promote TOPIC[/FAMILY]`: read-only synthesis of one bucket. Re-reads the full source-entry bodies, attaches the suggested `--doc / --doc-type / --project` and full `--link-log` ref list, and prints a structured prompt suitable for a subagent to read, decide, and (on yes) call `upsert-doc`. Never writes docs itself.
- `stats`: aggregate tag counts across the configured namespace log and `<namespace>/MEMORY.md`. Flags: `--config`, `--json`.
- `status`: lifetime dashboard. Reads `<namespace>/STATS.json` (real event counters incremented by hooks and write-* commands — never estimated) plus the anatomy index, prints session counts / anatomy attaches / log writes / hook blocks / hook passthroughs plus two diagnostic ratios (`anatomy_hit_rate`, `stop_block_ratio`). Flags: `--config`, `--json` (raw dict instead of dashboard).
- `export`: format a Markdown summary; stdout by default or `--dest FILE` to append. Flags: `--config`, `--dest`, `--json`.
- `anatomy-list`: list registered anatomy projects with file/token counts. Flags: `--config`, `--json`.
- `anatomy-show <slug|root>`: print the rendered anatomy markdown for a project. Errors if the project has not been scanned yet.

### Write

- `write-log`: append one primary JSONL entry. Required: `--config`, `--date`, `--tag`, `--text`. Optional: `--level detail|summary`, `--confidence 1-10`, `--source TEXT`, `--files path1 --files path2`, `--project SLUG`, `--topic SLUG`, `--cwd PATH` (override auto-routing context). When `--project` / `--topic` are omitted, they are auto-routed: project from cwd → registered anatomy slug, falling back to first matching `--files`; topic from text keywords (with `commit` / `deploy` / `release` / `build` / `test` tags short-circuiting to themselves). Allowed tags: `operation`, `progress`, `milestone`, `state`, `result`, `output`, `verification`, `issue`, `debug`, `error`, `fix`, `decision`, `analysis`, `consideration`, `build`, `deploy`, `release`, `commit`, `test`, `benchmark`, `lesson`, `fact`, `pattern`, `insight`, `note`, `context`.
- `write-memory`: append one curated `<namespace>/MEMORY.md` entry. Required: `--config`, `--date`, `--tag`, `--text`; `write-memory` accepts only `fact`, `decision`, and `lesson`.
- `write-preference`: append one stable `<namespace>/PREFERENCES.md` entry. Required: `--config`, `--text`.
- `upsert-doc`: write one `<namespace>/docs/*.md` document and update `<namespace>/docs/index.json`. Required: `--doc`, plus `--text` OR `--text-stdin`. Optional with auto-fallback: `--config` (env / default yaml), `--title` (first H1 in text → slug-derived), `--doc-type` (defaults to `wiki`; common: `wiki`, `lesson`, `troubleshooting`, `decision-record`, `runbook`, `SOP`, `project`), `--modified` (defaults to today). Optional metadata: `--project`, `--doc-tag`, `--summary`. Optional backlinks: `--link-log '[[log:YYYY-MM-DD#L<n>]]'` (repeatable; appends/merges a `## Related log entries` section, deduped). The distillation pipeline emits one `--link-log` per source entry so promoted log entries can be filtered out on the next distill pass.
- `anatomy-register <root> [--slug NAME]`: register a project root for anatomy snapshots. Cheap: writes a pointer into `_index.json` only and does **not** scan files. Slug must be unique; conflicts error out and require explicit `--slug`. Same root re-registered with the same slug is idempotent. The snapshot fills lazily via PostToolUse `anatomy-upsert-file` — only run `anatomy-scan` when you explicitly want a full project map.
- `anatomy-scan <slug|root>`: full re-scan of a registered project. Opt-in heavy operation: walks every indexable file under the root and writes `<slug>.json` / `<slug>.md`. Preserves `desc_source=user` entries (refreshes their tokens/mtime/kind, does not overwrite their desc). Avoid running it on projects with large vendored / thirdparty trees — those bloat the snapshot to tens of MB.
- `anatomy-set <slug|root> <relpath> --desc TEXT`: manually set or refine one file's description. Marks `desc_source=user` so future scans don't overwrite it.
- `anatomy-upsert-file <abs-path>`: refresh or remove the anatomy entry for one file. Used by the PostToolUse hook for incremental maintenance; safe to call manually too. Silently no-ops on files outside every registered project. Add `--auto-register` to also register the enclosing repo root when the file lives inside an eligible-but-unregistered project (`.git` + project marker); the hook always passes this flag.

## Anatomy

Anatomy is the project-snapshot dimension. It lives at `<namespace>/anatomy/{_index.json, <slug>.json, <slug>.md}` (JSON is the source of truth; the `.md` is auto-rendered). Each file entry stores `desc / desc_source (auto|user|empty) / tokens_est / kind / mtime`.

Use it to answer "what does this project contain?" without paying for a full re-read each session.

### Default growth path: register, then let it fill incrementally

Anatomy is built **lazily by default**. The intended lifecycle is:

1. **Registration** — either via `anatomy-register <root>` manually, or **automatically** on the first PostToolUse Write/Edit inside an eligible project (`.git` ancestor + at least one project marker file like `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `CMakeLists.txt`, `setup.py`, `pom.xml`, `build.gradle[.kts]`, `Gemfile`, `composer.json`, `Makefile`, `Pipfile`, `requirements.txt`). Either path writes a single pointer into `_index.json`. No file scan happens here.
2. The PostToolUse hook calls `anatomy-upsert-file --auto-register` on every `Write` / `Edit` / `MultiEdit` / `NotebookEdit` / `Create`. The snapshot grows to reflect the files you actually touched. On the first such edit in an eligible-but-unregistered project, the hook registers the repo root inline and proceeds with the upsert in the same call.
3. `anatomy-set <slug> <relpath> --desc "..."` to pin a short description on load-bearing files (trust boundaries, build entrypoints, config schemas). These are preserved through future scans.
4. `anatomy-scan <slug>` only when you explicitly want a project-wide map — e.g., onboarding a new repo, prepping a refactor, or producing an audit. **Skip this for projects with large vendored / build / thirdparty trees** (`ep/`, `vendor/`, generated `dist/` siblings, etc.) — they bloat the snapshot to tens of MB and slow every subsequent `upsert-file`.

Treat `anatomy-scan` as an opt-in heavy operation, not part of registration. A registered-but-unscanned project still works: `load --anatomy` returns the registered root without files, the SessionStart hook still injects the standard reminder, and PostToolUse upserts start populating files on the first edit (an empty snapshot shell is created inline when needed).

### Registration is automatic when safe, explicit otherwise

Auto-registration fires only when the file being touched lives inside a `.git` repo **and** some directory between the file and the `.git` ancestor contains a recognized project marker file. This gate keeps random directories (`~/Downloads`, scratch dirs, plain text notes under `~/notes`) out of the index — they have no marker and so never auto-register. Monorepos are handled by registering the `.git` directory (repo root) as a single slug, not the marker's parent; a marker found inside `services/api/` still registers the whole repo.

Slug derivation: the base slug is the repo root's basename. If that slug is already registered to a **different** root, the auto-registration path tries up to two levels of path-segment disambiguation (`parent-base`, then `grandparent-parent-base`). If all three candidates collide, auto-registration is skipped and the SessionStart hint surfaces the conflict so the user can pick a unique slug with explicit `--slug`. Idempotent: the same root re-encountered later returns the existing slug without rewriting the index.

`anatomy-register` remains available for projects without a marker, for projects you want to opt into ahead of any write, and for picking a custom slug.

### SessionStart auto-attach

The Claude Code / Codex hook calls `load --anatomy --cwd <session cwd>` on every SessionStart. When cwd is inside a registered project, the rendered anatomy markdown (capped at ~2000 tokens, falling back to a top-level directory summary above the cap) is appended to the SessionStart additionalContext. When cwd is in an unregistered git repo that has a project marker, the hook injects a multi-line actionable hint: detected repo root, suggested slug (auto-disambiguated against existing entries), and a paste-ready `anatomy-register` command. When cwd is in a git repo without any project marker, the hook injects a softer note explaining no marker was found and pointing at manual registration. When cwd is anywhere else, only the standard memory-protocol reminder is sent.

### Incremental maintenance

The PostToolUse hook detects `Write` / `Edit` / `MultiEdit` / `NotebookEdit` / `Create` tool invocations, extracts the touched file path(s), and calls `anatomy-upsert-file` for each. `desc_source=user` entries are preserved through every refresh — only tokens/mtime/kind get updated. Files matching the skip set (lockfiles, binaries, `dist/`, `node_modules/`, `>2 MB`, etc.) are removed from the snapshot if previously indexed.

For full reconciliation, run `memory_tool.py maintain` periodically: it surfaces `stale_files` (in snapshot, gone from disk), `new_files` (on disk but not snapshot), and `broken_log_refs` (`[[anatomy:slug/rel]]` citations whose target was removed). Note that `new_files` after a registration-only setup will list every indexable file under the root — that is expected; do not interpret it as drift, and do not run `anatomy-scan` just to silence it.

## Distillation Pipeline

A three-stage, two-gate pipeline turns repeated log buckets into curated docs. The pipeline is the only path that writes new docs from log activity, and every stage stays read-only until the very last call. The two gates ensure that no rule, hook, or subprocess can land a doc on its own — at least two LLM-in-the-loop decisions stand between a candidate bucket and a `docs/*.md` file.

### Stages

```
log/*.jsonl  --[1] distill-->  candidate buckets  --[2] promote-->  prompt  --[3] upsert-doc-->  docs/*.md
                                       ^                                ^                          ^
                                  hook injects                   subagent reads                 only writer
                                                                  & decides
```

1. **distill** (`maintain --distill`): read-only bucket analysis. Groups log entries by `(topic, tag-family)`, filters by `--min-entries` and `--min-days`, scores, and returns candidates. Updates `last_distill_check_ts` only.
2. **promote** (`maintain --promote TOPIC[/FAMILY]`): read-only synthesis prompt. Re-reads source entries in full, attaches suggested upsert-doc parameters, and emits structured markdown for a subagent. Never writes.
3. **upsert-doc** (`upsert-doc --doc <slug> --text-stdin --link-log <ref> ...`): the **only** stage that touches `docs/`. Writes the synthesized body, updates `index.json`, and merges `[[log:YYYY-MM-DD#L<n>]]` backlinks into a `## Related log entries` section.

### Two decision gates

- **Gate A — should this bucket be promoted?** The main-session model reads the candidate list (injected by the SessionStart / Stop hook) and decides whether to delegate. The cost of saying "not now" is one hook-injected reminder per ~100 turns; the cost of saying "yes" is spawning a subagent. The cheap default is to skip when the current task is unrelated.
- **Gate B — does the synthesized doc deserve to land?** The subagent reads the full prompt (5–30 KB of source text), decides whether the bucket actually coheres, and on yes calls `upsert-doc`. On no it returns a one-line summary explaining the mismatch and writes nothing. This catches buckets that look related by topic but turn out to be three different things sharing a label.

`docs/` cannot be written without passing both gates. The hook never calls `upsert-doc` directly; it can only inject candidates.

### Tag families

`distill` collapses the 26 log tags into 4 doc-shaped families. Tags not listed are skipped on purpose (noise-prone or already covered):

| Family | Tags | Suggested doc-type |
|---|---|---|
| `lesson` | `lesson`, `pattern`, `insight`, `fact` | `lesson` |
| `troubleshooting` | `fix`, `debug`, `error` | `troubleshooting` |
| `decision` | `decision`, `analysis`, `consideration` | `decision-record` |
| `runbook` | `operation`, `build`, `deploy`, `commit`, `release`, `verification` | `runbook` |

When an entry lacks a `topic` field (older logs pre-date auto-routing), distill applies the same regex inference `write-log` would have used at creation time, so historical data isn't permanently invisible.

### Backlinks: `[[log:YYYY-MM-DD#L<n>]]`

Every doc body emitted by promote / synthesized by a subagent should cite its source log entries with `[[log:YYYY-MM-DD#L<n>]]`. The `<n>` is the 1-based line number inside the JSONL file. `upsert-doc --link-log` accepts these refs (repeatable) and merges them into a `## Related log entries` section. The merge is dedup-safe; calling upsert-doc again on the same doc with overlapping refs leaves a clean union.

The distillation filter uses backlinks as the source of truth for "already promoted." A log entry with at least one `[[log:date#L<n>]]` reference in any doc is excluded from future buckets — so the same lesson cannot be promoted twice unless the user explicitly removes the backlink.

### Hook trigger

Both SessionStart and Stop / SubagentStop hooks call `fetch_distillation_candidates()`, which:

- Reads `cumulative_human_turns` (Stop hook accumulates real human-turn deltas across sessions, idempotent) and `last_distill_inject_ts` from STATS.json.
- Triggers when **either** `cumulative_human_turns - last_distill_inject_turn >= 100` **or** `now - last_distill_inject_ts >= 1 day`.
- Runs `maintain --distill --json` (read-only, milliseconds), and on candidates injects a compact summary into `additionalContext` (SessionStart) or appends it to the block reason (Stop).
- Updates `last_distill_inject_ts` and `last_distill_inject_turn` whether or not buckets were found, so an empty state doesn't make every hook re-run the subprocess.

The check is cheap (no docs, no log mutations) and runs every relevant hook; only the **inject** is throttled. This keeps SessionStart fast while ensuring long sessions still get a periodic nudge.

### Subagent delegation

A typical promote prompt is 5–30 KB. To keep the main session lean, **delegate via `Agent(subagent_type="general-purpose")`**:

```
Agent({
  description: "Promote hooks/lesson bucket to doc",
  subagent_type: "general-purpose",
  prompt: """Run `memory_tool.py maintain --promote hooks/lesson`. Read the source
            entries, decide whether the material coheres (return only a one-line
            summary if not). On yes, synthesize one doc body matching the
            doc-type shape and call `upsert-doc --doc <slug> --text-stdin
            --doc-type <type> --link-log <ref> ...`. Return only the final
            slug + a one-sentence summary."""
})
```

The subagent's isolated context window absorbs the source-entry payload; the main session sees only the final outcome.

### Tuning

Defaults are conservative: `--min-entries 3`, `--min-days 3`. Lower them to surface earlier candidates (`maintain --distill --min-entries 2 --min-days 1`); raise them to filter aggressively. The hook trigger uses `DISTILL_TURN_INTERVAL = 100` and `DISTILL_DAY_INTERVAL_SEC = 86400` in `memory_hook_common.py` — adjust those constants if a project's tempo demands more or less frequent injects.

## Health Dashboard (`status`)

`<namespace>/STATS.json` is an event-driven counter file maintained by the hooks and the write-* commands. It contains real counts — no estimates, no synthetic "savings" numbers — for:

- `sessions`, `anatomy_attached_count`, `anatomy_truncated_count`, `anatomy_hint_emitted`, `anatomy_attached_tokens_est` (rendered chars / 3.75), `anatomy_upserts`, `anatomy_auto_registered`
- `log_entries_user` (write-log invocations whose `--source` is not `auto`), `log_entries_auto` (silent hook-driven summary appends)
- `stop_blocks`, `stop_throttled_passthrough`, `precompact_blocks`
- `cumulative_human_turns` (Stop hook accumulates real human-turn deltas across sessions; powers distillation triggers)
- `last_distill_check_ts`, `last_distill_inject_ts`, `last_distill_inject_turn`, `last_promote_ts` (timestamps and turn checkpoints used by the distillation pipeline; see Distillation Pipeline above)

`memory_tool.py status` prints these along with two diagnostic ratios:

- `anatomy_hit_rate = anatomy_attached_count / sessions` — low values mean cwd rarely lands inside a registered project; consider running `anatomy-register` on more roots.
- `stop_block_ratio = stop_blocks / (stop_blocks + stop_throttled_passthrough)` — high values mean the model is being interrupted often (consider raising `STOP_DETAIL_TURN_INTERVAL` in the hook); near-zero values mean silent summaries are doing all the work.

Both ratios are diagnostic, not performance claims. The counters never assert "X% token savings" because the system has no real-API token visibility — it only knows what it injected and what it blocked.

## Hook Behaviour

The shared adapter at `scripts/hooks/memory_hook_common.py` is wired into Claude Code via `~/.claude/settings.json` (and into Codex via the equivalent codex adapter). Lifecycle bindings:

| Event | Action |
|---|---|
| **SessionStart** | Inject memory-protocol reminder + anatomy snapshot for cwd (or hint when cwd is in unregistered git repo) + distillation candidates when due (see Distillation Pipeline). |
| **UserPromptSubmit** | Set per-turn flag `prompt_mentions_memory` based on memory keyword regex; emit reminder when set. Does NOT reset session-lifetime counters. |
| **PostToolUse** / **PostToolBatch** | Update `important_events` / `memory_written` flags. For PostToolUse with a write/edit-style tool, additionally call `anatomy-upsert-file --auto-register` on each touched path (best-effort, 8s timeout, silent on failure). When the file is inside an eligible-but-unregistered project (`.git` + project marker), the subprocess auto-registers the repo root inline before upserting. |
| **Stop** / **SubagentStop** | Layered throttle. `stop_hook_active` short-circuits to `{}`. If the final assistant message itself contains a memory write, mark `memory_written=true` and pass through. Otherwise count real human user turns in the transcript JSONL (filtering out `tool_result` lists and synthetic `<system-reminder>` / `<command-message>` / `Stop hook feedback:` content), and accumulate the delta into `cumulative_human_turns` (idempotent). When `prompt_mentions_memory` OR `delta = current_turns - last_save_turn ≥ 8` AND `not memory_written`, BLOCK with the standard write-gate reason — and append distillation candidates to that reason when due. Otherwise pass through and (best-effort) append a `level=summary tag=progress source=auto` log entry capped at one per human turn and 200 per session. |
| **PreCompact** | Unconditional BLOCK with a structured reason: dump current task / unfinished subgoals / key identifiers / open risks before the context window shrinks. `stop_hook_active` / `precompact_hook_active` short-circuit to `{}` to prevent loops. |

The throttle threshold is `STOP_DETAIL_TURN_INTERVAL = 8` (per-turn level=summary appends are silent; once-per-eight detail blocks force a structured write).

## Write Strategy

At the end of each turn, make one write decision. Default toward writing a log entry when the turn performed work or changed state; do not apply heavy judgment filters to operation history.

- `skip`: no information worth recording.
- `log_detail`: complete operation record with full details written to `<namespace>/log/*.jsonl` via `write-log`.
- `log_summary`: key results or milestones written to `<namespace>/log/*.jsonl` via `write-log` with `level=summary`.
- `write_doc`: mature knowledge or workflow written to `<namespace>/docs/*.md` via `upsert-doc`.
- `write_memory`: stable facts or confirmed decisions written to `<namespace>/MEMORY.md` via `write-memory`.

For `<namespace>/log/*.jsonl`, prefer recording over skipping when there was a concrete operation, state change, verification, issue, fix, decision, commit, push, build, deployment, hook change, config change, or user-confirmed workflow event. The log is the continuity ledger and should be comprehensive enough to reconstruct what happened after restart.

Use `skip` mainly for pure greetings, purely conversational turns with no reusable context, trivial reads that produced no decision or state change, or repeated identical tool activity with no new information.

Routing:

- Complete operation records go to `<namespace>/log/*.jsonl` with `level=detail`: commands run, services restarted, files edited, config changed, branches/commits/pushes, builds, deployments, tests, debugging traces, verification, failures, fixes, and remaining risks.
- Key results and milestones go to `<namespace>/log/*.jsonl` with `level=summary`: successful completion, release/PR state, verified behavior, or important user-facing outcomes.
- Write enough fields in `text` to be useful later: what was done, why, command or host event when relevant, important parameters, affected paths, result status, commit hash/PR/deploy URL when available, and unresolved follow-up.
- Mature workflows, best practices, and troubleshooting guides go to `<namespace>/docs/*.md` through `scripts/memory_tool.py upsert-doc`. The minimal invocation is `upsert-doc --doc <slug> --text <body>` (or `--text-stdin`); title/type/modified auto-fallback so handwriting a doc is cheap.
- When consolidating multiple log entries into one doc (context-heavy synthesis, ~5–30 KB of source material), delegate to a subagent via the Agent tool (`subagent_type=general-purpose`). The subagent's isolated context window keeps the main session lean and returns only the final slug + a one-sentence summary.
- Stable facts, confirmed decisions, and durable lessons go to `<namespace>/MEMORY.md` through `scripts/memory_tool.py write-memory`.
- Open issues, parking points, and unresolved risks stay out of `<namespace>/MEMORY.md` unless they become confirmed decisions, durable lessons, or stable facts.
- Stable user preferences go to `<namespace>/PREFERENCES.md` through `scripts/memory_tool.py write-preference`.

Never write:

- raw per-turn transcripts
- one JSONL entry for every tool call as a mechanical mirror
- full temporary command output when a concise result summary is enough
- unverified assumptions as durable memory
- open questions directly into `<namespace>/MEMORY.md`

## Maintenance Rules

- `maintain`: scan the configured namespace log for stale `files` references and corrupt JSON lines, repair missing `<namespace>/docs/index.json` entries, and audit anatomy (`stale_files` / `new_files` per project + `broken_log_refs` for dead `[[anatomy:...]]` citations).
- `search` / `stats` / `export` are available at any time for quick overview without modifying anything.
- Distill useful patterns from log entries into curated long-term files during light maintenance moments. The automated path is `maintain --distill` -> `maintain --promote <topic>` -> subagent-driven `upsert-doc`; see "Distillation Pipeline" above for the two decision gates and trigger conditions.
- Keep wording agent-agnostic so this skill can be used by both Codex and Claude Code without edits.

## References

- `references/repo-layout.md`: read when discussing memory repo structure, file responsibilities, document metadata, or tag conventions.
- `references/startup-and-write-rules.md`: read when discussing retrieval triggers, load order, docs index matching, write routing, distillation, or failure behavior.
- `references/machine-setup.md`: read when installing on a new machine, exposing the skill to Codex or Claude Code, debugging config, or running smoke tests.
- `examples/`: sample config files, startup templates, and example memory repo content.
