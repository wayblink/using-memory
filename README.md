# using-memory

`using-memory` is a memory-management skill for Codex and Claude Code. It stores cross-session memory and operation history in a Git-managed Markdown repo, with every memory file scoped under a configured namespace. `scripts/memory_tool.py` provides loading, writing, document indexing, project anatomy snapshots, and a health dashboard.

The project goal is to make agents load durable memory only when cross-session context is useful, then route new information to the right place instead of mixing preferences, facts, temporary logs, and structured documents together.

## Memory Dimensions

`using-memory` stores four orthogonal kinds of context:

| Axis | What | File | Lifecycle |
|---|---|---|---|
| Time series (operation) | What happened, in order | `<namespace>/log/YYYY-MM-DD.jsonl` | Append-only, broad |
| Cross-project knowledge | Stable facts / decisions / lessons | `<namespace>/MEMORY.md` | Curated, narrow |
| Stable preferences | User-level habits / rules | `<namespace>/PREFERENCES.md` | Curated, very narrow |
| Project snapshot (anatomy) | What a project *looks like right now* | `<namespace>/anatomy/<slug>.{json,md}` | Auto-refreshed on writes |

The log answers *what did I do*; anatomy answers *in what shape did I do it*. They are linked via `[[anatomy:<slug>/<rel>]]` references emitted automatically when `write-log --files` matches a registered project.

## Memory Repo Layout

A typical memory repo looks like this. The repo root is only the Git checkout; memory files start at `<namespace>/`.

```text
memory-repo/
+-- main/
    +-- PREFERENCES.md
    +-- MEMORY.md
    +-- STATS.json                 # machine-local event accounting (not auto-loaded)
    +-- docs/
    |   +-- index.json
    |   +-- project-alpha.md
    |   +-- writing-rules.md
    +-- log/
    |   +-- 2026-05-06.jsonl
    +-- anatomy/                   # project snapshots (V2.0+)
        +-- _index.json
        +-- spark-ann.json
        +-- spark-ann.md
```

Layer responsibilities:

- `<namespace>/PREFERENCES.md`: long-lived preferences, working style, output style, and stable constraints.
- `<namespace>/MEMORY.md`: stable cross-project facts, decisions, and long-term lessons.
- `<namespace>/docs/`: structured documents such as wiki, SOP, todo, plan, and project notes.
- `<namespace>/docs/index.json`: an index for `<namespace>/docs/*.md`, including title, type, tags, modified time, related projects, and other metadata.
- `<namespace>/log/`: date-based working notes, same-day context, and operation history.
- `<namespace>/anatomy/`: project snapshots. JSON is the source of truth (`<slug>.json` per project plus an `_index.json` registry); `<slug>.md` is auto-rendered for humans and the SessionStart context injection.
- `<namespace>/STATS.json`: machine-local event counters maintained by the hooks and write-* commands. Never auto-loaded; intentionally not synced to reference roots (per-machine counts only).

`namespace` is a single path segment under the memory root. It defaults to `main` when omitted. Use a stable value such as a user name, machine ID, server name, or environment name when multiple machines share one Git repo.

The configured `path` must point to the parent directory that contains namespace directories, not to the namespace directory itself. For example, if memory files live under `~/.memories/main`, configure `path: ~/.memories` with `namespace: main`. Do not configure `path: ~/.memories/main` with `namespace: main`; write commands reject that shape to avoid accidental `main/main/log/` paths.

## Retrieval Triggers

The skill is not meant to load saved memory before every task. Use it when the user asks for memory work, refers to prior context, continues a saved project, or when persisted preferences and decisions would materially change the answer.

The trigger description also covers operation-continuity terms such as logs, operations, commits, pushes, builds, tests, deploys, hooks, and equivalent non-English memory or logging terms. Those triggers do not mean every turn should load memory; they mean the agent should consider retrieval and should normally write a JSONL log entry when the turn creates operation history that should survive restart.

Skip it for greetings, simple commands, isolated coding tasks with enough local context, generic explanations, and one-off questions where memory would not change the result.

## Load Order

When retrieval is needed, the skill follows this macro load order:

1. Read `<namespace>/PREFERENCES.md` and `<namespace>/MEMORY.md` from every configured repo.
2. Read `<namespace>/docs/index.json` from every repo, then load matching `<namespace>/docs/*.md` documents by index metadata, type, tag, project, or query.
3. Read recent `<namespace>/log/` records from the primary repo. By default, only today and yesterday are loaded; larger date windows must be requested explicitly through CLI flags.
4. With `load --anatomy`, attach the anatomy snapshot for the project whose root is the longest prefix of cwd. SessionStart hooks do this automatically.

