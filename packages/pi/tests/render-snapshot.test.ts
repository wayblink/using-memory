/**
 * The Pi snapshot renderer.
 *
 * `renderSnapshot` turns `load --json --brief` into the text injected into the
 * conversation. It had no test coverage at all, which is how the section title
 * drifted from "Saved preferences" to "Active spec" without anything noticing —
 * and a wrong title is not cosmetic: the surrounding sentence is what tells the
 * model these are constraints rather than background notes.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";

import { renderSnapshot, ruleLines } from "../extensions/umem/snapshot.ts";

test("rules are rendered under the Active spec heading", () => {
  const raw = JSON.stringify({
    preferences: ["# Spec\n\n- always reply in Simplified Chinese\n"],
  });
  const out = renderSnapshot(raw);
  assert.ok(out !== null);
  assert.match(out, /## Active spec/);
  // The words that make the section operational rather than decorative.
  assert.match(out, /constraints/i);
  assert.match(out, /always reply in Simplified Chinese/);
});

test("rules are never truncated in the snapshot", () => {
  // A rule cut mid-sentence reads as a complete rule and gets followed
  // literally, so length must not be capped here.
  const long = `- ${"detail ".repeat(500)}END-MARKER`;
  const out = renderSnapshot(JSON.stringify({ preferences: [long] }));
  assert.ok(out !== null);
  assert.match(out, /END-MARKER/);
});

test("rules come before memory and log entries", () => {
  // Rules must be in effect before the first answer, so they lead.
  const raw = JSON.stringify({
    preferences: ["RULE_TEXT"],
    durable_memory: ["MEMORY_TEXT"],
    log_entries: [{ ts: "2026-10-24T00:00:00Z", tag: "note", text: "LOG_TEXT" }],
  });
  const out = renderSnapshot(raw) ?? "";
  assert.ok(out.indexOf("RULE_TEXT") < out.indexOf("MEMORY_TEXT"));
  assert.ok(out.indexOf("RULE_TEXT") < out.indexOf("LOG_TEXT"));
});

test("a snapshot with no preferences omits the section entirely", () => {
  const out = renderSnapshot(JSON.stringify({ durable_memory: ["MEMORY_TEXT"] })) ?? "";
  assert.doesNotMatch(out, /## Active spec/);
  assert.match(out, /MEMORY_TEXT/);
});

test("unconfigured memory is reported rather than silently empty", () => {
  const out = renderSnapshot(JSON.stringify({ mode: "no_memory" })) ?? "";
  assert.match(out, /Memory not configured/);
});

test("malformed input yields null instead of a broken message", () => {
  assert.equal(renderSnapshot("not json"), null);
  assert.equal(renderSnapshot("null"), null);
  assert.equal(renderSnapshot("[]"), null);
});

test("warnings are surfaced", () => {
  const out = renderSnapshot(JSON.stringify({ warnings: ["config missing"] })) ?? "";
  assert.match(out, /config missing/);
});

test("the file preamble is not rendered as a rule", () => {
  // A SPEC file opens with "# Spec" and a line explaining where project specs
  // live. Both describe the format; rendering them as bullets makes the model
  // follow documentation as if it were an instruction.
  const raw = JSON.stringify({
    preferences: [
      "# Spec\n\nRules and constraints that apply to every project in this namespace.\nProject-specific specs live in `spec/<repo>.md`.\n\n- the real rule\n",
    ],
  });
  const out = renderSnapshot(raw) ?? "";
  assert.match(out, /- the real rule/);
  assert.doesNotMatch(out, /Project-specific specs live/);
  assert.doesNotMatch(out, /Rules and constraints that apply/);
});

test("rule entries are normalised the way the Python renderer does it", () => {
  assert.deepEqual(ruleLines("# Spec\n\npreamble\n\n- [2026-10-24] a rule\n"), ["a rule"]);
  // Continuation lines belong to the rule above them.
  assert.deepEqual(ruleLines("# Spec\n\n- first.\n\n  Why: because.\n"), ["first. Why: because."]);
  // A document with no list items contributes nothing.
  assert.deepEqual(ruleLines("# Spec\n\njust a preamble\n"), []);
});

test("duplicate rules across sources are not repeated", () => {
  const raw = JSON.stringify({ preferences: ["- shared\n", "- shared\n- other\n"] });
  const out = renderSnapshot(raw) ?? "";
  assert.equal((out.match(/shared/g) ?? []).length, 1);
});

test("one document's preamble is not absorbed by the previous document's last rule", () => {
  // Global SPEC.md and a project spec are separate documents. Processing them
  // as one blob made the mkdir project's preamble become the tail of the last
  // global rule — the two hosts then delivered different rule text for the same
  // rule, which is precisely the divergence the shared renderer exists to stop.
  const raw = JSON.stringify({
    preferences: [
      "# Spec\n\npreamble one\n\n- global rule\n",
      "# Spec — dozo\n\nConstraints for the `dozo` repository.\n\n- dozo rule\n",
    ],
  });
  const out = renderSnapshot(raw) ?? "";
  assert.match(out, /^- global rule$/m);
  assert.doesNotMatch(out, /global rule .*Constraints for the/);
  assert.match(out, /^- dozo rule$/m);
});
