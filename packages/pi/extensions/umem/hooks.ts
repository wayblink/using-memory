/**
 * hooks.ts — the Pi port of the memory hooks.
 *
 * The Codex and Claude adapters share `scripts/hooks/memory_hook_common.py` and
 * are driven by a host that fires SessionStart / UserPromptSubmit / PostToolUse
 * / Stop. Pi fires different events with different payloads, and one of them has
 * no equivalent at all, so the mapping is:
 *
 * | Codex / Claude      | Pi                       | Fidelity |
 * |---------------------|--------------------------|----------|
 * | SessionStart        | `session_start`          | full     |
 * | UserPromptSubmit    | `before_agent_start`     | full     |
 * | PostToolUse         | `tool_execution_end`     | full     |
 * | Stop (block)        | `agent_before_settle`    | partial — see below |
 * | PreCompact          | `session_before_compact` | re-inject on loss |
 *
 * The Stop gate is the interesting one. Pi has no hook that can refuse to stop:
 * the closest thing is appending a `custom_message` entry and returning
 * `continue: true`, which asks for one more model request. That is strictly
 * weaker than a blocking Stop hook and strictly more expensive, which is why the
 * threshold is looser here (30 turns) and the gate is latched per turn.
 *
 * The Python side still owns the *copy* (`memory_protocol_reminder` and
 * `stop_gate_reason` take a `host`), so the words the model reads are the same
 * ones the other hosts get, phrased for a tool call instead of a shell command.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

import type { UmemPiConfig } from "./config.js";
import { UMEM_CUSTOM_TYPE, countHumanTurns, isSyntheticUserText, shouldFireGate } from "./turns.js";
import { messageText } from "./turns.js";

/** Per-session state the hooks accumulate. */
interface SessionState {
  sessionId: string;
  /** Human turns at the last time we recorded a write. */
  lastSaveTurn: number;
  /** The most recent turn index we computed, so `agent_before_settle` can see a delta. */
  turns: number;
  /** Did the current turn call a `umem` write verb? */
  memoryWritten: boolean;
  /** One-line summaries of substantial operations in this turn. */
  importantEvents: string[];
  /** Did the user's prompt for this turn mention memory? */
  promptMentionsMemory: boolean;
  /** The latch: turn index at which the gate last fired, or null. */
  gateFiredAtTurn: number | null;
  /** Turn index at which a snapshot was last injected (start or post-compact). */
  injectedAtTurn: number | null;
}

const MEMORY_PROMPT_RE =
  /(memory|remember|forget|preference|prior context|previous work|continue|resume|project history|saved decisions|log|operation|commit|push|build|test|deploy|hook)/i;

const IMPORTANT_OPERATION_RE =
  /(apply_patch|write|edit|git\s+(commit|push|merge|rebase|cherry-pick|tag)|npm\s+(test|run|build)|pnpm\s+(test|run|build)|pytest|cargo\s+test|go\s+test|deploy|release|restart|systemctl|docker|kubectl|error|failed|failure|fix|debug|hook)/i;

/** Tool names whose calls count as operation evidence. */
const IMPORTANT_TOOLS = new Set([
  "write",
  "edit",
  "bash",
  "powershell",
  "apply_patch",
]);

function newState(sessionId: string): SessionState {
  return {
    sessionId,
    lastSaveTurn: 0,
    turns: 0,
    memoryWritten: false,
    importantEvents: [],
    promptMentionsMemory: false,
    gateFiredAtTurn: null,
    injectedAtTurn: null,
  };
}

/** Extract a one-line hint from a tool call's input for the event log. */
export function summarizeToolCall(toolName: string, input: unknown): string | null {
  if (typeof input !== "object" || input === null) return null;
  const record = input as Record<string, unknown>;
  const hint =
    (typeof record["command"] === "string" && record["command"]) ||
    (typeof record["file_path"] === "string" && record["file_path"]) ||
    (typeof record["path"] === "string" && record["path"]) ||
    (typeof record["pattern"] === "string" && record["pattern"]) ||
    "";
  const clipped = String(hint).replace(/\s+/g, " ").trim().slice(0, 120);
  return clipped === "" ? toolName : `${toolName}: ${clipped}`;
}

export interface HookDeps {
  readonly config: UmemPiConfig;
  /** Run `python3 memory_tool.py <argv>` and collect stdout. */
  readonly runCli: (argv: readonly string[]) => Promise<string>;
  /** The reminder text, host-aware (produced by the Python layer). */
  readonly reminder: string;
  /** The gate reason, host-aware. */
  readonly gateReason: (events: readonly string[]) => string;
  /** Compact snapshot to inject at session start, or null. */
  readonly sessionSnapshot: () => Promise<string | null>;
  /** Best-effort stats bump; failures must not affect the session. */
  readonly bumpStats: (deltas: Record<string, number>) => void;
}