`<namespace>/STATS.json` is never part of this snapshot; it is read on demand by `status`.

## Write Boundaries

Writes are routed by information type:

- User preferences, durable constraints, and working style go to `<namespace>/PREFERENCES.md`.
- Stable facts, confirmed decisions, and long-term lessons go to `<namespace>/MEMORY.md`.
- Wiki, SOP, todo, plan, and project notes go to `<namespace>/docs/*.md`, with `<namespace>/docs/index.json` updated at the same time.
- Same-day process notes, operation history, temporary context, and unconfirmed information usually go to `<namespace>/log/YYYY-MM-DD.jsonl`.
- Project file snapshots go to `<namespace>/anatomy/<slug>.json` via `anatomy-register` + `anatomy-scan` (or the incremental PostToolUse hook).

Open issues, temporary assumptions, and unconfirmed plans are not written directly to `<namespace>/MEMORY.md` by default.

JSONL logs are intentionally broader than durable memory. Record concrete operations and key events with minimal filtering: commands, file edits, config changes, service restarts, builds, tests, debugging findings, fixes, commits, pushes, deployments, hook behavior, verification, and remaining risks. Do not mirror every tool call mechanically or preserve raw transcripts; summarize the facts needed to reconstruct what happened.

## Two-axis log routing (project / topic)

JSONL log records have two optional metadata axes:

- `project` — usually a registered anatomy slug. Auto-routed from cwd (longest-prefix match against `anatomy/_index.json`), falling back to the first `--files` path inside a registered project.
- `topic` — auto-routed from text keywords (`hook`, `build`, `deploy`, `test`, `commit`, `anatomy`, …). The `commit` / `deploy` / `release` / `build` / `test` tags short-circuit to themselves.

Both axes accept lowercase `[a-z0-9._-]`, 1..64 chars. Fields are only written when present (no null pollution of older entries).

Filter at retrieval time:

```bash
python3 scripts/memory_tool.py load --project spark-ann
python3 scripts/memory_tool.py load --project spark-ann --topic build
python3 scripts/memory_tool.py search "regression" --project spark-ann
```

