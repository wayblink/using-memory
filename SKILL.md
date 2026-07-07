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
- If the user is installing, reinstalling, debugging setup, or explicitly expects a setup prompt, tell them to run `umem setup`. That command prompts for memory path, optional remote Git repo URL, namespace, and machine ID. If a remote Git repo is provided it clones or pulls first; otherwise it initializes a local Git repo and prints the later remote-creation command.
- Top-level config `remote: {endpoint, token}` is the optional HTTP API backend for command forwarding. It is separate from `memory_roots[*].remote`, which is Git remote metadata written by setup.
- Do not assume package-manager style skill installation executes `scripts/install.sh`; many installers only copy the skill directory. In that case, run `umem setup` manually after install.

## Session Snapshot
- `preferences`
- `durable_memory`
- `log_entries`
- `doc_hits`
- `sources`

## Memory Dimensions

The skill stores three orthogonal kinds of context. Pick the right one when reading or writing:

| Axis | What | File | Lifecycle |
|---|---|---|---|
| **Time series (operation)** | What happened, in order | `<namespace>/log/YYYY-MM-DD.jsonl` | Append-only, broad |
| **Cross-project knowledge** | Stable facts / decisions / lessons | `<namespace>/MEMORY.md` | Curated, narrow |
| **Stable preferences** | User-level habits / rules | `<namespace>/PREFERENCES.md` | Curated, very narrow |

The log answers "what did I do". Project structure snapshots (anatomy) have been split out into a separate skill, `using-anatomy`; see that skill for the project-snapshot dimension.

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

### Examples

A full worked example (well-formed Spark image build with a blocked registry push) plus the flat one-liner it replaces are in `references/log-entry-examples.md`. Do not write flat one-liners like `Built local Java17 Spark image; smoke passed; not pushed yet.` — they skip Context, hide which paths were touched, omit the commit SHA and the real failure mode, and force a future session to re-investigate from scratch.

## Memory Tool Commands

Invoke as `umem <command>` (installed to `~/.local/bin` by `scripts/install.sh`; equivalent to `python3 <skill>/scripts/memory_tool.py <command>`). Every command takes `--config` (or falls back to `USING_MEMORY_CONFIG` / the default yaml) and supports `--json`. The list below is the entry point — **when unsure of a command's flags, run `umem <command> --help`**; full flag reference also in `references/cli-reference.md`.

When top-level `remote.endpoint` is configured, `load`, `search`, `write-log`, `write-memory`, `write-preference`, and `upsert-doc` first call `/api/v1` on that endpoint. Connection failures, timeouts, and HTTP 5xx responses fall back to local files with a warning; HTTP 4xx responses are command errors. `remote.token`, when present, is sent as a bearer token.

### Read

- `load` — read the memory snapshot. Selectors for date / log window and docs filters (`--doc`/`--doc-type`/`--project`/`--topic`/`--doc-query`). Returns `log_entries` as parsed JSON.
- `search <query>` — full-text search across `docs/*.md`, `MEMORY.md`, and the namespace log. `--project` / `--topic` narrow scope (to log-only when either is set).
- `maintain` — scan log for stale `files` refs + corrupt lines, repair `docs/index.json`. `--distill` and `--promote TOPIC[/FAMILY]` drive the distillation pipeline (both read-only).
- `stats` — aggregate tag counts across log + `MEMORY.md`.
- `status` — lifetime dashboard from `STATS.json`.
- `export` — Markdown summary to stdout or `--dest FILE`.

### Write

- `write-log` — append one JSONL log entry. Required: `--date --tag --text`. `--project` / `--topic` auto-route from cwd/files/text when omitted. Allowed tags listed in "Log JSONL Format".
- `write-memory` — append one curated `MEMORY.md` entry. Tags limited to `fact`, `decision`, `lesson`.
- `write-preference` — append one stable `PREFERENCES.md` entry. Required: `--text`.
- `upsert-doc` — write one `docs/*.md` + update `index.json`. Required: `--doc` plus `--text` / `--text-stdin`. `--link-log '[[log:YYYY-MM-DD#L<n>]]'` merges backlinks (repeatable).

## Distillation Pipeline

A three-stage, two-gate pipeline turns repeated log buckets into curated docs — the only path that writes new docs from log activity. Every stage stays read-only until the final `upsert-doc`, and two LLM-in-the-loop gates stand between a candidate bucket and a `docs/*.md` file.

```
log/*.jsonl --[1] distill--> candidate buckets --[2] promote--> prompt --[3] upsert-doc--> docs/*.md
```

