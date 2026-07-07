# using-memory

`using-memory` is a memory-management skill for Codex and Claude Code. It stores cross-session memory and operation history in a Git-managed Markdown repo, with every memory file scoped under a configured namespace. The `umem` CLI (`scripts/memory_tool.py`) provides loading, writing, document indexing, and a health dashboard.

The project goal is to make agents load durable memory only when cross-session context is useful, then route new information to the right place instead of mixing preferences, facts, temporary logs, and structured documents together.

## Memory Dimensions

`using-memory` stores three orthogonal kinds of context:

| Axis | What | File | Lifecycle |
|---|---|---|---|
| Time series (operation) | What happened, in order | `<namespace>/log/YYYY-MM-DD.jsonl` | Append-only, broad |
| Cross-project knowledge | Stable facts / decisions / lessons | `<namespace>/MEMORY.md` | Curated, narrow |
| Stable preferences | User-level habits / rules | `<namespace>/PREFERENCES.md` | Curated, very narrow |

The log answers *what did I do*. Project structure snapshots (anatomy) have been split out into a separate skill, `using-anatomy`; see that skill for the project-snapshot dimension.

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
        +-- 2026-05-06.jsonl
```

Layer responsibilities:

- `<namespace>/PREFERENCES.md`: long-lived preferences, working style, output style, and stable constraints.
- `<namespace>/MEMORY.md`: stable cross-project facts, decisions, and long-term lessons.
- `<namespace>/docs/`: structured documents such as wiki, SOP, todo, plan, and project notes.
- `<namespace>/docs/index.json`: an index for `<namespace>/docs/*.md`, including title, type, tags, modified time, related projects, and other metadata.
- `<namespace>/log/`: date-based working notes, same-day context, and operation history.
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

`<namespace>/STATS.json` is never part of this snapshot; it is read on demand by `status`.

## Write Boundaries

Writes are routed by information type:

- User preferences, durable constraints, and working style go to `<namespace>/PREFERENCES.md`.
- Stable facts, confirmed decisions, and long-term lessons go to `<namespace>/MEMORY.md`.
- Wiki, SOP, todo, plan, and project notes go to `<namespace>/docs/*.md`, with `<namespace>/docs/index.json` updated at the same time.
- Same-day process notes, operation history, temporary context, and unconfirmed information usually go to `<namespace>/log/YYYY-MM-DD.jsonl`.

Open issues, temporary assumptions, and unconfirmed plans are not written directly to `<namespace>/MEMORY.md` by default.

JSONL logs are intentionally broader than durable memory. Record concrete operations and key events with minimal filtering: commands, file edits, config changes, service restarts, builds, tests, debugging findings, fixes, commits, pushes, deployments, hook behavior, verification, and remaining risks. Do not mirror every tool call mechanically or preserve raw transcripts; summarize the facts needed to reconstruct what happened.

## Two-axis log routing (project / topic)

JSONL log records have two optional metadata axes:

- `project` — a project slug. Auto-routed from cwd basename, falling back to the parent directory name of the first `--files` path.
- `topic` — auto-routed from text keywords (`hook`, `build`, `deploy`, `test`, `commit`, …). The `commit` / `deploy` / `release` / `build` / `test` tags short-circuit to themselves.

Both axes accept lowercase `[a-z0-9._-]`, 1..64 chars. Fields are only written when present (no null pollution of older entries).

Filter at retrieval time:

```bash
umem load --project spark-ann
umem load --project spark-ann --topic build
umem search "regression" --project spark-ann
```

Same axis repeats are OR, different axes AND. When `search` is called with either axis, scope auto-narrows to log-only (docs and MEMORY.md don't carry these fields yet).

## Anatomy (project snapshots)

Anatomy — the per-project file-index dimension — has been split out into a separate skill, `using-anatomy`. See that skill for registration, snapshots, and the `anatomy-*` commands.

## Health Dashboard (`status` + `/memstatus`)

`<namespace>/STATS.json` is an event-driven counter file. Counters are real events — no estimates, no synthetic "savings" numbers:

- `sessions`
- `log_entries_user`, `log_entries_auto`
- `stop_blocks`, `stop_throttled_passthrough`, `precompact_blocks`

```bash
umem status            # human-readable dashboard
umem status --json     # raw dict
```

The dashboard surfaces a diagnostic ratio:

- `stop_block_ratio = stop_blocks / (stop_blocks + stop_throttled_passthrough)` — high values mean the model is being interrupted often (consider raising `logging.detail_turn_interval`); near-zero values mean the hook is mostly passing through.

This is diagnostic, not a performance claim — the system has no real-API token visibility.

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

Use `link.sh codex` for day-to-day development: Codex reads this checkout through a symlink, so edits to `SKILL.md`, scripts, hooks, and docs are live after a new Codex session starts. Use `install.sh codex` for a copied install when you want Codex isolated from the working tree.

To refresh an existing Codex development install:

```bash
./scripts/link.sh codex
umem --help
python3 ~/.codex/skills/using-memory/scripts/memory_tool.py load --json >/tmp/umem-load.json
```

To replace Codex with a copied install:

```bash
USING_MEMORY_INSTALL_FORCE=1 ./scripts/install.sh codex
umem --help
```

`link.sh` refuses to replace an existing real directory; remove the old directory manually or use `install.sh` for a copied install. `install.sh` refuses to overwrite an existing destination unless `USING_MEMORY_INSTALL_FORCE=1` is set, and copied installs exclude development-only files such as `.git` and `tests/`.

After installation, the skill usually lives at:

```text
~/.codex/skills/using-memory/
~/.claude/skills/using-memory/
```

`install.sh` / `link.sh` also drop a `umem` command into `~/.local/bin` — a thin wrapper so you can run `umem <command>` instead of `python3 <skill>/scripts/memory_tool.py <command>`. Ensure `~/.local/bin` is on your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"   # add to your shell profile if needed
umem --help
```

Override the wrapper location with `UMEM_BIN_DIR`; the `python3 .../memory_tool.py` form always works as a fallback.

## First-time storage setup

On first install or first link through this repo's `scripts/install.sh` or `scripts/link.sh`, the helper script checks for `~/.skills/using-memory/config.yaml` (or `USING_MEMORY_CONFIG`). If no config exists and the terminal is interactive, it starts:

```bash
umem setup
```

Some external skill installers only copy the skill directory and do not execute `scripts/install.sh`; after those installs, run the setup command manually. The setup prompt asks for the memory repo path, optional remote Git repo URL, namespace, and machine ID. When a remote URL is supplied, setup clones it into the requested path or pulls an existing Git checkout. When no remote URL is supplied, setup initializes a local Git repo, seeds the namespace layout, writes the config, and prints the follow-up command to add a remote later. Set `USING_MEMORY_SKIP_SETUP=1` to skip this prompt during automated installs.

You can also run setup non-interactively:

```bash
umem setup --path ~/.memories --namespace main --machine-id local-main
umem setup --path ~/.memories --remote git@github.com:you/memories.git --namespace main --machine-id local-main
```

Fresh setup writes conservative hook defaults into `config.yaml`:

```yaml
logging:
  silent_summary: false
  detail_turn_interval: 20
  hard_gate:
    memory_prompt: true
    important_interval: true

session_archive:
  enabled: false
  mode: pointer
  auto_load: false
  index_events: true
```

These defaults keep startup lean: saved preferences still inject on `SessionStart`, but silent auto-summaries and session pointer archives are opt-in. Existing installs inherit the same defaults even if these fields are absent; copy the block from `examples/config.example.yaml` when you want explicit per-machine tuning.

## Configuration

`umem` resolves config in this order:

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

Optional API remote:

```yaml
remote:
  endpoint: http://127.0.0.1:8765
  token: change-me
```

When top-level `remote.endpoint` is configured, `umem load`, `umem search`, `umem write-log`, `umem write-memory`, `umem write-preference`, and `umem upsert-doc` first call the web app's `/api/v1/*` endpoints. `remote.token` is sent as `Authorization: Bearer <token>`. Connection failures, timeouts, and HTTP 5xx responses fall back to the local file backend with a stderr warning; HTTP 4xx responses are treated as command errors. This top-level API remote is separate from `umem setup --remote`, which is still the Git remote URL for syncing the memory repo.

Python dependencies are listed in [requirements.txt](requirements.txt). The current CLI needs `PyYAML` to parse local config.

## Hook Behaviour

The shared adapter at `scripts/hooks/memory_hook_common.py` is wired into Claude Code via `~/.claude/settings.json` and into Codex via `~/.codex/hooks.json`. Both adapters share the same `run()` entry point — any hook change applies to both hosts automatically.

| Event | Action |
|---|---|
| **SessionStart** | Inject memory-protocol reminder + compact preference summary from `<namespace>/PREFERENCES.md`. |
| **UserPromptSubmit** | Set `prompt_mentions_memory` if the prompt contains memory keywords; emit reminder when set. Session-lifetime counters are not reset. |
| **PostToolUse** / **PostToolBatch** | Update `important_events` / `memory_written` flags. |
| **Stop** / **SubagentStop** | Layered throttle. `stop_hook_active` short-circuits to `{}`. If the final message contains a memory-write call, mark `memory_written=true` and pass through. Otherwise count real human user turns in the transcript JSONL: when configured memory-prompt gating is active or `delta >= logging.detail_turn_interval` (default `20`), BLOCK with a short reason asking the model to write a detail-level log. Silent `level=summary tag=progress source=auto` appends happen only when `logging.silent_summary: true`. If `session_archive.enabled: true`, successful Stop pass-through appends a pointer record to `<namespace>/sessions/index.jsonl`. |
| **PreCompact** | Disabled. Previous BLOCK behavior could hang context compaction; do not wire it in new installs. If an older host still invokes it, the handler returns `{}`. |

Block reasons are intentionally short (~200 chars) — they are a *trigger* for the model to call `write-log`, not a place to replay the model's own tool history.

For Codex, enable the hooks feature in `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

Then point `~/.codex/hooks.json` at `~/.codex/skills/using-memory/scripts/hooks/codex_memory_hook.py` for `SessionStart`, `UserPromptSubmit`, `PostToolUse`, and `Stop`. Do not add `PreCompact` on new installs; it is intentionally disabled.

For Claude Code, point `SessionStart` at `~/.claude/skills/using-memory/scripts/hooks/claude_session_start_hook.py` so startup includes both `using-superpowers` and `using-memory`. Point `UserPromptSubmit`, `PostToolUse`, `PostToolBatch`, `ConfigChange`, and `Stop` at `~/.claude/skills/using-memory/scripts/hooks/claude_memory_hook.py`. Do not add `PreCompact` on new installs.

When you pull an update that changes hook behavior, rerun `./scripts/link.sh` or `./scripts/install.sh both` before restarting the host. Copied installs do not pick up new helper scripts until you reinstall.

See [references/machine-setup.md](references/machine-setup.md) for complete hook JSON examples and smoke tests.

## CLI Usage

Invoke as `umem <command>` (installed to `~/.local/bin` by `scripts/install.sh`; equivalent to `python3 <skill>/scripts/memory_tool.py <command>`). Every command takes `--config` (env `USING_MEMORY_CONFIG`, or the default `~/.skills/using-memory/config.yaml`) and supports `--json`.

**When unsure of a command's flags, run `umem <command> --help`.** The full flag reference also lives in [`references/cli-reference.md`](references/cli-reference.md) — flags and examples are intentionally not duplicated here.

### Read

| Command | What |
|---|---|
| `umem load` | Print the memory snapshot: preferences + durable memory + recent log window + matched docs. |
| `umem search` | Full-text search (query as positional arg) across `docs/*.md`, `MEMORY.md`, and the namespace log. |
| `umem maintain` | Repair `docs/index.json`, flag stale/corrupt log lines. `--distill` / `--promote TOPIC` drive the distillation pipeline (read-only). |
| `umem stats` | Aggregate tag counts across the log + `MEMORY.md`. |
| `umem status` | Lifetime hook/counter dashboard from `STATS.json`. |
| `umem export` | Markdown summary to stdout or `--dest FILE`. |

### Write

| Command | What |
|---|---|
| `umem write-log` | Append one JSONL operation-log entry. Required: `--date --tag --text`; `--project`/`--topic` auto-route from cwd/files/text when omitted. |
| `umem write-memory` | Append one curated `MEMORY.md` entry (tags: `fact` / `decision` / `lesson`). |
| `umem write-preference` | Append one stable `PREFERENCES.md` entry. Required: `--text`. |
| `umem upsert-doc` | Write one `docs/*.md` + update `index.json`. Required: `--doc` plus `--text` / `--text-stdin`. |
| `umem setup` | Write the machine-local config (path / namespace / machine-id / optional remote). |


## Tests

Run the full test suite:

```bash
.venv/bin/python -m pytest -q; echo EXIT:$?
```

Trust the exit code, not just the summary text. The web/API suite uses FastAPI's `TestClient`, so deprecation warnings from FastAPI/Starlette can appear while behavior still passes.

## Web browser (optional)

`web/` ships a FastAPI app that browses the same memory repo via the same `config.yaml`. It also exposes `/api/v1` for command-level remote access: POST `log`, `memory`, `preference`, and `doc`; GET `load`, `search`, and `health`. If top-level `remote.token` is configured, non-loopback `/api/v1` clients must send `Authorization: Bearer <token>`; loopback calls remain usable for local development.

```bash
cd web
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
memory-web --open    # → http://127.0.0.1:8765
```

See [web/README.md](web/README.md) for pages, architecture, API remote behavior, and browser QA notes.

## References

- [SKILL.md](SKILL.md): the runtime entry point and formal model-facing instructions.
- [references/repo-layout.md](references/repo-layout.md): memory repo structure, file responsibilities, and tag conventions.
- [references/startup-and-write-rules.md](references/startup-and-write-rules.md): runtime load order, docs matching, write routing, and failure degradation.
- [references/machine-setup.md](references/machine-setup.md): Codex and Claude Code installation, startup wiring, new-machine setup, and smoke tests.
- [web/README.md](web/README.md): optional local web browser for the memory repo.
- [examples/memory-repo/](examples/memory-repo/): sample memory repo content.
