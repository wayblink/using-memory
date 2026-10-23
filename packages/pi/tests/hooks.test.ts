/**
 * End-to-end hook wiring against a fake Pi.
 *
 * The gate's failure mode is a loop: `continue: true` makes Pi run one more
 * model request, which settles again. A unit test of `shouldFireGate` cannot
 * catch a mistake in how the *handler* calls it — the latch could be stored but
 * never read, or compared against the wrong turn number. So this drives the real
 * handlers in the order Pi fires them and asserts on what actually gets injected.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";

import { registerMemoryHooks, summarizeToolCall } from "../extensions/umem/hooks.ts";
import type { UmemPiConfig } from "../extensions/umem/config.ts";

const CONFIG: UmemPiConfig = {
  gate: "message",
  detailTurnInterval: 3,
  silentSummary: false,
  injectPreferences: true,
  briefSnapshot: true,
  configFound: true,
};

interface Emitted {
  customType: string;
  content: string;
  display: boolean;
}

/**
 * A fake ExtensionAPI that records registrations and injected messages, and a
 * fake context whose branch is a mutable list of session entries.
 */
function makeFakePi(branch: unknown[], config: UmemPiConfig = CONFIG) {
  const handlers = new Map<string, (...args: unknown[]) => unknown>();
  const sent: Emitted[] = [];
  const notifications: string[] = [];

  const pi = {
    on(event: string, handler: (...args: unknown[]) => unknown) {
      handlers.set(event, handler);
      return () => handlers.delete(event);
    },
    sendMessage(message: Emitted) {
      sent.push(message);
    },
  };

  const ctx = {
    sessionManager: {
      getSessionId: () => "test-session",
      getBranch: () => branch,
    },
    ui: { notify: (text: string) => notifications.push(text) },
  };

  const fire = async (event: string, payload: unknown = {}): Promise<unknown> => {
    const handler = handlers.get(event);
    if (handler === undefined) return undefined;
    return await handler(payload, ctx);
  };

  registerMemoryHooks(pi as never, {
    config,
    runCli: async () => "",
    reminder: "REMINDER",
    gateReason: (events) =>
      events.length === 0 ? "GATE" : `GATE: ${events.length} events [${events[0]}]`,
    sessionSnapshot: async () => "PREFS",
    bumpStats: () => undefined,
  });

  return { fire, sent, handlers, notifications };
}

/** Push `n` human turns onto the branch. */
function addTurns(branch: unknown[], n: number): void {
  for (let i = 0; i < n; i += 1) {
    branch.push({ type: "message", message: { role: "user", content: `turn ${i}` } });
  }
}

test("session_start injects the reminder and snapshot once", async () => {
  const branch: unknown[] = [];
  const fake = makeFakePi(branch);
  await fake.fire("session_start", { reason: "startup" });

  assert.equal(fake.sent.length, 1);
  assert.match(fake.sent[0]!.content, /REMINDER/);
  assert.match(fake.sent[0]!.content, /PREFS/);
  assert.equal(fake.sent[0]!.customType, "umem");
  // Not shown in the transcript: this is context, not a message to read.
  assert.equal(fake.sent[0]!.display, false);
});

test("session_start on reload does not re-inject", async () => {
  const branch: unknown[] = [];
  const fake = makeFakePi(branch);
  await fake.fire("session_start", { reason: "reload" });
  assert.equal(fake.sent.length, 0);
});

test("a resumed session starts counting from its existing branch", async () => {
  const branch: unknown[] = [];
  addTurns(branch, 10);
  const fake = makeFakePi(branch);
  await fake.fire("session_start", { reason: "resume" });
  // lastSaveTurn is seeded to the branch's turn count, so the very first settle
  // does not see a delta of 10 and fire immediately.
  const result = await fake.fire("agent_before_settle", {});
  assert.equal(result, undefined, "a resumed session must not gate on turn one");
});

test("the gate fires once at the threshold and then latches", async () => {
  const branch: unknown[] = [];
  const fake = makeFakePi(branch);
  await fake.fire("session_start", { reason: "startup" });
  fake.sent.length = 0;

  // Turn 1..2: under the threshold of 3.
  for (let i = 0; i < 2; i += 1) {
    addTurns(branch, 1);
    await fake.fire("before_agent_start", { prompt: "do some work" });
    await fake.fire("tool_execution_end", { toolName: "write", isError: false });
    const result = await fake.fire("agent_before_settle", {});
    assert.equal(result, undefined, `turn ${i + 1} is under the threshold`);
  }

  // Turn 3: at the threshold — fires.
  addTurns(branch, 1);
  await fake.fire("before_agent_start", { prompt: "do more work" });
  await fake.fire("tool_execution_end", { toolName: "write", isError: false });
  const fired = await fake.fire("agent_before_settle", {});
  assert.ok(fired, "expected the gate to fire at the threshold");
  const result = fired as { entries: unknown[]; continue: boolean };
  assert.equal(result.continue, true);
  assert.equal(result.entries.length, 1);
  const entry = result.entries[0] as { type: string; customType: string; content: string };
  assert.equal(entry.type, "custom_message");
  assert.equal(entry.customType, "umem");
  assert.match(entry.content, /^GATE/);

  // THE assertion: settle again without a new turn. This is the loop Pi would
  // run — a second fire here would be an infinite session.
  const again = await fake.fire("agent_before_settle", {});
  assert.equal(again, undefined, "the gate must not fire twice in the same turn");
});

