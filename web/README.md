# memory-web

Local web browser + lightweight editor for the [using-memory](..) skill.
Browse and edit log entries, docs (markdown + HTML), `MEMORY.md`,
`PREFERENCES.md`, download underlying files, and run full-text search across them.
Bilingual UI (English / Chinese).

## Install

Requires Python 3.10+. A virtualenv is recommended.

```bash
cd web
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Dependencies: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `PyYAML`.
No npm / build step — `marked.js` for markdown rendering is loaded from a
CDN at runtime.

## Run

```bash
memory-web                       # http://127.0.0.1:8765
memory-web --open                # also opens a browser tab
memory-web --port 9000
memory-web --host 0.0.0.0        # expose on LAN; set remote.token for /api/v1 auth
memory-web --config /path/to/config.yaml
```

The app reads from the same `~/.skills/using-memory/config.yaml` (or
`USING_MEMORY_CONFIG`) that `memory_tool.py` uses, and operates on the
configured primary repo + namespace.

If the config has top-level `remote.token`, non-loopback `/api/v1` requests
must send `Authorization: Bearer <token>`. Loopback clients are exempt so local
CLI forwarding remains frictionless.

The version pill in the sidebar reads from `<repo>/version.txt` (the
skill's source of truth). The probe falls back to common skill install
paths (`~/.skills/using-memory/`, `~/.claude/skills/using-memory/`,
`~/.codex/skills/using-memory/`), then `unknown` if nothing matches.

## Pages

| Path | What |
|---|---|
| `/` | Dashboard — STATS.json counters, ratios, **estimated tokens kept out of context** |
| `/logs` | JSONL log entries, markdown-rendered, filters: date / days / tag / level / source / project / topic / text |
| `/search?q=…` | Full-text across docs, `MEMORY.md`, and the log window. Each hit is a clickable card |
| `/docs` | Every `.md` and `.html` under `<ns>/docs/`, with type / format / project / tag / indexed / title filters |
| `/docs/new` | Empty editor for a new `.md` doc |
| `/docs/<rel>` | Single document rendered (`.md` via marked.js, `.html` in a sandboxed iframe) |
| `/docs/<rel>?edit=1` | Editor for an existing `.md` doc (textarea + Write/Preview toggle) |
| `/docs/<rel>?raw=1` | Source text (`text/markdown` or `text/plain`) |
| `/docs/<rel>/download` | Download the original doc file as an attachment |
| `POST /docs/save` | Upsert one doc via `memory_tool.upsert-doc` |
| `/memory` | `MEMORY.md` rendered + Append-entry form (`fact` / `decision` / `lesson`) |
| `/memory/download` | Download `MEMORY.md` |
| `POST /memory/append` | Append via `memory_tool.write-memory` |
| `/preferences` | `PREFERENCES.md` rendered + Append-preference form |
| `/preferences/download` | Download `PREFERENCES.md` |
| `POST /preferences/append` | Append via `memory_tool.write-preference` |
| `/api/v1/health` | JSON health endpoint for remote CLI forwarding |
| `GET /api/v1/load`, `GET /api/v1/search` | JSON read endpoints matching the CLI read commands |
| `POST /api/v1/log`, `POST /api/v1/memory`, `POST /api/v1/preference`, `POST /api/v1/doc` | JSON write endpoints matching the CLI write commands |
| `/lang/{en,zh}` | Set language cookie + redirect back |
| `/favicon.ico` · `/static/favicon.svg` | SVG favicon (also referenced via `<link rel="icon">`) |

### Search → source navigation

Every search hit links back to its origin:

- **Docs** hit → `/docs/<rel>` (rendered doc).
- **Memory** hit → `/memory`.
- **Log** hit → `/logs?from=YYYY-MM-DD&to=YYYY-MM-DD&q=<query>` — the
  date is parsed from the JSONL filename stem and the original query is
  forwarded so the log filter narrows to that day's matching entries.

### Docs rendering

- `.md` → parsed client-side via `marked.js`. Code blocks are styled but
  not syntax-highlighted.
- `.html` → rendered inside a `sandbox="allow-same-origin"` `<iframe>`
  with `srcdoc`. The doc's own `<style>` stays scoped to the iframe; the
  host resizes the iframe to fit `scrollHeight`.
- Files on disk that aren't registered in `docs/index.json` are still
  listed and viewable, with an `unindexed` badge.
- Subdirectories under `docs/` are supported.
- Path-traversal guard: requests with `..` or absolute paths are rejected.
- HTML docs are read-only — `memory_tool.upsert-doc` is markdown-only.

### Logs markdown

Each log entry's `text` field is rendered as GFM markdown. Headings
inside an entry are scaled down (16/15/14 px) so cards stay compact.
Bullets, code spans, fenced code, links all render normally.

## Editing

Three forms wrap the underlying `memory_tool.py` write commands. All
flow through the adapter (no subprocess), so `STATS.json` counters
and `docs/index.json` stay consistent with the CLI:

- **MEMORY.md** → `write-memory`. Tag restricted to `fact` / `decision`
  / `lesson` (the only values `memory_tool` accepts).
- **PREFERENCES.md** → `write-preference`.
- **docs/*.md** → `upsert-doc`. Full editor: slug, title, type,
  projects, tags, summary, body. Body has a Write / Preview toggle.

Validation failures are captured from `memory_tool`'s stderr via
`contextlib.redirect_stderr` + `SystemExit` trap, then surfaced to the
UI as a warning instead of crashing the worker. PRG on success;
draft-preserving 400 with the form repopulated on failure.

## Internationalization

`memory_web/i18n.py` defines ~140 keys per language. Language resolves
in order: `?lang=` query > `memory_web_lang` cookie > `Accept-Language`
header > `en`. A `GET /lang/{code}` endpoint sets the cookie (1 year,
SameSite=Lax) and redirects to the referer.

User data (log text, doc bodies, tag names, project slugs) is **never**
translated; only UI chrome.

## Dashboard

- **Lifetime counters**: sessions, cumulative turns, log
  entries total / user / auto, MEMORY entries, stop blocks /
  passthroughs, PreCompact saves.
- **Estimated tokens kept out of context** (rough): sums
  `log_entries_auto × 400` + `stop_blocks × 200`.
  Each component is shown with its input counter and heuristic factor.
  Disclaimer makes clear the skill has no real API token visibility.
- **Tag charts**: log tags (blue) and MEMORY.md tags (orange) sorted
  by count, rendered as horizontal bars. Log-tag rows are clickable —
  they jump to `/logs?days=180&tag=<tag>`.

## Architecture

```
memory_web.adapter   ── imports scripts/memory_tool.py via importlib.util
                       and wraps do_* with types.SimpleNamespace; write
                       paths wrapped in stderr-capture + SystemExit trap
        ▲