1. **distill** (`maintain --distill`) — group log entries by `(topic, tag-family)`, filter by `--min-entries`/`--min-days`, return candidates. Read-only.
2. **promote** (`maintain --promote TOPIC[/FAMILY]`) — re-read source entries in full, emit a structured synthesis prompt for a subagent. Read-only.
3. **upsert-doc** — the only stage that writes `docs/`; merges `[[log:YYYY-MM-DD#L<n>]]` backlinks into a `## Related log entries` section.

Two gates: **Gate A** (the main-session model decides whether to delegate a hook-injected candidate) and **Gate B** (the subagent decides whether the synthesized doc actually coheres before calling `upsert-doc`, else writes nothing). The hook never calls `upsert-doc` directly. A log entry already cited by a `[[log:date#L<n>]]` backlink is excluded from future buckets, so nothing is promoted twice.

Trigger: SessionStart / Stop hooks run the cheap read-only `maintain --distill --json` and inject a candidate summary when `cumulative_human_turns` has advanced ≥100 since the last inject or ≥1 day has passed. Delegate promotion via `Agent(subagent_type="general-purpose")` so the 5–30 KB source payload stays out of the main session.

Full details — the tag-family table, backlink semantics, hook internals, subagent prompt template, and tuning constants — are in `references/distillation.md`.

## Health Dashboard (`status`)

`<namespace>/STATS.json` is an event-driven counter file maintained by the hooks and the write-* commands. It contains real counts — no estimates, no synthetic "savings" numbers — for:

- `sessions`
- `log_entries_user` (write-log invocations whose `--source` is not `auto`), `log_entries_auto` (silent hook-driven summary appends, only when `logging.silent_summary: true`)
- `stop_blocks`, `stop_throttled_passthrough`, `precompact_blocks`
- `cumulative_human_turns` (Stop hook accumulates real human-turn deltas across sessions; powers distillation triggers)
- `last_distill_check_ts`, `last_distill_inject_ts`, `last_distill_inject_turn`, `last_promote_ts` (timestamps and turn checkpoints used by the distillation pipeline; see Distillation Pipeline above)

`umem status` prints these along with a diagnostic ratio:

- `stop_block_ratio = stop_blocks / (stop_blocks + stop_throttled_passthrough)` — high values mean the model is being interrupted often (consider raising `logging.detail_turn_interval` or narrowing `logging.hard_gate`); near-zero values mean the hook is mostly passing through.

The ratio is diagnostic, not a performance claim. The counters never assert "X% token savings" because the system has no real-API token visibility — it only knows what it injected and what it blocked.

## Hook Behaviour

The shared adapter at `scripts/hooks/memory_hook_common.py` is wired into Claude Code via `~/.claude/settings.json` (and into Codex via the equivalent codex adapter). Lifecycle bindings:

| Event | Action |
|---|---|
| **SessionStart** | Inject memory-protocol reminder + compact saved-preferences summary + distillation candidates when due (see Distillation Pipeline). |
| **UserPromptSubmit** | Set per-turn flag `prompt_mentions_memory` based on memory keyword regex; emit reminder when set. Does NOT reset session-lifetime counters. |
| **PostToolUse** / **PostToolBatch** | Update `important_events` / `memory_written` flags. |
| **Stop** / **SubagentStop** | Layered throttle. `stop_hook_active` short-circuits to `{}`. If the final assistant message itself contains a memory write, mark `memory_written=true` and pass through. Otherwise count real human user turns in the transcript JSONL (filtering out `tool_result` lists and synthetic `<system-reminder>` / `<command-message>` / `Stop hook feedback:` content), and accumulate the delta into `cumulative_human_turns` (idempotent). When the configured memory-prompt hard gate fires OR `delta = current_turns - last_save_turn ≥ logging.detail_turn_interval` (default 20) AND `not memory_written`, BLOCK with the standard write-gate reason — and append distillation candidates to that reason when due. Otherwise pass through. Silent `level=summary tag=progress source=auto` appends happen only when `logging.silent_summary: true`; optional `session_archive.enabled: true` writes a cold pointer to `<namespace>/sessions/index.jsonl`. |
| **PreCompact** | Disabled. Previous versions BLOCKED compact to force a write-log/write-memory flush; this was observed to hang the compact pipeline and has been removed. The handler now returns `{}` unconditionally and the hook is unwired from `settings.json`. |