test("a memory write in the turn suppresses the gate", async () => {
  const branch: unknown[] = [];
  const fake = makeFakePi(branch);
  await fake.fire("session_start", { reason: "startup" });
  addTurns(branch, 5);
  await fake.fire("before_agent_start", { prompt: "record this" });
  await fake.fire("tool_call", { toolName: "umem", input: { action: "write-log" } });
  await fake.fire("tool_execution_end", { toolName: "umem", isError: false });

  const result = await fake.fire("agent_before_settle", {});
  assert.equal(result, undefined, "a write satisfies the gate");
});

test("a read does not satisfy the gate", async () => {
  const branch: unknown[] = [];
  const fake = makeFakePi(branch);
  await fake.fire("session_start", { reason: "startup" });
  addTurns(branch, 5);
  // A prompt that is substantial on its own (it mentions a deploy), so the only
  // question left is whether the `load` call counted as the memory write.
  await fake.fire("before_agent_start", { prompt: "deploy the service" });
  await fake.fire("tool_call", { toolName: "umem", input: { action: "load" } });
  await fake.fire("tool_execution_end", { toolName: "umem", isError: false });

  const result = await fake.fire("agent_before_settle", {});
  assert.ok(result, "a load is not a write; the gate should still fire");
});

test("gate: off never injects", async () => {
  const branch: unknown[] = [];
  const fake = makeFakePi(branch, { ...CONFIG, gate: "off" });
  await fake.fire("session_start", { reason: "startup" });
  addTurns(branch, 50);
  await fake.fire("before_agent_start", { prompt: "lots of work" });
  await fake.fire("tool_execution_end", { toolName: "write", isError: false });
  assert.equal(await fake.fire("agent_before_settle", {}), undefined);
});

test("a turn with no work at all does not gate, however long", async () => {
  const branch: unknown[] = [];
  const fake = makeFakePi(branch);
  await fake.fire("session_start", { reason: "startup" });
  addTurns(branch, 50);
  await fake.fire("before_agent_start", { prompt: "hello there" });
  // No tool calls, no memory mention in the prompt.
  assert.equal(await fake.fire("agent_before_settle", {}), undefined);
});

test("the gate reason names the events that happened", async () => {
  const branch: unknown[] = [];
  const fake = makeFakePi(branch);
  await fake.fire("session_start", { reason: "startup" });
  addTurns(branch, 5);
  await fake.fire("before_agent_start", { prompt: "deploy it" });
  await fake.fire("tool_execution_end", { toolName: "bash", isError: false });
  await fake.fire("tool_execution_end", { toolName: "edit", isError: false });

  const fired = (await fake.fire("agent_before_settle", {})) as {
    entries: { content: string }[];
  };
  assert.match(fired.entries[0]!.content, /2 events/);
});

test("a settled turn that wrote memory advances the checkpoint", async () => {
  const branch: unknown[] = [];
  const fake = makeFakePi(branch);
  await fake.fire("session_start", { reason: "startup" });
  addTurns(branch, 5);
  await fake.fire("before_agent_start", { prompt: "record" });
  await fake.fire("tool_call", { toolName: "umem", input: { action: "write-log" } });
  await fake.fire("agent_before_settle", {});

  // The next turn is only +1, so it must not fire even though the absolute
  // count is well past the threshold.
  addTurns(branch, 1);
  await fake.fire("before_agent_start", { prompt: "next" });
  await fake.fire("tool_execution_end", { toolName: "write", isError: false });
  assert.equal(await fake.fire("agent_before_settle", {}), undefined);
});

test("unknown events and missing context do not throw", async () => {
  const branch: unknown[] = [];
  const fake = makeFakePi(branch);
  assert.equal(await fake.fire("nonexistent_event"), undefined);
  // Settle before any session_start: state is null, must be a quiet no-op.
  assert.equal(await fake.fire("agent_before_settle", {}), undefined);
});

test("summarizeToolCall produces a one-line hint", () => {
  assert.equal(
    summarizeToolCall("bash", { command: "git commit -m 'x'\nwith newline" }),
    "bash: git commit -m 'x' with newline",
  );
  assert.equal(summarizeToolCall("edit", { file_path: "/a/b.py" }), "edit: /a/b.py");
  assert.equal(summarizeToolCall("write", {}), "write");
  assert.equal(summarizeToolCall("write", null), null);
});
