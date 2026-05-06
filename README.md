# using-memory

`using-memory` is a memory-management skill for Codex and Claude Code. It stores cross-session memory in one or more Git-managed Markdown repos, and `scripts/memory_tool.py` provides loading, writing, and document-index maintenance.

The project goal is to make every new conversation load durable memory in a stable order and route new information to the right place, instead of mixing preferences, facts, temporary logs, and structured documents together.

## Memory Repo Layout

A typical memory repo looks like this:

```text
memory-repo/
+-- PREFERENCES.md
+-- MEMORY.md
+-- docs/
|   +-- index.json
|   +-- project-alpha.md
|   +-- writing-rules.md
+-- daily/
|   +-- 2026-05-06.md
+-- local/
    +-- MACHINE.md
    +-- ENV.md
    +-- WORKSPACE.md
```

Layer responsibilities:

- `PREFERENCES.md`: long-lived preferences, working style, output style, and stable constraints.
- `MEMORY.md`: stable cross-project facts, decisions, and long-term lessons.
- `docs/`: structured documents such as wiki, SOP, todo, plan, and project notes.
- `docs/index.json`: an index for `docs/*.md`, including title, type, tags, modified time, related projects, and other metadata.
- `daily/`: date-based working notes, same-day context, and undistilled information.
- `local/MACHINE.md`: current-machine identity, role, hardware, network, and stable machine-local facts.
- `local/ENV.md`: current-machine toolchains, shell, runtime, and system constraints.
- `local/WORKSPACE.md`: current-machine workspaces, repo paths, and project entry points.

## Load Order

At startup, the skill follows this macro load order:

1. Read `PREFERENCES.md` and `MEMORY.md` from every configured repo.
2. Read `docs/index.json` from every repo, then load matching `docs/*.md` documents by index metadata, type, tag, project, or query.
3. Read recent `daily/` and `local/` records from the primary repo. By default, only today and yesterday are loaded; larger date windows must be requested explicitly through CLI flags.

The intent is to establish stable preferences and durable facts first, select structured documents by index second, and add short-term context last.

## Write Boundaries

Writes are routed by information type:

- User preferences, durable constraints, and working style go to `PREFERENCES.md`.
- Stable facts, confirmed decisions, and long-term lessons go to `MEMORY.md`.
- Wiki, SOP, todo, plan, and project notes go to `docs/*.md`, with `docs/index.json` updated at the same time.
- Same-day process notes, temporary context, and unconfirmed information usually go to `daily/YYYY-MM-DD.md` or explicit local records.

Open issues, temporary assumptions, and unconfirmed plans are not written directly to `MEMORY.md` by default.

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
  - role: primary
  - writable: true
  - machine_id: local-main
  - priority: 100

defaults:
  read_today: true
  read_yesterday: true
  load_docs_on_demand: true
```

Python dependencies are listed in [requirements.txt](requirements.txt). The current CLI needs `PyYAML` to parse local config.

## CLI Usage

Show available commands:

```bash
python3 scripts/memory_tool.py --help
```

Current commands:

- `load`: load memory according to the skill rules.
- `write-daily`: append one daily entry in the primary repo.
- `write-memory`: append curated long-term memory to `MEMORY.md`.
- `write-preference`: append a durable preference to `PREFERENCES.md`.
- `upsert-doc`: create or update `docs/*.md` and maintain `docs/index.json`.

Load the default context:

```bash
python3 scripts/memory_tool.py load
```

Load a larger daily date range:

```bash
python3 scripts/memory_tool.py load --daily-from 2026-05-01 --daily-to 2026-05-06
python3 scripts/memory_tool.py load --daily-days 14
python3 scripts/memory_tool.py load --daily-days 30 --daily-query "project alpha"
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
  --text "The using-memory project uses docs/index.json as its structured document index."
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

Write a daily entry:

```bash
python3 scripts/memory_tool.py write-daily \
  --config ~/.skills/using-memory/config.yaml \
  --date 2026-05-06 \
  --tag fact \
  --text "Finished the initial using-memory README draft today." \
  --confidence 8 \
  --source user
```

Full-text search:

```bash
python3 scripts/memory_tool.py search "deploy"
python3 scripts/memory_tool.py search "bug" --daily-days 7
python3 scripts/memory_tool.py search "deploy" --no-docs --json
```

Check for stale file references in daily JSONL:

```bash
python3 scripts/memory_tool.py prune --config ~/.skills/using-memory/config.yaml
```

Memory stats:

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
