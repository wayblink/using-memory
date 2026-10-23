/**
 * guidance.ts — the prompt copy the `umem` tool advertises to the model.
 *
 * Pure and Pi-free so it is unit-testable and config-overridable.
 *
 * Why these live here and not only in `SKILL.md`: Pi puts a skill's *name and
 * description* in the system prompt and loads the body only when the model
 * chooses to open it. The routing rules below are the ones that decide whether
 * a write goes to the log, to MEMORY, or to PREFERENCES — if the model has to
 * load a skill to learn them, it will have already written to the wrong file.
 * So the load-bearing rules go in `promptGuidelines`, and the skill body keeps
 * the long-form reference.
 *
 * Plain sentences in priority order — Pi adds the bullets, so a literal "1."
 * would render as "• 1. …".
 */

export const PROMPT_SNIPPET =
  "Persisted memory: recall saved preferences/decisions/logs, and record operations that should survive this session.";

export const PROMPT_GUIDELINES: readonly string[] = [
  "Do not load memory on every turn. Decide first whether persisted context could change this answer — prior preferences, a decision already made, previous work on the same project — and call `load` only when it could. A greeting, a one-off command, or a task with enough local context skips it.",
  "When memory is needed, `load` first (it returns preferences, durable memory, recent log entries and matching docs), then `search` for anything older than the default window. Do not guess at a past decision you could look up.",
  "Route every write by kind, not by convenience: a stable user habit goes to `write-preference`; a stable fact, confirmed decision, or long-lived lesson goes to `write-memory`; an operation, build, deploy, commit, test, debug trace, or fix goes to `write-log`. Open questions and unverified assumptions go nowhere — they belong in the conversation, not in durable memory.",
  "`write-log` bodies must be structured Markdown with `## <one-line title>`, then `Context`, `Operations`, `Result`/`Verification`, and `Decisions`/`Open` sections — 800–3000 chars for level=detail, 300–800 for level=summary. A one-sentence entry is almost always missing Context or Result and will be useless in three days.",
  "Inside a log body, use absolute paths and concrete identifiers — commands, parameters, commit SHAs, branch names, versions, row counts, exit codes. Record failures and skipped steps explicitly; an entry that hides a failure is worse than no entry, because the next session trusts it.",
  "`files` takes one path per entry. Never join several paths into one comma-separated string — the field is an index, so a joined value becomes one bogus path.",
  "Never write a per-tool-call transcript, raw command output that a summary would convey, or unverified claims. The log is a continuity ledger, not a mirror of the conversation.",
  "`maintain` is the maintenance door: plain `maintain` repairs stale file references and the docs index, `--distill` lists candidate buckets of repeated log entries, and `--promote <topic>` renders the prompt for turning one bucket into a doc. Both are read-only until `upsert-doc` writes.",
];

export interface ResolvedGuidance {
  readonly promptSnippet: string;
  readonly promptGuidelines: readonly string[];
}

export function resolveGuidance(overrides?: {
  promptSnippet?: string;
  promptGuidelines?: readonly string[];
}): ResolvedGuidance {
  return {
    promptSnippet: overrides?.promptSnippet ?? PROMPT_SNIPPET,
    promptGuidelines: overrides?.promptGuidelines ?? PROMPT_GUIDELINES,
  };
}
