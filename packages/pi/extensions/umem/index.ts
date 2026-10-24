/**
 * umem — Pi extension for using-memory.
 *
 * The extension is deliberately thin: every read and write goes through
 * `scripts/memory_tool.py`, the same CLI the `umem` wrapper, the Codex/Claude
 * hooks and the web app use. There is no second copy of the memory logic here —
 * only argument plumbing, the Pi-specific glue (which event maps to which hook,
 * see `hooks.ts`), and the rendering Pi needs to make a write feel like a
 * first-class verb instead of a bash echo.
 *
 * Why a native tool rather than "the model can just run bash": Pi colours and
 * renders tool calls, and a tool carries `promptSnippet`/`promptGuidelines` into
 * the system prompt. Those guidelines are where the log-vs-memory-vs-preference
 * routing rules live, and the model needs them *before* it decides to load the
 * skill — see guidance.ts.
 */

import { existsSync } from "node:fs";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { Text } from "@earendil-works/pi-tui";
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";

import {
  ACTIONS,
  LOG_TAGS,
  MEMORY_TAGS,
  buildArgs,
  splitTokens,
  summarizeCall,
  type ArgDefaults,
  type UmemParams,
} from "./args.js";
import { loadPiConfig, resolveConfigPath, type UmemPiConfig } from "./config.js";
import { resolveGuidance } from "./guidance.js";
import { registerMemoryHooks } from "./hooks.js";
import { pythonExecutable, resolveMemoryTool, resolveMemoryWeb, resolveRepoName } from "./resolve.js";
import {
  createDetachedWebSpawner,
  launchWebServer,
  parseWebCommand,
  type WebServer,
} from "./web.js";

const TOOL_NAME = "umem";

