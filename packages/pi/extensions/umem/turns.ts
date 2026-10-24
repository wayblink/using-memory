/**
 * turns.ts — counting human turns from a Pi branch.
 *
 * The Codex/Claude hooks count user turns by scanning a transcript JSONL and
 * filtering out tool-result lists and synthetic wrapper content. Pi has no
 * equivalent file to scan: the session is a tree, and `getBranch()` gives the
 * entries leading to the current leaf — which is *better*, because it is
 * branch-aware. Undoing to an earlier point and taking a different path gives a
 * count for that path, not for the abandoned history.
 *
 * Two filters matter and both are load-bearing:
 *
 * 1. Synthetic user messages. Pi and other extensions inject text that arrives
 *    as a user-role message (`<system-reminder>`, `<command-message>`, slash
 *    command expansions). Counting those as human turns would fire the gate on
 *    a schedule nobody asked for.
 * 2. Our own injected messages. The gate itself appends a `custom_message`
 *    entry; counting it would make the gate feed its own counter.
 *
 * Pure and Pi-free so the tricky part is testable without a runtime.
 */

/** The shape of a session entry this module reads. */
export interface TurnEntry {
  readonly type: string;
  readonly message?: { readonly role?: string; readonly content?: unknown };
  readonly customType?: string;
}

/** Wrapper prefixes that mean "not typed by the human". */
const SYNTHETIC_PREFIXES = [
  "<system-reminder>",
  "<command-message>",
  "<command-name>",
  "<local-command-stdout>",
  "<bash-input>",
  "<user-prompt-submit-hook>",
  "Stop hook feedback:",
];

/** Our own injected content is tagged with this customType. */
export const UMEM_CUSTOM_TYPE = "umem";

/** Plain text out of a message's content, which may be a string or blocks. */
export function messageText(message: TurnEntry["message"]): string {
  const content = message?.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const block of content) {
    if (
      typeof block === "object" &&
      block !== null &&
      (block as { type?: unknown }).type === "text" &&
      typeof (block as { text?: unknown }).text === "string"
    ) {
      parts.push((block as { text: string }).text);
    }
  }
  return parts.join("\n");
}

export function isSyntheticUserText(text: string): boolean {
  const trimmed = text.trimStart();
  if (trimmed === "") return true;
  return SYNTHETIC_PREFIXES.some((prefix) => trimmed.startsWith(prefix));
}

/**
 * Count human turns on a branch.
 *
 * A "turn" is one user-role message that a person actually typed. Everything
 * else — assistant messages, tool results, our injected messages, synthetic
 * wrappers — is skipped.
 */
export function countHumanTurns(entries: readonly TurnEntry[]): number {
  let count = 0;
  for (const entry of entries) {
    // A custom_message we injected: never a human turn.
    if (entry.type === "custom_message" && entry.customType === UMEM_CUSTOM_TYPE) continue;
    if (entry.type !== "message") continue;
    if (entry.message?.role !== "user") continue;
    if (isSyntheticUserText(messageText(entry.message))) continue;
    count += 1;
  }
  return count;
}

/** What the gate decided, and why — the "why" is what tests assert on. */
export interface GateDecision {
  readonly fire: boolean;
  readonly reason:
    | "fired"
    | "disabled"
    | "not-substantial"
    | "below-threshold"
    | "already-written"
    | "already-fired-this-turn";
}

export interface GateInputs {
  /** `pi.gate` — `off` never fires. */
  readonly gate: "message" | "off";
  /** Did this turn touch anything worth recording? */
  readonly substantial: boolean;
  /** Human turns since the last recorded write. */
  readonly delta: number;
  /** The model already called a `umem` write tool this turn. */
  readonly memoryWritten: boolean;
  /** The latch: has the gate already fired for this turn? */
  readonly firedThisTurn: boolean;
  readonly threshold: number;
}

/**
 * Decide whether to inject the write gate.
 *
 * Order matters: the latch is checked last but only because every earlier
 * condition is cheaper to evaluate and strictly narrower. What must never happen
 * is `fire` with `firedThisTurn` true — Pi answers a `continue: true` with
 * another model request and then settles again, so an unlatched gate loops until
 * the session is killed.
 */
export function shouldFireGate(inputs: GateInputs): GateDecision {
  if (inputs.gate === "off") return { fire: false, reason: "disabled" };
  if (!inputs.substantial) return { fire: false, reason: "not-substantial" };
  if (inputs.memoryWritten) return { fire: false, reason: "already-written" };
  if (inputs.firedThisTurn) return { fire: false, reason: "already-fired-this-turn" };
  if (inputs.delta < inputs.threshold) return { fire: false, reason: "below-threshold" };
  return { fire: true, reason: "fired" };
}

/**
 * Which tool calls count as "the model wrote memory".
 *
 * On Pi this is a tool identity, not a regex over text: the write verbs are
 * `umem` calls with a `write-*` action. Reading the action out of the call's
 * input is what distinguishes a `write-log` from a `load` — a bare tool name
 * would treat every read as a write and silently disable the gate.
 */
export const WRITE_ACTIONS = new Set([
  "write-log",
  "write-memory",
  "write-preference",
  "upsert-doc",
]);

export function isMemoryWrite(toolName: string, input: unknown): boolean {
  if (toolName !== UMEM_CUSTOM_TYPE) return false;
  if (typeof input !== "object" || input === null) return false;
  const action = (input as { action?: unknown }).action;
  return typeof action === "string" && WRITE_ACTIONS.has(action);
}