Same axis repeats are OR, different axes AND. When `search` is called with either axis, scope auto-narrows to log-only (docs and MEMORY.md don't carry these fields yet).

## Anatomy (project snapshots)

Anatomy is the *project* dimension: a small per-project file index with kind / token estimate / one-line description per source file. Use it when you want a project map without re-reading every file.

### Register and scan

```bash
python3 scripts/memory_tool.py anatomy-register ~/yard/spark-ann          # slug defaults to basename
python3 scripts/memory_tool.py anatomy-register ~/yard/spark-ann --slug spark
python3 scripts/memory_tool.py anatomy-scan spark-ann                      # full scan
python3 scripts/memory_tool.py anatomy-show spark-ann                      # render markdown
python3 scripts/memory_tool.py anatomy-set spark-ann src/api.py \
  --desc "JWT auth gateway. Trust boundary."                               # locks desc against future scans
python3 scripts/memory_tool.py anatomy-list                                # registered projects
```

Registration is explicit on purpose: `cd ~/Downloads` should not silently create a snapshot, and slug collisions are surfaced at registration time so they cannot drift. Same root + same slug is idempotent; conflicting slug requires explicit `--slug` to disambiguate.

### Auto-attach on SessionStart

```bash
python3 scripts/memory_tool.py load --anatomy --cwd ~/yard/spark-ann/src
```

The bundled hook calls this on every SessionStart and appends the rendered anatomy (capped at ~2000 tokens, falling back to a top-level directory summary above the cap) to the model's context. When cwd is inside an unregistered git repo, it emits a one-line hint suggesting `anatomy-register`. Otherwise it stays silent.

### Incremental upkeep

The PostToolUse hook detects `Write` / `Edit` / `MultiEdit` / `NotebookEdit` / `Create` tool invocations and calls `anatomy-upsert-file` for each touched path. `desc_source: user` entries (set via `anatomy-set`) are preserved through every refresh — only tokens / mtime / kind get updated. Files matching the skip set (lockfiles, binaries, `dist/`, `node_modules/`, `>2 MB`, etc.) are removed from the snapshot.

Run `memory_tool.py maintain` periodically for full reconciliation: it reports `stale_files` (in snapshot, gone from disk), `new_files` (on disk but not in snapshot), and `broken_log_refs` (`[[anatomy:slug/rel]]` citations whose target was removed).

## Health Dashboard (`status` + `/memstatus`)

`<namespace>/STATS.json` is an event-driven counter file. Counters are real events — no estimates, no synthetic "savings" numbers:

- `sessions`, `anatomy_attached_count`, `anatomy_truncated_count`, `anatomy_hint_emitted`, `anatomy_attached_tokens_est`, `anatomy_upserts`
- `log_entries_user`, `log_entries_auto`
- `stop_blocks`, `stop_throttled_passthrough`, `precompact_blocks`

```bash
python3 scripts/memory_tool.py status            # human-readable dashboard
python3 scripts/memory_tool.py status --json     # raw dict
```

The dashboard surfaces two diagnostic ratios:

- `anatomy_hit_rate = anatomy_attached_count / sessions` — low values mean cwd rarely lands inside a registered project; consider running `anatomy-register` on more roots.
- `stop_block_ratio = stop_blocks / (stop_blocks + stop_throttled_passthrough)` — high values mean the model is being interrupted often (consider raising `STOP_DETAIL_TURN_INTERVAL`); near-zero values mean silent summaries are doing the work.

Both are diagnostic, not performance claims — the system has no real-API token visibility.

For Claude Code there is also a `/memstatus` slash command in `~/.claude/commands/memstatus.md` that runs the dashboard and asks the model to give a 3-part summary (what's happening / what the ratios mean / one concrete next action).

## Install

During development, link this directory into both Codex and Claude Code skill directories:

```bash
./scripts/link.sh
```

You can target a single host, or install by copying:

```bash
./scripts/link.sh codex
./scripts/link.sh claude-code
./scripts/install.sh both
```

`link.sh` refuses to replace an existing real directory; remove the old directory manually or use `install.sh` for a copied install. `install.sh` refuses to overwrite an existing destination unless `USING_MEMORY_INSTALL_FORCE=1` is set, and copied installs exclude development-only files such as `.git` and `tests/`.

After installation, the skill usually lives at:

```text
~/.codex/skills/using-memory/
~/.claude/skills/using-memory/
```

## First-time storage setup

On first install or first link through this repo's `scripts/install.sh` or `scripts/link.sh`, the helper script checks for `~/.skills/using-memory/config.yaml` (or `USING_MEMORY_CONFIG`). If no config exists and the terminal is interactive, it starts:

```bash
python3 scripts/memory_tool.py setup
```

Some external skill installers only copy the skill directory and do not execute `scripts/install.sh`; after those installs, run the setup command manually. The setup prompt asks for the memory repo path, optional remote Git repo URL, namespace, and machine ID. When a remote URL is supplied, setup clones it into the requested path or pulls an existing Git checkout. When no remote URL is supplied, setup initializes a local Git repo, seeds the namespace layout, writes the config, and prints the follow-up command to add a remote later. Set `USING_MEMORY_SKIP_SETUP=1` to skip this prompt during automated installs.

You can also run setup non-interactively:

```bash
python3 scripts/memory_tool.py setup --path ~/.memories --namespace main --machine-id local-main
python3 scripts/memory_tool.py setup --path ~/.memories --remote git@github.com:you/memories.git --namespace main --machine-id local-main
```

## Configuration

`memory_tool.py` resolves config in this order:

1. File path from the `USING_MEMORY_CONFIG` environment variable.
2. `~/.skills/using-memory/config.yaml`.

If config is missing, `load` enters `no_memory` mode and emits a warning that setup is needed. Write commands still require a valid writable primary root.

See [examples/config.example.yaml](examples/config.example.yaml) for a full example.

Minimal config:

```yaml
version: 1
memory_roots:
  - path: /absolute/path/to/memory-repo
    role: primary
    writable: true
    namespace: main
    machine_id: local-main
    priority: 100

defaults:
  read_today: true
  read_yesterday: true
  load_docs_on_demand: true
```

Here `path` is the memory root that contains the `main/` namespace directory.

Python dependencies are listed in [requirements.txt](requirements.txt). The current CLI needs `PyYAML` to parse local config.

## Hook Behaviour

The shared adapter at `scripts/hooks/memory_hook_common.py` is wired into Claude Code via `~/.claude/settings.json` and into Codex via `~/.codex/hooks.json`. Both adapters share the same `run()` entry point — any hook change applies to both hosts automatically.

| Event | Action |
|---|---|
| **SessionStart** | Inject memory-protocol reminder + anatomy snapshot for cwd (or one-line hint when cwd is inside an unregistered git repo). |
| **UserPromptSubmit** | Set `prompt_mentions_memory` if the prompt contains memory keywords; emit reminder when set. Session-lifetime counters are not reset. |
| **PostToolUse** / **PostToolBatch** | Update `important_events` / `memory_written` flags. For write/edit-style tools, also call `anatomy-upsert-file` on every touched path (best-effort, 8 s timeout). |
| **Stop** / **SubagentStop** | Layered throttle. `stop_hook_active` short-circuits to `{}`. If the final message contains a memory-write call, mark `memory_written=true` and pass through. Otherwise count real human user turns in the transcript JSONL: when `prompt_mentions_memory` OR `delta >= STOP_DETAIL_TURN_INTERVAL` (default `8`), BLOCK with a short reason asking the model to write a detail-level log. Other substantial turns get a silent `level=summary tag=progress source=auto` log entry (deduped per turn, capped at 200 per session). |
| **PreCompact** | Unconditional BLOCK with a short structured reason: dump current task / unfinished subgoals / key identifiers / open risks before the context window shrinks. `stop_hook_active` / `precompact_hook_active` flags short-circuit to `{}` to prevent loops. |

Block reasons are intentionally short (~200 chars) — they are a *trigger* for the model to call `write-log`, not a place to replay the model's own tool history.

For Codex, enable the hooks feature in `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

Then point `~/.codex/hooks.json` at `~/.codex/skills/using-memory/scripts/hooks/codex_memory_hook.py` for `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `PreCompact`, and `Stop`.

For Claude Code, point `~/.claude/settings.json` at `~/.claude/skills/using-memory/scripts/hooks/claude_memory_hook.py` for `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `PostToolBatch`, `ConfigChange`, `PreCompact`, and `Stop`.

See [references/machine-setup.md](references/machine-setup.md) for complete hook JSON examples and smoke tests.

## CLI Usage

Show available commands:

```bash
python3 scripts/memory_tool.py --help
```

Current commands:

- `load`: load memory according to the skill rules. Flags include `--log-query`, `--project`, `--topic`, `--anatomy`, `--cwd`, `--anatomy-max-tokens`.
- `search`: full-text search across namespace docs, durable memory, and primary log JSONL. With `--project` / `--topic`, scope narrows to log-only.
- `maintain`: check log JSONL health, repair missing `<namespace>/docs/index.json` entries, and audit anatomy projects (`stale_files`, `new_files`, `broken_log_refs`).
- `stats`: summarize primary log JSONL and `<namespace>/MEMORY.md` tag counts.
- `status`: dashboard for `<namespace>/STATS.json` lifetime counters and the registered anatomy projects.
- `export`: export a Markdown memory summary.
- `write-log`: append one log entry. Optional `--project` / `--topic` (auto-routed when omitted), `--cwd` to override auto-routing.
- `write-memory`: append curated long-term memory to `<namespace>/MEMORY.md`.
- `write-preference`: append a durable preference to `<namespace>/PREFERENCES.md`.
- `upsert-doc`: create or update `<namespace>/docs/*.md` and maintain `<namespace>/docs/index.json`.
- `anatomy-register`, `anatomy-scan`, `anatomy-show`, `anatomy-set`, `anatomy-list`, `anatomy-upsert-file`: project snapshot lifecycle.
- `setup`: configure the memory repo path, optional remote Git repo, namespace, and machine ID.

Load the default context:

```bash
python3 scripts/memory_tool.py load
```

Load with axes and anatomy:

```bash
python3 scripts/memory_tool.py load --project spark-ann
python3 scripts/memory_tool.py load --project spark-ann --topic build
python3 scripts/memory_tool.py load --anatomy --cwd ~/yard/spark-ann/src
```

Load a larger log date range:

```bash
python3 scripts/memory_tool.py load --log-from 2026-05-01 --log-to 2026-05-06
python3 scripts/memory_tool.py load --log-days 14
python3 scripts/memory_tool.py load --log-days 30 --log-query "project alpha"
```

Filter docs by index metadata:

```bash
python3 scripts/memory_tool.py load --doc-type SOP
python3 scripts/memory_tool.py load --doc-tag writing
python3 scripts/memory_tool.py load --project project-alpha
python3 scripts/memory_tool.py load --doc-query "deployment"
```

Write a durable preference:

```bash
python3 scripts/memory_tool.py write-preference \
  --config ~/.skills/using-memory/config.yaml \
  --text "User preference: answer direct questions concisely by default."
```

Write durable memory:

```bash
python3 scripts/memory_tool.py write-memory \
  --config ~/.skills/using-memory/config.yaml \
  --date 2026-05-06 \
  --tag fact \
  --text "The using-memory project uses <namespace>/docs/index.json as its structured document index."
```

Create or update a docs document:

```bash
python3 scripts/memory_tool.py upsert-doc \
  --config ~/.skills/using-memory/config.yaml \
  --doc project-alpha \
  --title "Project Alpha" \
  --doc-type project \
  --modified 2026-05-06 \
  --doc-tag planning \
  --project project-alpha \
  --text "Long-term Project Alpha notes."
```

Write a log entry (axes auto-routed when omitted):

```bash
python3 scripts/memory_tool.py write-log \
  --config ~/.skills/using-memory/config.yaml \
  --date 2026-05-06 \
  --tag operation \
  --level summary \
  --text "Finished the initial using-memory README draft today." \
  --confidence 8 \
  --source user
```

Or pin axes explicitly and reference touched files (anatomy refs are auto-appended when files live inside a registered project):

```bash
python3 scripts/memory_tool.py write-log \
  --config ~/.skills/using-memory/config.yaml \
  --date 2026-05-06 \
  --tag commit \
  --project spark-ann \
  --topic build \
  --files /Users/me/yard/spark-ann/build.sh \
  --text "Built Java17 image and pushed to dev registry."
```

`write-log` writes `<namespace>/log/YYYY-MM-DD.jsonl` and auto-generates `ts` as a local timezone ISO 8601 timestamp with an offset, such as `2026-05-06T18:30:00+08:00`.

Allowed log tags are:

```text
operation, progress, milestone, state, result, output, verification,
issue, debug, error, fix, decision, analysis, consideration, build,
deploy, release, commit, test, benchmark, lesson, fact, pattern,
insight, note, context
```

Full-text search. Search returns a `scope` object: docs and memory search cover primary plus reference roots, while log search covers the primary root's configured namespace only. Adding `--project` / `--topic` narrows scope to log-only.

```bash
python3 scripts/memory_tool.py search "deploy"
python3 scripts/memory_tool.py search "bug" --log-days 7
python3 scripts/memory_tool.py search "deploy" --no-docs --json
python3 scripts/memory_tool.py search "regression" --project spark-ann
```

Anatomy lifecycle:

```bash
python3 scripts/memory_tool.py anatomy-register ~/yard/spark-ann --slug spark
python3 scripts/memory_tool.py anatomy-scan spark
python3 scripts/memory_tool.py anatomy-show spark
python3 scripts/memory_tool.py anatomy-set spark src/api.py --desc "JWT auth gateway"
python3 scripts/memory_tool.py anatomy-list
python3 scripts/memory_tool.py anatomy-upsert-file ~/yard/spark-ann/src/api.py
```

Run maintenance checks and repair missing docs index entries:

```bash
python3 scripts/memory_tool.py maintain --config ~/.skills/using-memory/config.yaml
```

When `maintain` indexes manually added docs, it creates minimal metadata only: `title` from the first Markdown H1 when present, `type: wiki`, and empty `projects` / `tags`. Use `upsert-doc` when you need precise document type, project, tag, or summary metadata. `maintain` also audits anatomy drift; the `anatomy` block in the result lists per-project `stale_files`, `new_files`, and any `broken_log_refs`.

Memory stats. Stats return a `scope` object and currently count the primary root only:

```bash
python3 scripts/memory_tool.py stats
```

Health dashboard:

```bash
python3 scripts/memory_tool.py status
python3 scripts/memory_tool.py status --json
```

Export Markdown summary:

```bash
python3 scripts/memory_tool.py export
python3 scripts/memory_tool.py export --dest CLAUDE.md
```

## Tests

Run the full test suite:

```bash
python3 -m unittest discover -s tests -v
```

## References

- [SKILL.md](SKILL.md): the runtime entry point and formal model-facing instructions.
- [references/repo-layout.md](references/repo-layout.md): memory repo structure, file responsibilities, and tag conventions.
- [references/startup-and-write-rules.md](references/startup-and-write-rules.md): runtime load order, docs matching, write routing, and failure degradation.
- [references/machine-setup.md](references/machine-setup.md): Codex and Claude Code installation, startup wiring, new-machine setup, and smoke tests.
- [examples/memory-repo/](examples/memory-repo/): sample memory repo content.
