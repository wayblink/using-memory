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
  3. Then load only the local primary repo's configured namespace entries at `<namespace>/log/YYYY-MM-DD.jsonl` and namespace-local notes at `<namespace>/local/MACHINE.md`, `<namespace>/local/ENV.md`, and `<namespace>/local/WORKSPACE.md`.
- Only the local primary repo is writable by default.
- Log entries from other namespaces are ignored by default.
- Config `namespace` is a single path segment used for all memory files; it defaults to `main` when omitted.
- Config `path` must point to the parent directory that contains namespace directories. Do not point `path` at the namespace directory itself. For example, use `path: ~/.memories` with `namespace: main`, not `path: ~/.memories/main` with `namespace: main`.
- Canonical log path: `<namespace>/log/YYYY-MM-DD.jsonl`; do not create a `YYYY/` layer for log files.
- Log loading defaults to today and yesterday, but explicit `load --log-from/--log-to` or `load --log-days` may expand the primary repo log window.
- `load --log-query` filters the selected primary log window against `text` and loads only matching entries into `log_entries`.
- `<namespace>/local/` stores namespace-local facts only; do not put dated log entries under `local/`.
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
- `local_context`
- `log_entries`
- `doc_hits`
- `sources`

## Log JSONL Format

Each `<namespace>/log/YYYY-MM-DD.jsonl` file is newline-delimited JSON with one object per line:

```json
{"ts":"2026-05-06T18:30:00+08:00","date":"2026-05-06","tag":"lesson","level":"summary","source":"user","text":"insight sentence","confidence":8,"files":["deploy.py"]}
```

| Field | Description |
|---|---|
| `ts` | Local timezone timestamp (auto-generated on write, ISO 8601 with offset) |
| `date` | Entry date, `YYYY-MM-DD` (matches filename) |
| `tag` | One of: `operation`, `progress`, `milestone`, `state`, `result`, `output`, `verification`, `issue`, `debug`, `error`, `fix`, `decision`, `analysis`, `consideration`, `build`, `deploy`, `release`, `commit`, `test`, `benchmark`, `lesson`, `fact`, `pattern`, `insight`, `note`, `context` |
| `level` | `detail` for full operation records, `summary` for key results and milestones |
| `source` | Origin: `user`, `auto`, `observed`, `user-stated`… |
| `text` | Entry body |
| `confidence` | Optional 1-10 score |
| `files` | Optional list of related file paths |

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

- `load`: read memory snapshot. Key selectors: `--config`, `--date`, `--json`, `--log-from` + `--log-to`, `--log-days`, `--log-query`, `--doc` / `--doc-type` / `--doc-tag` / `--project` / `--doc-query`. Returns `log_entries` as a parsed JSON list from the primary repo's configured namespace log.
- `search <query>`: full-text search across `<namespace>/docs/*.md`, `<namespace>/MEMORY.md`, and the configured namespace log. Docs and memory cover primary plus reference roots; log covers the primary root's configured namespace only. Flags: `--config`, `--log-days N`, `--no-docs`, `--no-memory`, `--no-log`, `--json`.
- `maintain`: scan the configured namespace log for stale `files` references and corrupt JSON lines, and add missing `<namespace>/docs/index.json` entries for manually added `<namespace>/docs/*.md` files in the writable primary repo. Generated doc entries use minimal metadata only: title from the first Markdown H1 when present, `type: wiki`, and empty `projects` / `tags`. Flags: `--config`, `--json`.
- `stats`: aggregate tag counts across the configured namespace log and `<namespace>/MEMORY.md`. Flags: `--config`, `--json`.
- `export`: format a Markdown summary; stdout by default or `--dest FILE` to append. Flags: `--config`, `--dest`, `--json`.

### Write

- `write-log`: append one primary JSONL entry. Required: `--config`, `--date`, `--tag`, `--text`. Optional: `--level detail|summary`, `--confidence 1-10`, `--source TEXT`, `--files path1 --files path2`. Allowed tags: `operation`, `progress`, `milestone`, `state`, `result`, `output`, `verification`, `issue`, `debug`, `error`, `fix`, `decision`, `analysis`, `consideration`, `build`, `deploy`, `release`, `commit`, `test`, `benchmark`, `lesson`, `fact`, `pattern`, `insight`, `note`, `context`.
- `write-memory`: append one curated `<namespace>/MEMORY.md` entry. Required: `--config`, `--date`, `--tag`, `--text`; `write-memory` accepts only `fact`, `decision`, and `lesson`.
- `write-preference`: append one stable `<namespace>/PREFERENCES.md` entry. Required: `--config`, `--text`.
- `upsert-doc`: write one `<namespace>/docs/*.md` document and update `<namespace>/docs/index.json`. Required: `--config`, `--doc`, `--title`, `--doc-type`, `--modified`, `--text`; optional metadata: `--project`, `--doc-tag`, `--summary`.

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
- Mature workflows, best practices, and troubleshooting guides go to `<namespace>/docs/*.md` through `scripts/memory_tool.py upsert-doc`.
- Stable facts, confirmed decisions, and durable lessons go to `<namespace>/MEMORY.md` through `scripts/memory_tool.py write-memory`.
- Open issues, parking points, and unresolved risks stay out of `<namespace>/MEMORY.md` unless they become confirmed decisions, durable lessons, or stable facts.
- Stable user preferences go to `<namespace>/PREFERENCES.md` through `scripts/memory_tool.py write-preference`.
- Namespace-local facts belong in `<namespace>/local/MACHINE.md`, `<namespace>/local/ENV.md`, or `<namespace>/local/WORKSPACE.md` only through explicit maintenance.

Never write:

- raw per-turn transcripts
- one JSONL entry for every tool call as a mechanical mirror
- full temporary command output when a concise result summary is enough
- unverified assumptions as durable memory
- open questions directly into `<namespace>/MEMORY.md`

## Maintenance Rules

- `maintain`: scan the configured namespace log for stale `files` references and corrupt JSON lines, then repair missing `<namespace>/docs/index.json` entries for manually added primary namespace `<namespace>/docs/*.md` files.
- `search` / `stats` / `export` are available at any time for quick overview without modifying anything.
- Distill useful patterns from log entries into curated long-term files during light maintenance moments.
- Keep wording agent-agnostic so this skill can be used by both Codex and Claude Code without edits.

## References

- `references/repo-layout.md`: read when discussing memory repo structure, file responsibilities, document metadata, or tag conventions.
- `references/startup-and-write-rules.md`: read when discussing retrieval triggers, load order, docs index matching, write routing, distillation, or failure behavior.
- `references/machine-setup.md`: read when installing on a new machine, exposing the skill to Codex or Claude Code, debugging config, or running smoke tests.
- `examples/`: sample config files, startup templates, and example memory repo content.