memory_web.i18n      ── STRINGS dict (en + zh), Translator, lang_context
                       Jinja2 context_processor
        ▲
memory_web.app       ── FastAPI factory; lang middleware; /lang/{code};
                       /favicon.ico; /api/v1 auth middleware; static mount;
                       router mounts
        ▲
memory_web.routes.*  ── one router per page (dashboard, logs, search,
                       docs, memory, preferences)
        ▲
templates/*.html     ── Jinja2, all UI strings via t('key')
static/style.css     ── single stylesheet, no JS framework
static/favicon.svg   ── 32×32 brand favicon (3-line journal motif)
```

Implementation notes:

- FastAPI's auto-generated `/docs` Swagger UI is disabled
  (`docs_url=None`) so our docs browser owns that path.
- The adapter loads `scripts/memory_tool.py` once per process.
- `do_search`'s hits use `source` values `docs` / `MEMORY.md` / `log`;
  the route normalizes them via a `source_map` into the template's
  `docs` / `memory` / `log` buckets.
- Empty form selects (e.g. `?tag=`) are coerced to "no filter" — the
  `Query(None)` default would otherwise parse them as `[""]` and filter
  every entry out.

## Roadmap

- v0.5 — manual triggers for `maintain` / `distill` / `promote` from
  the web UI.

See SKILL.md for the broader using-memory roadmap.

## Stopping the server

`Ctrl+C` in the terminal. If you started it backgrounded,
`pkill -f memory-web` or `lsof -ti :8765 | xargs kill` works.