The default throttle threshold is `logging.detail_turn_interval = 20`. Hook-driven silent summaries are off by default; enable `logging.silent_summary` only when the extra auto log volume is intentional.

## Write Strategy

At the end of each turn, make one write decision. Default toward skipping pure chatter and trivial reads, but write a log entry for key operation history that should survive restart. Do not mirror every tool call mechanically.

- `skip`: no information worth recording.
- `log_detail`: complete operation record with full details written to `<namespace>/log/*.jsonl` via `write-log`.
- `log_summary`: key results or milestones written to `<namespace>/log/*.jsonl` via `write-log` with `level=summary`.
- `write_doc`: mature knowledge or workflow written to `<namespace>/docs/*.md` via `upsert-doc`.
- `write_memory`: stable facts or confirmed decisions written to `<namespace>/MEMORY.md` via `write-memory`.

For `<namespace>/log/*.jsonl`, prefer recording over skipping when there was a key concrete operation, state change, verification, issue, fix, decision, commit, push, build, deployment, hook change, config change, or user-confirmed workflow event. The log is the continuity ledger and should be comprehensive enough to reconstruct what happened after restart, but it should not become a per-tool transcript.

Use `skip` mainly for pure greetings, purely conversational turns with no reusable context, trivial reads that produced no decision or state change, or repeated identical tool activity with no new information.

Routing:

- Complete operation records go to `<namespace>/log/*.jsonl` with `level=detail`: commands run, services restarted, files edited, config changed, branches/commits/pushes, builds, deployments, tests, debugging traces, verification, failures, fixes, and remaining risks.
- Key results and milestones go to `<namespace>/log/*.jsonl` with `level=summary`: successful completion, release/PR state, verified behavior, or important user-facing outcomes.
- Write enough fields in `text` to be useful later: what was done, why, command or host event when relevant, important parameters, affected paths, result status, commit hash/PR/deploy URL when available, and unresolved follow-up.
- Mature workflows, best practices, and troubleshooting guides go to `<namespace>/docs/*.md` through `umem upsert-doc`. The minimal invocation is `upsert-doc --doc <slug> --text <body>` (or `--text-stdin`); title/type/modified auto-fallback so handwriting a doc is cheap.
- When consolidating multiple log entries into one doc (context-heavy synthesis, ~5–30 KB of source material), delegate to a subagent via the Agent tool (`subagent_type=general-purpose`). The subagent's isolated context window keeps the main session lean and returns only the final slug + a one-sentence summary.
- Stable facts, confirmed decisions, and durable lessons go to `<namespace>/MEMORY.md` through `umem write-memory`.
- Open issues, parking points, and unresolved risks stay out of `<namespace>/MEMORY.md` unless they become confirmed decisions, durable lessons, or stable facts.
- Stable user preferences go to `<namespace>/PREFERENCES.md` through `umem write-preference`.

Never write:

- raw per-tool transcripts
- one JSONL entry for every tool call as a mechanical mirror
- full temporary command output when a concise result summary is enough
- unverified assumptions as durable memory
- session transcript contents by default; optional `session_archive.enabled` stores pointer records only and does not auto-load them
- open questions directly into `<namespace>/MEMORY.md`

## Maintenance Rules

- `maintain`: scan the configured namespace log for stale `files` references and corrupt JSON lines, and repair missing `<namespace>/docs/index.json` entries.
- `search` / `stats` / `export` are available at any time for quick overview without modifying anything.
- Distill useful patterns from log entries into curated long-term files during light maintenance moments. The automated path is `maintain --distill` -> `maintain --promote <topic>` -> subagent-driven `upsert-doc`; see "Distillation Pipeline" above for the two decision gates and trigger conditions.
- Keep wording agent-agnostic so this skill can be used by both Codex and Claude Code without edits.

## References

- `references/cli-reference.md`: full `umem` / `memory_tool.py` flag reference for every read/write command.
- `references/distillation.md`: distillation tag-family table, backlink semantics, hook trigger internals, subagent prompt template, tuning constants.
- `references/log-entry-examples.md`: full worked good/bad log-entry body examples.
- `references/repo-layout.md`: read when discussing memory repo structure, file responsibilities, document metadata, or tag conventions.
- `references/startup-and-write-rules.md`: read when discussing retrieval triggers, load order, docs index matching, write routing, distillation, or failure behavior.
- `references/machine-setup.md`: read when installing on a new machine, exposing the skill to Codex or Claude Code, debugging config, or running smoke tests.
- `examples/`: sample config files, startup templates, and example memory repo content.