/** Local calendar date as `YYYY-MM-DD`. */
function today(): string {
  const now = new Date();
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** The host copy the Python layer emits for `host=pi`. */
interface HookCopy {
  reminder: string;
  gateReason: (events: readonly string[]) => string;
}

/**
 * Re-exported from snapshot.ts.
 *
 * It lives in its own module because index.ts imports the Pi runtime packages,
 * so anything defined here cannot be loaded by a plain `node --test` run. The
 * renderer decides what the model reads about its rules, and it had no
 * coverage at all while it lived here.
 */
import { renderSnapshot } from "./snapshot.js";

export { renderSnapshot };

/**
 * Fetch the host copy from the Python layer.
 *
 * `pi.exec` is async and the factory cannot await a slow CLI, so the strings are
 * loaded lazily on first use and cached. The fallbacks below are deliberately
 * short and still correct: if `hook-context` fails (an old installed CLI), the
 * session gets usable instructions instead of nothing.
 */
export async function loadHookCopy(
  run: (argv: readonly string[], signal: undefined) => Promise<{ code: number; output: string }>,
): Promise<HookCopy> {
  const fallbackInstruction =
    "Before stopping, call the `umem` tool with action=write-log to record this turn";
  const fallback: HookCopy = {
    reminder:
      "using-memory: recall saved preferences and decisions when they could change the answer, and record this turn's concrete operations with the `umem` tool (action=write-log) when they should survive the session.",
    gateReason: (events) => renderGateReason(fallbackInstruction, events),
  };

  try {
    const { code, output } = await run(["hook-context", "--host", "pi", "--json"], undefined);
    if (code !== 0) return fallback;
    const parsed = JSON.parse(output) as { reminder?: unknown; gate_instruction?: unknown };
    const reminder = typeof parsed.reminder === "string" ? parsed.reminder : fallback.reminder;
    const instruction =
      typeof parsed.gate_instruction === "string" ? parsed.gate_instruction : fallbackInstruction;
    return { reminder, gateReason: (events) => renderGateReason(instruction, events) };
  } catch {
    return fallback;
  }
}

/**
 * Compose the gate reason from the CLI's own wording plus this turn's events.
 *
 * Done here rather than by re-calling the CLI because a gate decision happens
 * inside a synchronous-ish boundary and must not wait on a subprocess. The
 * sentence is the CLI's; only the event list is local.
 */
export function renderGateReason(instruction: string, events: readonly string[]): string {
  if (events.length === 0) {
    return `${instruction}'s concrete operations, result, identifiers, verification, and unresolved risks.`;
  }
  const kinds: string[] = [];
  for (const event of events) {
    const kind = event.split(":")[0]?.trim() ?? event.slice(0, 20).trim();
    if (kind !== "" && !kinds.includes(kind)) kinds.push(kind);
    if (kinds.length >= 5) break;
  }
  const label = kinds.length > 0 ? kinds.join(", ") : "operation";
  return (
    `${instruction}: ${events.length} important event(s) [${label}]. ` +
    "Include affected files, result, identifiers (commit/PR/deploy), verification, and unresolved risks."
  );
}

/** Cap rendered output so one big `load` cannot flood the transcript. */
function truncateOutput(text: string, maxLines = 30): { text: string; truncated: boolean } {
  const lines = text.split("\n");
  if (lines.length <= maxLines) return { text, truncated: false };
  return { text: lines.slice(0, maxLines).join("\n"), truncated: true };
}

function extractText(content: readonly { type: string; text?: unknown }[]): string {
  const parts: string[] = [];
  for (const part of content) {
    if (part.type === "text" && typeof part.text === "string") parts.push(part.text);
  }
  return parts.join("\n");
}

const HELP = [
  "umem — persisted memory for this session and the next",
  "/umem                      status (lifetime dashboard)",
  "/umem load [--log-days N]  read the snapshot",
  "/umem search <query>       full-text search over logs, docs, MEMORY",
  "/umem write-log --tag T --text ...",
  "/umem stats | status | maintain [--distill]",
  "/umem web [--port N] [--host H] [--open]   start the web UI (detached)",
  "/umem web stop             stop the UI this session started",
  "/umem setup                prints how to run the interactive setup",
  "/umem help                 this text",
].join("\n");

export default async function umemExtension(pi: ExtensionAPI): Promise<void> {
  const config: UmemPiConfig = loadPiConfig();
  const guidance = resolveGuidance();
  const toolPath = resolveMemoryTool(config.memoryToolPath);
  const configPath = resolveConfigPath();
  const python = pythonExecutable();

  // The write verbs require `--config` and `--date` in argparse, so the
  // extension supplies both rather than making the model remember flags that
  // have exactly one right answer here. `date` is recomputed per call: a long
  // session can cross midnight, and a log entry filed under yesterday is a
  // bug nobody notices for a week.
  const argDefaults = (): ArgDefaults => ({ config: configPath, date: today() });

  /** Run the CLI and return its exit code plus combined output. */
  const run = async (
    argv: readonly string[],
    signal: AbortSignal | undefined,
  ): Promise<{ code: number; output: string }> => {
    const result = await pi.exec(
      python,
      [toolPath, ...argv],
      signal === undefined ? undefined : { signal },
    );
    const output = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
    return { code: result.code, output: output || "(no output)" };
  };

  const missingToolMessage = `umem: memory_tool.py not found at ${toolPath}. Install with \`scripts/install.sh\` (or set \`pi.memory_tool_path\` in config.yaml).`;

  /* -------------------------------- web ---------------------------------- */

  // See web.ts for why this is detached and not awaited.
  const spawnWeb = createDetachedWebSpawner();
  let webServer: WebServer | null = null;

  const handleWebCommand = async (
    tokens: readonly string[],
    ctx: ExtensionCommandContext,
  ): Promise<void> => {
    // A server started from a non-interactive run (json/print) has no session
    // to own its lifetime: `session_shutdown` fires immediately and the URL is
    // printed into a machine-readable stream nobody reads. Refuse rather than
    // leak a process.
    if (ctx.mode !== "tui" && ctx.mode !== "rpc") {
      ctx.ui.notify("umem web needs an interactive session (Pi TUI or RPC)", "warning");
      return;
    }

    const command = parseWebCommand(tokens);
    if (command.error !== null) {
      ctx.ui.notify(command.error, "warning");
      return;
    }

    if (command.action === "stop") {
      const server = webServer;
      webServer = null;
      if (server === null || server.exited) {
        ctx.ui.notify("umem web: no server started by this session", "info");
        return;
      }
      await server.stop();
      ctx.ui.notify(`umem web: stopped ${server.url}`, "info");
      return;
    }

    if (webServer !== null && !webServer.exited) {
      ctx.ui.notify(`umem web: already running at ${webServer.url}`, "info");
      return;
    }

    const binary = resolveMemoryWeb(config.memoryWebPath);
    if (binary === null) {
      ctx.ui.notify(
        "umem web: the `memory-web` command was not found. Install it with `pip install -e web/` inside the skill directory, or set `pi.memory_web_path` in config.yaml.",
        "error",
      );
      return;
    }

    const launch = await launchWebServer({ command: binary, argv: command.args, spawn: spawnWeb });
    if (!launch.ok) {
      // Code 0 without a URL is a deliberate non-server run (--help): its own
      // text is the answer, not a warning about a failed launch.
      ctx.ui.notify(`umem web: ${launch.error}`, launch.code === 0 ? "info" : "warning");
      return;
    }
    webServer = launch.server;
    ctx.ui.notify(`umem web: ${launch.server.url} (stop with /umem web stop)`, "info");
  };

  /* -------------------------------- setup -------------------------------- */

  /**
   * `umem setup` is interactive — it prompts for memory path, git remote,
   * namespace and machine id over stdin. Pi's `exec` has no TTY, so running it
   * here would hang on the first prompt. Say where to run it instead of
   * pretending we can.
   */
  const handleSetup = (ctx: ExtensionCommandContext): void => {
    ctx.ui.notify(
      [
        "umem setup is interactive and needs a terminal. Run it in your shell:",
        `  python3 ${toolPath} setup`,
        "It will ask for the memory path, an optional git remote, the namespace and a machine id.",
      ].join("\n"),
      "info",
    );
  };

  /* ------------------------------ commands ------------------------------- */

  const runVerb = async (
    argv: readonly string[],
    ctx: ExtensionCommandContext,
  ): Promise<void> => {
    try {
      const { code, output } = await run(argv, ctx.signal);
      ctx.ui.notify(output, code === 0 ? "info" : "error");
    } catch (error) {
      ctx.ui.notify(error instanceof Error ? error.message : String(error), "error");
    }
  };

  pi.registerCommand(TOOL_NAME, {
    description:
      "using-memory — status (no args) | load | search | write-log | write-memory | write-preference | upsert-doc | maintain | stats | web | help",
    handler: async (input, ctx) => {
      const tokens = splitTokens(input.trim());
      const verb = tokens[0]?.toLowerCase();

      if (verb === "help") {
        ctx.ui.notify(HELP, "info");
        return;
      }
      if (verb === "web") {
        await handleWebCommand(tokens.slice(1), ctx);
        return;
      }
      if (verb === "setup") {
        handleSetup(ctx);
        return;
      }
      // `/umem` alone is the lifetime dashboard: it is the one view that is
      // useful without the caller knowing any flags.
      await runVerb(tokens.length > 0 ? tokens : ["status"], ctx);
    },
  });

  /* -------------------------------- tool --------------------------------- */

  pi.registerTool({
    name: TOOL_NAME,
    label: "Memory",
    description: [
      "Persisted memory for this machine: user preferences, durable facts and decisions, an operation",
      "log, and indexed docs. Use `load` before answering anything that turns on prior context, and",
      "`write-log`/`write-memory`/`write-preference` to record what should survive the session.",
      "Do not load memory every turn; route each write by kind (see the guidelines).",
      "Log bodies are structured Markdown (## title, Context, Operations, Result, Decisions).",
    ].join(" "),
    promptSnippet: guidance.promptSnippet,
    promptGuidelines: [...guidance.promptGuidelines],
    parameters: Type.Object({
      action: StringEnum(ACTIONS),
      query: Type.Optional(Type.String({ description: "search: the query string" })),
      text: Type.Optional(
        Type.String({
          description:
            "The entry body. For write-log this must be structured Markdown: '## <title>', then Context, Operations, Result/Verification, Decisions/Open. 800–3000 chars for level=detail, 300–800 for summary.",
        }),
      ),
      tag: Type.Optional(
        Type.String({
          description: `write-log tag — one of: ${LOG_TAGS.join(", ")}. write-memory accepts only: ${MEMORY_TAGS.join(", ")}.`,
        }),
      ),
      level: Type.Optional(
        StringEnum(["detail", "summary"] as const, {
          description:
            "detail for a full operation record, summary for key results and milestones (default: detail)",
        }),
      ),
      date: Type.Optional(Type.String({ description: "YYYY-MM-DD; defaults to today" })),
      files: Type.Optional(
        Type.Array(Type.String(), {
          description:
            "Related file paths, one entry per file. Absolute paths preferred. Never join several paths into one string.",
        }),
      ),
      project: Type.Optional(Type.String({ description: "Project axis slug, e.g. using-memory" })),
      scope: Type.Optional(
        Type.String({
          description:
            "write-preference only: 'global' (default) writes SPEC.md and applies to every project; a repo name writes spec/<repo>.md and applies only inside that repository; 'auto' derives the current git repo.",
        }),
      ),
      topic: Type.Optional(Type.String({ description: "Topic axis slug, e.g. hooks" })),
      confidence: Type.Optional(
        Type.Integer({ minimum: 1, maximum: 10, description: "Optional 1-10 confidence" }),
      ),
      source: Type.Optional(
        Type.String({ description: "Origin of the entry, e.g. user, auto, observed" }),
      ),
      logDays: Type.Optional(
        Type.Integer({ minimum: 1, description: "load: how many days of log to read back" }),
      ),
      logFrom: Type.Optional(Type.String({ description: "load: log start date, YYYY-MM-DD" })),
      logTo: Type.Optional(Type.String({ description: "load: log end date, YYYY-MM-DD" })),
      logQuery: Type.Optional(Type.String({ description: "load: filter log entries by text" })),
      doc: Type.Optional(Type.String({ description: "Doc slug for load/upsert-doc" })),
      docType: Type.Optional(
        Type.String({
          description:
            "wiki | lesson | troubleshooting | decision-record | runbook | SOP | project (default wiki)",
        }),
      ),
      docTags: Type.Optional(
        Type.Array(Type.String(), { description: "Doc tags, one entry per tag" }),
      ),
      docQuery: Type.Optional(Type.String({ description: "load: filter docs by query" })),
      docTitle: Type.Optional(Type.String({ description: "upsert-doc: title (defaults to first H1)" })),
      summary: Type.Optional(Type.String({ description: "upsert-doc: one-line summary" })),
      distill: Type.Optional(
        Type.Boolean({ description: "maintain: list candidate buckets for distillation" }),
      ),
      promote: Type.Optional(
        Type.String({ description: "maintain: render the promote prompt for TOPIC[/FAMILY]" }),
      ),
      dest: Type.Optional(Type.String({ description: "export: destination file" })),
    }),

    async execute(_toolCallId, params, signal) {
      const typed = params as UmemParams;
      const { code, output } = await run(buildArgs(typed, argDefaults()), signal);
      return {
        isError: code !== 0,
        content: [{ type: "text", text: output }],
        details: { action: typed.action, code },
      };
    },

    renderCall(args, theme) {
      return new Text(
        `${theme.fg("toolTitle", theme.bold("umem"))} ${theme.fg("accent", summarizeCall(args as UmemParams))}`,
        0,
        0,
      );
    },

    renderResult(result, _options, theme) {
      const { text, truncated } = truncateOutput(extractText(result.content));
      const suffix = truncated ? theme.fg("muted", "\n… (truncated)") : "";
      return new Text(theme.fg("toolOutput", text) + suffix, 0, 0);
    },
  });

  /* ------------------------------ lifecycle ------------------------------ */

  // Registered outside the hook block: `/umem web` is independent of whether the
  // memory hooks are enabled.
  pi.on("session_shutdown", async () => {
    const server = webServer;
    webServer = null;
    if (server === null) return;
    try {
      await server.stop();
    } catch {
      // Shutting down: a server that will not stop must not hold the exit up.
    }
  });

  // A missing CLI is a setup problem. Say it once at load: every call would
  // otherwise fail with the same ENOENT and bury the cause in a stack.
  if (!existsSync(toolPath)) {
    process.stderr.write(`[umem] ${missingToolMessage}\n`);
  }

  /* -------------------------------- hooks -------------------------------- */

  // The Python layer owns the copy, so the reminder and gate reason are asked
  // for once per process with `host=pi`. If the CLI is missing there is nothing
  // to ask, and the hooks stay unregistered — an extension that cannot reach
  // memory should be quiet, not noisy.
  if (existsSync(toolPath)) {
    const copy = await loadHookCopy(run);
    registerMemoryHooks(pi, {
      config,
      runCli: async (argv) => {
        const { output } = await run(argv, undefined);
        return output;
      },
      reminder: copy.reminder,
      gateReason: copy.gateReason,
      sessionSnapshot: async () => {
        if (!config.injectPreferences) return null;
        const argv = config.briefSnapshot ? ["load", "--json", "--brief"] : ["load", "--json"];
        const { code, output } = await run(argv, undefined);
        if (code !== 0) return null;
        // The repo name narrows the document catalogue; see snapshot.ts.
        return renderSnapshot(output, resolveRepoName());
      },
      bumpStats: () => {
        // Stats are maintained by the Python side; the extension has no
        // business writing the accounting file directly.
      },
    });
  } else {
    process.stderr.write(
      "[umem] memory hooks not registered: the CLI is missing, so there is nothing to inject from.\n",
    );
  }
}
