# memory_tool.py CLI reference

Full flag reference for `scripts/memory_tool.py`. SKILL.md keeps a one-line summary per command; read this file when you need the exact selectors/flags. Prefer executing it directly or with `python3`; do not assume a `python` shim exists.

If top-level config `remote.endpoint` is set, `load`, `search`, `write-log`, `write-memory`, `write-preference`, and `upsert-doc` forward to the web app's `/api/v1` endpoints before touching local files. `remote.token` is sent as `Authorization: Bearer <token>`. Connection failures, timeouts, and HTTP 5xx responses fall back to local execution with a warning; HTTP 4xx responses are surfaced as command errors. `setup`, `maintain`, `stats`, `status`, and `export` stay local.

## Read

- `load`: read memory snapshot. Key selectors: `--config`, `--date`, `--json`, `--log-from` + `--log-to`, `--log-days`, `--log-query`, `--doc` / `--doc-type` / `--doc-tag` / `--project` / `--topic` / `--doc-query`. Returns `log_entries` as a parsed JSON list from the primary repo's configured namespace log.
- `search <query>`: full-text search across `<namespace>/docs/*.md`, `<namespace>/MEMORY.md`, and the configured namespace log. Docs and memory cover primary plus reference roots; log covers the primary root's configured namespace only. Flags: `--config`, `--log-days N`, `--no-docs`, `--no-memory`, `--no-log`, `--project` / `--topic` (repeatable; same axis is OR, different axes are AND; **scope reduces to log-only when either is set**), `--json`.
- `maintain`: default mode scans the configured namespace log for stale `files` references and corrupt JSON lines, and repairs missing `<namespace>/docs/index.json` entries. Generated doc entries use minimal metadata only: title from the first Markdown H1 when present, `type: wiki`, and empty `projects` / `tags`. Flags: `--config`, `--json`.
  - `maintain --distill`: read-only bucket analysis for the log-to-doc distillation pipeline. Groups unpromoted log entries by `(topic, tag-family)`, filters by `--min-entries` (default 3) and `--min-days` (default 3), scores, and returns candidate buckets ready for synthesis into a doc. Updates `last_distill_check_ts` only — never writes log or docs. See `references/distillation.md`.
  - `maintain --promote TOPIC[/FAMILY]`: read-only synthesis of one bucket. Re-reads the full source-entry bodies, attaches the suggested `--doc / --doc-type / --project` and full `--link-log` ref list, and prints a structured prompt suitable for a subagent to read, decide, and (on yes) call `upsert-doc`. Never writes docs itself.
- `stats`: aggregate tag counts across the configured namespace log and `<namespace>/MEMORY.md`. Flags: `--config`, `--json`.
- `status`: lifetime dashboard. Reads `<namespace>/STATS.json` (real event counters incremented by hooks and write-* commands — never estimated), prints session counts / log writes / hook blocks / hook passthroughs plus the `stop_block_ratio` diagnostic ratio. Flags: `--config`, `--json` (raw dict instead of dashboard).
- `export`: format a Markdown summary; stdout by default or `--dest FILE` to append. Flags: `--config`, `--dest`, `--json`.

## Write

- `write-log`: append one primary JSONL entry. Required: `--config`, `--date`, `--tag`, `--text`. Optional: `--level detail|summary`, `--confidence 1-10`, `--source TEXT`, `--files path1 --files path2`, `--project SLUG`, `--topic SLUG`, `--cwd PATH` (override auto-routing context). When `--project` / `--topic` are omitted, they are auto-routed: project from cwd basename, falling back to the parent directory name of the first matching `--files`; topic from text keywords (with `commit` / `deploy` / `release` / `build` / `test` tags short-circuiting to themselves). Allowed tags: `operation`, `progress`, `milestone`, `state`, `result`, `output`, `verification`, `issue`, `debug`, `error`, `fix`, `decision`, `analysis`, `consideration`, `build`, `deploy`, `release`, `commit`, `test`, `benchmark`, `lesson`, `fact`, `pattern`, `insight`, `note`, `context`.
- `write-memory`: append one curated `<namespace>/MEMORY.md` entry. Required: `--config`, `--date`, `--tag`, `--text`; `write-memory` accepts only `fact`, `decision`, and `lesson`.
- `write-preference`: append one stable `<namespace>/PREFERENCES.md` entry. Required: `--config`, `--text`.
- `upsert-doc`: write one `<namespace>/docs/*.md` document and update `<namespace>/docs/index.json`. Required: `--doc`, plus `--text` OR `--text-stdin`. Optional with auto-fallback: `--config` (env / default yaml), `--title` (first H1 in text → slug-derived), `--doc-type` (defaults to `wiki`; common: `wiki`, `lesson`, `troubleshooting`, `decision-record`, `runbook`, `SOP`, `project`), `--modified` (defaults to today). Optional metadata: `--project`, `--doc-tag`, `--summary`. Optional backlinks: `--link-log '[[log:YYYY-MM-DD#L<n>]]'` (repeatable; appends/merges a `## Related log entries` section, deduped). The distillation pipeline emits one `--link-log` per source entry so promoted log entries can be filtered out on the next distill pass.

## Remote forwarding map

When `remote.endpoint` is configured:

| CLI command | HTTP endpoint | Fallback |
|---|---|---|
| `load` | `GET /api/v1/load` | yes for connection errors/timeouts/5xx |
| `search` | `GET /api/v1/search` | yes for connection errors/timeouts/5xx |
| `write-log` | `POST /api/v1/log` | yes for connection errors/timeouts/5xx |
| `write-memory` | `POST /api/v1/memory` | yes for connection errors/timeouts/5xx |
| `write-preference` | `POST /api/v1/preference` | yes for connection errors/timeouts/5xx |
| `upsert-doc` | `POST /api/v1/doc` | yes for connection errors/timeouts/5xx |

Loopback `memory-web` API calls are allowed without a bearer token so a local `umem` wrapper can forward to a local server without extra friction. Non-loopback clients must send the configured bearer token when `remote.token` is set.
