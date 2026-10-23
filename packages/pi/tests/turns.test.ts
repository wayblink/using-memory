/**
 * The gate and the turn counter — the two pieces that can damage a session.
 *
 * A gate that fires when it should not costs tokens; a gate that fails to latch
 * costs the session, because Pi answers `continue: true` with another model
 * request and then settles again. These tests pin both.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  UMEM_CUSTOM_TYPE,
  countHumanTurns,
  isMemoryWrite,
  isSyntheticUserText,
  shouldFireGate,
  type GateInputs,
  type TurnEntry,
} from "../extensions/umem/turns.ts";

const human = (text: string): TurnEntry => ({
  type: "message",
  message: { role: "user", content: text },
});

const assistant = (text: string): TurnEntry => ({
  type: "message",
  message: { role: "assistant", content: text },
});

const toolResult = (): TurnEntry => ({
  type: "message",
  message: {
    role: "toolResult",
    content: [{ type: "text", text: "exit 0" }],
  },
});

const injected = (): TurnEntry => ({
  type: "custom_message",
  customType: UMEM_CUSTOM_TYPE,
  message: { role: "user", content: "gate text" },
});

/* ------------------------------ turn counting ------------------------------ */

test("counts plain human messages", () => {
  assert.equal(countHumanTurns([human("a"), assistant("x"), human("b")]), 2);
});

test("ignores assistant messages and tool results", () => {
  assert.equal(countHumanTurns([assistant("x"), toolResult(), toolResult()]), 0);
});

test("ignores our own injected gate messages", () => {
  // The gate appends a custom_message with the umem customType. Counting it
  // would let the gate feed its own counter and re-fire forever.
  assert.equal(countHumanTurns([human("a"), injected(), injected()]), 1);
});

test("ignores synthetic wrapper content", () => {
  const synthetic: TurnEntry[] = [
    human("<system-reminder>be careful</system-reminder>"),
    human("<command-message>ukb</command-message>"),
    human("Stop hook feedback: write a log"),
    human("   "),
  ];
  assert.equal(countHumanTurns(synthetic), 0);
});

test("only leading wrapper prefixes are synthetic, not mentions mid-text", () => {
  // A prompt that *discusses* a tag is a human turn; only a prompt that *starts*
  // with a wrapper is machine-generated. Trimming-then-startsWith is why.
  assert.equal(countHumanTurns([human("why does <system-reminder> appear?")]), 1);
  assert.equal(countHumanTurns([human("<local-command> is a thing I typed about")]), 1);
  // ...but a wrapper line itself is not.
  assert.equal(countHumanTurns([human("<command-name>/ukb</command-name>")]), 0);
});

test("content blocks are read, not just strings", () => {
  const entry: TurnEntry = {
    type: "message",
    message: {
      role: "user",
      content: [
        { type: "text", text: "look at this" },
        { type: "image", data: "…" },
      ],
    },
  };
  assert.equal(countHumanTurns([entry]), 1);
});

test("isSyntheticUserText treats an empty prompt as synthetic", () => {
  assert.equal(isSyntheticUserText(""), true);
  assert.equal(isSyntheticUserText("deploy the thing"), false);
});

/* --------------------------------- the gate -------------------------------- */

const base: GateInputs = {
  gate: "message",
  substantial: true,
  delta: 30,
  memoryWritten: false,
  firedThisTurn: false,
  threshold: 30,
};

const decide = (patch: Partial<GateInputs>) => shouldFireGate({ ...base, ...patch });

test("fires at the threshold with substantial work and no write", () => {
  const decision = decide({});
  assert.equal(decision.fire, true);
  assert.equal(decision.reason, "fired");
});

test("never fires when disabled", () => {
  assert.equal(decide({ gate: "off" }).reason, "disabled");
  // Even at an absurd delta with everything else favourable.
  assert.equal(decide({ gate: "off", delta: 9999 }).fire, false);
});

test("does not fire without substantial work", () => {
  assert.equal(decide({ substantial: false }).reason, "not-substantial");
});

test("does not fire when the model already wrote memory", () => {
  assert.equal(decide({ memoryWritten: true }).reason, "already-written");
});

test("does not fire twice in one turn", () => {
  // The latch. This is the assertion that keeps a session from looping.
  assert.equal(decide({ firedThisTurn: true }).reason, "already-fired-this-turn");
  assert.equal(decide({ firedThisTurn: true }).fire, false);
});

test("does not fire one turn early", () => {
  assert.equal(decide({ delta: 29 }).reason, "below-threshold");
  assert.equal(decide({ delta: 30 }).fire, true);
});

test("every suppression reason is distinct", () => {
  const reasons = new Set([
    decide({ gate: "off" }).reason,
    decide({ substantial: false }).reason,
    decide({ memoryWritten: true }).reason,
    decide({ firedThisTurn: true }).reason,
    decide({ delta: 0 }).reason,
    decide({}).reason,
  ]);
  assert.equal(reasons.size, 6, "each path must be distinguishable in a log");
});

test("a memory write suppresses the gate even on a high delta", () => {
  assert.equal(decide({ delta: 500, memoryWritten: true }).fire, false);
});

/* --------------------------- what counts as a write ------------------------ */

test("only write verbs count as a memory write", () => {
  assert.equal(isMemoryWrite("umem", { action: "write-log" }), true);
  assert.equal(isMemoryWrite("umem", { action: "write-memory" }), true);
  assert.equal(isMemoryWrite("umem", { action: "write-preference" }), true);
  assert.equal(isMemoryWrite("umem", { action: "upsert-doc" }), true);
});

test("reads do not count — a load must not satisfy the gate", () => {
  assert.equal(isMemoryWrite("umem", { action: "load" }), false);
  assert.equal(isMemoryWrite("umem", { action: "search" }), false);
  assert.equal(isMemoryWrite("umem", { action: "status" }), false);
  assert.equal(isMemoryWrite("umem", { action: "maintain" }), false);
});

test("other tools never count", () => {
  assert.equal(isMemoryWrite("bash", { action: "write-log" }), false);
  assert.equal(isMemoryWrite("write", { file_path: "/a" }), false);
  assert.equal(isMemoryWrite("umem", null), false);
  assert.equal(isMemoryWrite("umem", {}), false);
});
