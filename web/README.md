# memory-web

Local web browser for the [using-memory](..) skill. Read-only v0.1 — browse
log entries, docs (markdown + HTML), `MEMORY.md`, `PREFERENCES.md`, anatomy
snapshots, and run full-text search across them.

## Install

Requires Python 3.10+. A virtualenv is recommended.

```bash
cd web
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Dependencies pulled in: `fastapi`, `uvicorn`, `jinja2`, `PyYAML`. No npm /
build step — the markdown renderer (`marked`) is loaded from a CDN at runtime.

## Run

```bash
memory-web                       # http://127.0.0.1:8765
memory-web --open                # also opens a browser tab
memory-web --port 9000
memory-web --host 0.0.0.0        # expose on LAN (no auth — use with care)
memory-web --config /path/to/config.yaml
```

It reads from the same `~/.skills/using-memory/config.yaml` (or
`USING_MEMORY_CONFIG`) that `memory_tool.py` uses, and operates on the
configured primary repo + namespace.

## Pages

| Path | What |
|---|---|
| `/` | Dashboard — STATS.json lifetime counters + diagnostic ratios + anatomy index |
| `/logs` | JSONL log entries with date / tag / level / source / project / topic filters |
| `/search?q=…` | Full-text across docs, `MEMORY.md`, and the configured log window |
| `/docs` | Every `.md` and `.html` file under `<ns>/docs/`, grouped by type |
| `/docs/<slug>` | Single document rendered (see below) |
| `/docs/<slug>?raw=1` | Source text (`text/markdown` for `.md`, `text/plain` for `.html`) |
| `/memory` | `MEMORY.md` rendered |
| `/preferences` | `PREFERENCES.md` rendered |
| `/anatomy` | Registered anatomy projects |
| `/anatomy/<slug>` | File-level snapshot for one project |

### Docs rendering

- `.md` → parsed client-side via `marked.js`. Code blocks are styled but
  syntax highlighting is intentionally off in v0.1.
- `.html` → rendered inside a `sandbox="allow-same-origin"` `<iframe>` with
  `srcdoc`. The doc's own `<style>` stays scoped to the iframe; the host
  page resizes the iframe to fit `scrollHeight`.
- Files that exist on disk but aren't registered in `docs/index.json` are
  still listed and viewable, with an `unindexed` badge.
- Subdirectories under `docs/` are supported; the slug is the relative path
  without extension (`docs/foo/bar.md` → `/docs/foo/bar`).
- Path-traversal guard: requests with `..` or absolute paths are rejected.

## Architecture

```
memory_web.adapter   ── imports scripts/memory_tool.py via importlib.util
                       and wraps do_* functions with types.SimpleNamespace
        ▲
memory_web.app       ── builds the FastAPI app, mounts the routers, points
                       Jinja2 at templates/
        ▲
memory_web.routes.*  ── one router per page (dashboard, logs, search, docs,
                       memory, preferences, anatomy)
        ▲
templates/*.html     ── Jinja2 (Notion-style CSS)
static/style.css     ── single stylesheet, no JS framework
```

Implementation notes:

- FastAPI's auto-generated `/docs` Swagger UI is disabled (`docs_url=None`)
  so our docs browser owns that path.
- The adapter loads `scripts/memory_tool.py` once per process via
  `importlib.util.spec_from_file_location`, so write paths (in v0.4+) will
  naturally maintain `STATS.json` counters, anatomy backlinks, and
  `docs/index.json` consistency the same way the CLI does.
- Markdown / HTML viewing both go through the same `/docs/<slug>` route;
  the template branches on file extension.

## v0.1 scope

Read-only across all dimensions. Editing (`write-memory`,
`write-preference`, `upsert-doc`) is planned for v0.4. Manual triggers for
`maintain` / `distill` / `promote` are planned for v0.5. See SKILL.md for
the broader using-memory roadmap.

## Stopping the server

`Ctrl+C` in the terminal. If you started it with a backgrounded shell,
`pkill -f memory-web` or `lsof -ti :8765 | xargs kill` works.
