/**
 * args.ts — structured tool params → `umem` CLI argv.
 *
 * Pure and Pi-free so it is unit-testable without a runtime, exactly like
 * `guidance.ts` in the kanban extension. The CLI owns parsing and validation;
 * this module only decides which flag a field becomes. Every judgement here is
 * about *shape* (which flags are repeatable, which are positional), never about
 * whether a value is legal — a bad value should surface as the CLI's own error,
 * not as a second, differently-worded one from the tool schema.
 */

export const ACTIONS = [
  "load",
  "search",
  "write-log",
  "write-memory",
  "write-preference",
  "upsert-doc",
  "maintain",
  "stats",
  "status",
] as const;

export type Action = (typeof ACTIONS)[number];

/** Actions that only read. Drives the `readOnlyHint` annotation. */
export const READ_ONLY_ACTIONS: ReadonlySet<Action> = new Set([
  "load",
  "search",
  "stats",
  "status",
]);

/**
 * The tag vocabulary `write-log` accepts.
 *
 * Kept as documentation in the parameter description rather than a `StringEnum`:
 * 25 values in the schema is a lot of tokens on every request, and the CLI
 * already rejects an unknown tag with a message that lists the legal set.
 */
export const LOG_TAGS = [
  "operation",
  "progress",
  "milestone",
  "state",
  "result",
  "output",
  "verification",
  "issue",
  "debug",
  "error",
  "fix",
  "decision",
  "analysis",
  "consideration",
  "build",
  "deploy",
  "release",
  "commit",
  "test",
  "benchmark",
  "lesson",
  "fact",
  "pattern",
  "insight",
  "note",
  "context",
] as const;

/** `write-memory` accepts a curated subset. */
export const MEMORY_TAGS = ["fact", "decision", "lesson"] as const;

export interface UmemParams {
  action: Action;
  /** Explicit `--config` override. Normally injected from the extension config. */
  config?: string | undefined;
  /** search: the query string. */
  query?: string | undefined;
  /** write-*: the entry body. */
  text?: string | undefined;
  tag?: string | undefined;
  level?: "detail" | "summary" | undefined;
  date?: string | undefined;
  /** File paths. Repeatable: one `--files` per path, never a joined string. */
  files?: string[] | undefined;
  project?: string | undefined;
  topic?: string | undefined;
  /** write-preference: 'global' (SPEC.md), a repo name (spec/<repo>.md), or 'auto'. */
  scope?: string | undefined;
  confidence?: number | undefined;
  source?: string | undefined;
  /** load: the log window. */
  logDays?: number | undefined;
  logFrom?: string | undefined;
  logTo?: string | undefined;
  logQuery?: string | undefined;
  doc?: string | undefined;
  docType?: string | undefined;
  docTags?: string[] | undefined;
  docQuery?: string | undefined;
  docTitle?: string | undefined;
  summary?: string | undefined;
  /** maintain: the distillation subcommands. */
  distill?: boolean | undefined;
  promote?: string | undefined;
  /** export: destination file. */
  dest?: string | undefined;
}

/**
 * Build the CLI argv for a tool call.
 *
 * Two flags the model should never have to think about are injected by the
 * caller via `defaults`:
 *
 * - `--config`: the write verbs declare it `required=True` in argparse, so
 *   omitting it is a hard failure rather than a fallback.
 * - `--date`: also required, and "today" is always the right answer from a tool
 *   call — a model passing its own idea of today would be guessing across a
 *   timezone or a session that outlived midnight.
 *
 * `--json` is always appended: the tool renders structured output.
 */
export interface ArgDefaults {
  readonly config: string | null;
  /** `YYYY-MM-DD`, supplied when the caller did not choose a date. */
  readonly date: string;
}

/**
 * Actions that need `--date`; `write-preference` defaults it in argparse, and
 * the read verbs do not take it as a required field.
 */
const NEEDS_DATE: ReadonlySet<Action> = new Set(["write-log", "write-memory"]);

