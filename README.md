# using-memory

`using-memory` is a memory-management skill for Codex and Claude Code. It stores cross-session memory and operation history in a Git-managed Markdown repo, with every memory file scoped under a configured namespace, and `scripts/memory_tool.py` provides loading, writing, and document-index maintenance.

The project goal is to make agents load durable memory only when cross-session context is useful, then route new information to the right place instead of mixing preferences, facts, temporary logs, and structured documents together.

## Memory Repo Layout

A typical memory repo looks like this. The repo root is only the Git checkout; memory files start at `<namespace>/`.

```text
memory-repo/
+-- main/
    +-- PREFERENCES.md
    +-- MEMORY.md
    +-- docs/
    |   +-- index.json
    |   +-- project-alpha.md
    |   +-- writing-rules.md
    +-- log/
    |   +-- 2026-05-06.jsonl
    +-- local/
        +-- MACHINE.md
        +-- ENV.md
        +-- WORKSPACE.md
```

Layer responsibilities:

- `<namespace>/PREFERENCES.md`: long-lived preferences, working style, output style, and stable constraints.
- `<namespace>/MEMORY.md`: stable cross-project facts, decisions, and long-term lessons.
- `<namespace>/docs/`: structured documents such as wiki, SOP, todo, plan, and project notes.
- `<namespace>/docs/index.json`: an index for `<namespace>/docs/*.md`, including title, type, tags, modified time, related projects, and other metadata.
- `<namespace>/log/`: date-based working notes, same-day context, and undistilled information for one user, machine, server, or environment.
- `<namespace>/local/MACHINE.md`: namespace-local identity, role, hardware, network, and stable local facts.
- `<namespace>/local/ENV.md`: namespace-local toolchains, shell, runtime, and system constraints.
- `<namespace>/local/WORKSPACE.md`: namespace-local workspaces, repo paths, and project entry points.

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
3. Read recent `<namespace>/log/` and `<namespace>/local/` records from the primary repo. By default, only today and yesterday are loaded; larger date windows must be requested explicitly through CLI flags.

The intent is to establish stable preferences and durable facts first, select structured documents by index second, and add short-term context last.

## Write Boundaries

Writes are routed by information type:

- User preferences, durable constraints, and working style go to `<namespace>/PREFERENCES.md`.
- Stable facts, confirmed decisions, and long-term lessons go to `<namespace>/MEMORY.md`.
- Wiki, SOP, todo, plan, and project notes go to `<namespace>/docs/*.md`, with `<namespace>/docs/index.json` updated at the same time.
- Same-day process notes, operation history, temporary context, and unconfirmed information usually go to `<namespace>/log/YYYY-MM-DD.jsonl` or explicit namespace-local records.

Open issues, temporary assumptions, and unconfirmed plans are not written directly to `<namespace>/MEMORY.md` by default.

JSONL logs are intentionally broader than durable memory. Record concrete operations and key events with minimal filtering: commands, file edits, config changes, service restarts, builds, tests, debugging findings, fixes, commits, pushes, deployments, hook behavior, verification, and remaining risks. Do not mirror every tool call mechanically or preserve raw transcripts; summarize the facts needed to reconstruct what happened.

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

## Host Hook Enforcement

Skill text improves routing, but Codex and Claude Code hooks add a pre-final write gate. The bundled hook scripts live in `scripts/hooks/`:

- `codex_memory_hook.py`: Codex hook adapter.
- `claude_memory_hook.py`: Claude Code hook adapter.
- `memory_hook_common.py`: shared trigger detection and Stop-gate logic.

The hooks do not load memory on every turn and do not write memory automatically. They inject a short reminder when memory/logging triggers are present, track operation-like tool events, and block `Stop` once when the turn appears to contain operation history but no memory write was observed. The continuation prompt asks the agent to run `scripts/memory_tool.py write-log` with concrete operation facts before finalizing.

For Codex, enable the hooks feature in `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

Then point `~/.codex/hooks.json` at `~/.codex/skills/using-memory/scripts/hooks/codex_memory_hook.py` for `SessionStart`, `UserPromptSubmit`, `PostToolUse`, and `Stop`.

For Claude Code, point `~/.claude/settings.json` at `~/.claude/skills/using-memory/scripts/hooks/claude_memory_hook.py` for `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `PostToolBatch`, `ConfigChange`, and `Stop`.

See [references/machine-setup.md](references/machine-setup.md) for complete hook JSON examples and smoke tests. Hooks are deterministic gates around a heuristic detector; they reduce missed log writes, but the agent still has to summarize accurately.

## CLI Usage

Show available commands:

```bash
python3 scripts/memory_tool.py --help
```

Current commands:

- `load`: load memory according to the skill rules. `--log-query` filters parsed log entries by their `text` field.
- `search`: full-text search across namespace docs, durable memory, and primary log JSONL.
- `maintain`: check log JSONL health and repair missing `<namespace>/docs/index.json` entries for manually added docs.
- `stats`: summarize primary log JSONL and `<namespace>/MEMORY.md` tag counts.
- `export`: export a Markdown memory summary.
- `write-log`: append one log entry in the primary repo's configured namespace.
- `write-memory`: append curated long-term memory to `<namespace>/MEMORY.md`.
- `write-preference`: append a durable preference to `<namespace>/PREFERENCES.md`.
- `upsert-doc`: create or update `<namespace>/docs/*.md` and maintain `<namespace>/docs/index.json`.

Load the default context:

```bash
python3 scripts/memory_tool.py load
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

Write a log entry:

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

`write-log` writes `<namespace>/log/YYYY-MM-DD.jsonl` and auto-generates `ts` as a local timezone ISO 8601 timestamp with an offset, such as `2026-05-06T18:30:00+08:00`.

Allowed log tags are:

```text
operation, progress, milestone, state, result, output, verification,
issue, debug, error, fix, decision, analysis, consideration, build,
deploy, release, commit, test, benchmark, lesson, fact, pattern,
insight, note, context
```

Full-text search. Search returns a `scope` object: docs and memory search cover primary plus reference roots, while log search covers the primary root's configured namespace only.

```bash
python3 scripts/memory_tool.py search "deploy"
python3 scripts/memory_tool.py search "bug" --log-days 7
python3 scripts/memory_tool.py search "deploy" --no-docs --json
```

Run maintenance checks and repair missing docs index entries:

```bash
python3 scripts/memory_tool.py maintain --config ~/.skills/using-memory/config.yaml
```

When `maintain` indexes manually added docs, it creates minimal metadata only: `title` from the first Markdown H1 when present, `type: wiki`, and empty `projects` / `tags`. Use `upsert-doc` when you need precise document type, project, tag, or summary metadata.

Memory stats. Stats return a `scope` object and currently count the primary root only:

```bash
python3 scripts/memory_tool.py stats
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