/**
 * Register the memory hooks.
 *
 * Every handler is written to fail soft: memory is a side view, and a hook that
 * throws must not cost the user their session. Pi reports handler errors and
 * continues, but a `tool_call`/`agent_before_settle` handler that throws can
 * change the run's outcome, so the try/catch is deliberate rather than
 * defensive habit.
 */
export function registerMemoryHooks(
  pi: ExtensionAPI,
  deps: HookDeps,
): (ctx: ExtensionContext) => void {
  let state: SessionState | null = null;

  // `agent_before_settle` carries no context of its own, so the most recent one
  // is remembered here. A closure rather than module state keeps two concurrent
  // sessions from pointing at each other's branch.
  let currentCtx: ExtensionContext | null = null;

  const ensureState = (ctx: ExtensionContext): SessionState => {
    if (state === null) state = newState(String(ctx.sessionManager.getSessionId?.() ?? "unknown"));
    return state;
  };

  const recount = (ctx: ExtensionContext): number => {
    try {
      return countHumanTurns(ctx.sessionManager.getBranch() as never);
    } catch {
      return 0;
    }
  };

  /* ------------------------------ session_start ------------------------------ */

  const onSessionStart = async (
    event: { reason: string },
    ctx: ExtensionContext,
  ): Promise<void> => {
    try {
      state = newState(String(ctx.sessionManager.getSessionId?.() ?? "unknown"));
      // A resumed or forked session already has turns on its branch; start the
      // counter where the branch says it is, or the gate fires immediately.
      state.turns = recount(ctx);
      state.lastSaveTurn = state.turns;
      deps.bumpStats({ sessions: 1 });

      if (event.reason === "reload") {
        // The runtime was replaced; state was rebuilt above. No injection: the
        // conversation already carries whatever the first start provided.
        return;
      }

      const snapshot = await deps.sessionSnapshot();
      const content = snapshot === null ? deps.reminder : `${deps.reminder}\n\n---\n\n${snapshot}`;
      pi.sendMessage(
        { customType: UMEM_CUSTOM_TYPE, content, display: false },
        { deliverAs: "nextTurn" },
      );
      state.injectedAtTurn = state.turns;
    } catch {
      // Memory injection is best-effort. A missing config, a broken CLI or a
      // malformed snapshot must not stop the session from starting.
    }
  };

  /* ---------------------------- before_agent_start --------------------------- */

  const onBeforeAgentStart = (event: { prompt: string }): void => {
    try {
      if (state === null) return;
      // A new user turn: reset the per-turn flags, keep the lifetime counters.
      state.memoryWritten = false;
      state.importantEvents = [];
      state.promptMentionsMemory = MEMORY_PROMPT_RE.test(event.prompt);
    } catch {
      // ignore
    }
  };

  /* ---------------------------- tool_execution_end --------------------------- */

  const onToolExecutionEnd = (event: {
    toolName: string;
    isError: boolean;
  }): void => {
    try {
      if (state === null) return;
      if (event.toolName === UMEM_CUSTOM_TYPE) {
        // Reaching the *write* path is decided in `tool_call` (where the input
        // is visible); here we only note that a memory call happened at all.
        return;
      }
      if (!IMPORTANT_TOOLS.has(event.toolName)) return;
      const summary = `${event.toolName}${event.isError ? " (failed)" : ""}`;
      if (!state.importantEvents.includes(summary)) {
        state.importantEvents.push(summary);
        state.importantEvents = state.importantEvents.slice(-20);
      }
    } catch {
      // ignore
    }
  };

  /* -------------------------------- tool_call -------------------------------- */

  const onToolCall = (event: { toolName: string; input: unknown }): void => {
    try {
      if (state === null) return;
      if (event.toolName !== UMEM_CUSTOM_TYPE) return;
      const input = event.input;
      if (typeof input !== "object" || input === null) return;
      const action = (input as { action?: unknown }).action;
      if (typeof action !== "string") return;
      // Only a write verb satisfies the gate. A `load` is a read and must not
      // let the turn off the hook.
      if (action.startsWith("write-") || action === "upsert-doc") {
        state.memoryWritten = true;
      }
    } catch {
      // ignore
    }
  };

  /* ---------------------------- agent_before_settle -------------------------- */

  const onAgentBeforeSettle = async (): Promise<
    { entries: unknown[]; continue: boolean } | undefined
  > => {
    try {
      if (state === null) return undefined;
      if (deps.config.gate === "off") return undefined;

      // The turn count is only meaningful once the branch has settled.
      const ctx = currentCtx;
      if (ctx === null) return undefined;
      const turns = recount(ctx);
      state.turns = turns;

      const substantial =
        state.importantEvents.length > 0 ||
        state.memoryWritten ||
        state.promptMentionsMemory;

      const decision = shouldFireGate({
        gate: deps.config.gate,
        substantial,
        delta: Math.max(0, turns - state.lastSaveTurn),
        memoryWritten: state.memoryWritten,
        firedThisTurn: state.gateFiredAtTurn === turns,
        threshold: deps.config.detailTurnInterval,
      });

      if (!decision.fire) {
        // Nothing to gate: if the model did write, advance the checkpoint so the
        // next delta is measured from here.
        if (state.memoryWritten) state.lastSaveTurn = turns;
        return undefined;
      }

      // Latch before returning. If the injection throws below, the latch still
      // holds and the gate cannot loop.
      state.gateFiredAtTurn = turns;
      deps.bumpStats({ stop_blocks: 1 });

      return {
        entries: [
          {
            type: "custom_message",
            customType: UMEM_CUSTOM_TYPE,
            content: deps.gateReason(state.importantEvents),
            display: true,
          },
        ],
        continue: true,
      };
    } catch {
      // A gate that throws must look like a gate that did not fire.
      return undefined;
    }
  };

  /* --------------------------------- wiring ---------------------------------- */

  const withCtx =
    <T>(handler: (event: T, ctx: ExtensionContext) => void | Promise<void>) =>
    async (event: T, ctx: ExtensionContext): Promise<void> => {
      currentCtx = ctx;
      await handler(event, ctx);
    };

  /* ---------------------------- session_before_compact ---------------------------- */

  /**
   * Re-inject the rules after a compaction that actually drops messages.
   *
   * Session start is the only time the rules were delivered, so a long session
   * used to depend on the compaction summary remembering them — which is not a
   * guarantee, it is a hope. Measured on an 8-day session: one injection at
   * 02:38, compaction one minute later, then two more compactions, no further
   * injection. The model then follows rules it has not been shown.
   *
   * The event carries `preparation.messagesToSummarize`, so "was anything lost"
   * is a fact rather than a guess: an empty list means the compaction had
   * nothing to drop and re-injecting would be pure token cost.
   *
   * This does NOT customize or block compaction — it returns `undefined` so Pi
   * runs its normal summarization. An extension has no business standing in
   * front of the compaction pipeline.
   */
  const onBeforeCompact = async (event: {
    preparation?: { messagesToSummarize?: unknown[] };
  }): Promise<undefined> => {
    try {
      const summarizing = event.preparation?.messagesToSummarize;
      if (!Array.isArray(summarizing) || summarizing.length === 0) return undefined;
      if (state === null) return undefined;
      // Count from the branch rather than trusting `state.turns`: the counter is
      // only refreshed at session start and at settle, so mid-turn it lags and
      // the de-dup below would compare against a stale number.
      const ctx = currentCtx;
      const turns = ctx === null ? state.turns : recount(ctx);
      state.turns = turns;
      // One injection per turn: `session_start` may have just delivered the same
      // text, and a compaction can fire more than once across a long turn.
      if (state.injectedAtTurn === turns) return undefined;

      const snapshot = await deps.sessionSnapshot();
      if (snapshot === null) return undefined;
      pi.sendMessage(
        {
          customType: UMEM_CUSTOM_TYPE,
          content: `${deps.reminder}\n\n---\n\n${snapshot}`,
          display: false,
        },
        { deliverAs: "nextTurn" },
      );
      state.injectedAtTurn = turns;
    } catch {
      // A failed re-injection must not disturb the compaction that is in flight.
    }
    return undefined;
  };

  pi.on("session_start", withCtx(onSessionStart));
  pi.on("before_agent_start", withCtx(onBeforeAgentStart));
  pi.on("tool_execution_end", withCtx(onToolExecutionEnd));
  pi.on("tool_call", withCtx(onToolCall));
  pi.on("agent_before_settle", (async () => onAgentBeforeSettle()) as never);

  // Compaction itself is left alone on purpose: the hook hosts used to *block*
  // compact to force a memory flush, it hung the compaction pipeline, and that
  // was removed there too. Re-injecting after loss is a different thing from
  // standing in front of it.
  pi.on("session_before_compact", onBeforeCompact as never);

  return (ctx: ExtensionContext): void => {
    currentCtx = ctx;
  };
}

/** Re-exported so tests can assert the synthetic-text filter without a runtime. */
export { isSyntheticUserText, messageText };