export function buildArgs(params: UmemParams, defaults?: ArgDefaults): string[] {
  const args: string[] = [];
  const flag = (name: string, value: string | number | boolean | undefined): void => {
    if (value === undefined || value === false) return;
    if (value === true) {
      args.push(name);
      return;
    }
    args.push(name, String(value));
  };
  const repeated = (name: string, values: readonly string[] | undefined): void => {
    for (const value of values ?? []) {
      // One flag per path. A comma-joined list is the single most common way to
      // corrupt a `files` field: it becomes one bogus path at index time.
      args.push(name, value);
    }
  };

  switch (params.action) {
    case "search":
      if (params.query !== undefined) args.push(params.query);
      flag("--project", params.project);
      flag("--topic", params.topic);
      break;
    case "load":
      flag("--date", params.date);
      flag("--log-days", params.logDays);
      flag("--log-from", params.logFrom);
      flag("--log-to", params.logTo);
      flag("--log-query", params.logQuery);
      flag("--doc", params.doc);
      flag("--doc-type", params.docType);
      repeated("--doc-tag", params.docTags);
      flag("--project", params.project);
      flag("--topic", params.topic);
      flag("--doc-query", params.docQuery);
      break;

    case "write-log":
      flag("--date", params.date);
      flag("--tag", params.tag);
      flag("--text", params.text);
      flag("--level", params.level);
      flag("--confidence", params.confidence);
      flag("--source", params.source);
      repeated("--files", params.files);
      flag("--project", params.project);
      flag("--topic", params.topic);
      break;

    case "write-memory":
      flag("--date", params.date);
      flag("--tag", params.tag);
      flag("--text", params.text);
      break;

    case "write-preference":
      flag("--date", params.date);
      flag("--text", params.text);
      flag("--scope", params.scope);
      break;
    case "upsert-doc":
      flag("--doc", params.doc);
      flag("--text", params.text);
      flag("--title", params.docTitle);
      flag("--doc-type", params.docType);
      repeated("--doc-tag", params.docTags);
      flag("--project", params.project);
      flag("--summary", params.summary);
      break;

    case "maintain":
      flag("--distill", params.distill);
      flag("--promote", params.promote);
      break;

    case "stats":
    case "status":
      break;

    default:
      break;
  }

  args.push("--json");

  // Injected last, and only when the model did not supply them: an explicit
  // value from the model always wins.
  if (defaults !== undefined) {
    if (defaults.config !== null && !args.includes("--config")) {
      args.push("--config", defaults.config);
    }
    if (NEEDS_DATE.has(params.action) && params.date === undefined) {
      args.push("--date", defaults.date);
    }
  }

  // An explicit `config` param beats the resolved default.
  if (params.config !== undefined && !args.includes("--config")) {
    args.push("--config", params.config);
  }

  return [params.action, ...args];
}

/** A compact one-line echo for the tool-call header. */
export function summarizeCall(params: UmemParams): string {
  const parts: string[] = [params.action];
  if (params.action === "search" && params.query !== undefined) {
    parts.push(quote(params.query));
  }
  if (params.action === "write-log" && params.tag !== undefined) {
    parts.push(params.tag);
  }
  if (params.action === "upsert-doc" && params.doc !== undefined) {
    parts.push(quote(params.doc));
  }
  if (params.action === "maintain" && params.promote !== undefined) {
    parts.push(`--promote ${quote(params.promote)}`);
  }
  if (params.action === "maintain" && params.distill === true) {
    parts.push("--distill");
  }
  if (params.project !== undefined) parts.push(`--project ${params.project}`);
  if (params.text !== undefined && params.action !== "search") parts.push("--text …");
  return parts.join(" ");
}

function quote(value: string): string {
  return /[\s"']/.test(value) ? JSON.stringify(value) : value;
}

/** Split a slash-command string into argv tokens, honouring quotes. */
export function splitTokens(input: string): string[] {
  const tokens: string[] = [];
  const pattern = /"([^"\\]*(?:\\.[^"\\]*)*)"|'([^']*)'|(\S+)/g;
  for (const match of input.matchAll(pattern)) {
    tokens.push(match[1] ?? match[2] ?? match[3] ?? "");
  }
  return tokens;
}
