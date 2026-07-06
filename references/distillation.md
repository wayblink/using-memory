# Distillation Pipeline — full details

A three-stage, two-gate pipeline turns repeated log buckets into curated docs. The pipeline is the only path that writes new docs from log activity, and every stage stays read-only until the very last call. The two gates ensure that no rule, hook, or subprocess can land a doc on its own — at least two LLM-in-the-loop decisions stand between a candidate bucket and a `docs/*.md` file. SKILL.md keeps the summary; this file has the tables and templates.

## Stages

```
log/*.jsonl  --[1] distill-->  candidate buckets  --[2] promote-->  prompt  --[3] upsert-doc-->  docs/*.md
                                       ^                                ^                          ^
                                  hook injects                   subagent reads                 only writer
                                                                  & decides
```

1. **distill** (`maintain --distill`): read-only bucket analysis. Groups log entries by `(topic, tag-family)`, filters by `--min-entries` and `--min-days`, scores, and returns candidates. Updates `last_distill_check_ts` only.
2. **promote** (`maintain --promote TOPIC[/FAMILY]`): read-only synthesis prompt. Re-reads source entries in full, attaches suggested upsert-doc parameters, and emits structured markdown for a subagent. Never writes.
3. **upsert-doc** (`upsert-doc --doc <slug> --text-stdin --link-log <ref> ...`): the **only** stage that touches `docs/`. Writes the synthesized body, updates `index.json`, and merges `[[log:YYYY-MM-DD#L<n>]]` backlinks into a `## Related log entries` section.

## Two decision gates

- **Gate A — should this bucket be promoted?** The main-session model reads the candidate list (injected by the SessionStart / Stop hook) and decides whether to delegate. The cost of saying "not now" is one hook-injected reminder per ~100 turns; the cost of saying "yes" is spawning a subagent. The cheap default is to skip when the current task is unrelated.
- **Gate B — does the synthesized doc deserve to land?** The subagent reads the full prompt (5–30 KB of source text), decides whether the bucket actually coheres, and on yes calls `upsert-doc`. On no it returns a one-line summary explaining the mismatch and writes nothing. This catches buckets that look related by topic but turn out to be three different things sharing a label.

`docs/` cannot be written without passing both gates. The hook never calls `upsert-doc` directly; it can only inject candidates.

## Tag families

`distill` collapses the 26 log tags into 4 doc-shaped families. Tags not listed are skipped on purpose (noise-prone or already covered):

| Family | Tags | Suggested doc-type |
|---|---|---|
| `lesson` | `lesson`, `pattern`, `insight`, `fact` | `lesson` |
| `troubleshooting` | `fix`, `debug`, `error` | `troubleshooting` |
| `decision` | `decision`, `analysis`, `consideration` | `decision-record` |
| `runbook` | `operation`, `build`, `deploy`, `commit`, `release`, `verification` | `runbook` |

When an entry lacks a `topic` field (older logs pre-date auto-routing), distill applies the same regex inference `write-log` would have used at creation time, so historical data isn't permanently invisible.

## Backlinks: `[[log:YYYY-MM-DD#L<n>]]`

Every doc body emitted by promote / synthesized by a subagent should cite its source log entries with `[[log:YYYY-MM-DD#L<n>]]`. The `<n>` is the 1-based line number inside the JSONL file. `upsert-doc --link-log` accepts these refs (repeatable) and merges them into a `## Related log entries` section. The merge is dedup-safe; calling upsert-doc again on the same doc with overlapping refs leaves a clean union.

The distillation filter uses backlinks as the source of truth for "already promoted." A log entry with at least one `[[log:date#L<n>]]` reference in any doc is excluded from future buckets — so the same lesson cannot be promoted twice unless the user explicitly removes the backlink.

## Hook trigger

Both SessionStart and Stop / SubagentStop hooks call `fetch_distillation_candidates()`, which:

- Reads `cumulative_human_turns` (Stop hook accumulates real human-turn deltas across sessions, idempotent) and `last_distill_inject_ts` from STATS.json.
- Triggers when **either** `cumulative_human_turns - last_distill_inject_turn >= 100` **or** `now - last_distill_inject_ts >= 1 day`.
- Runs `maintain --distill --json` (read-only, milliseconds), and on candidates injects a compact summary into `additionalContext` (SessionStart) or appends it to the block reason (Stop).
- Updates `last_distill_inject_ts` and `last_distill_inject_turn` whether or not buckets were found, so an empty state doesn't make every hook re-run the subprocess.

The check is cheap (no docs, no log mutations) and runs every relevant hook; only the **inject** is throttled. This keeps SessionStart fast while ensuring long sessions still get a periodic nudge.

## Subagent delegation

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

## Tuning

Defaults are conservative: `--min-entries 3`, `--min-days 3`. Lower them to surface earlier candidates (`maintain --distill --min-entries 2 --min-days 1`); raise them to filter aggressively. The hook trigger uses `DISTILL_TURN_INTERVAL = 100` and `DISTILL_DAY_INTERVAL_SEC = 86400` in `memory_hook_common.py` — adjust those constants if a project's tempo demands more or less frequent injects.
