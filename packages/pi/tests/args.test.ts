/**
 * Pure-function tests for the umem extension's argument plumbing.
 *
 * Run with: node --test packages/pi/  (Node 22+; no Pi runtime needed)
 *
 * The argv tests are the load-bearing ones: a wrong flag shape reaches the
 * memory repo as corrupted data (a joined `--files` value becomes one bogus
 * path), and it does so silently, long after the call looked fine.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";

import { buildArgs, splitTokens, summarizeCall } from "../extensions/umem/args.ts";
import { parsePiBlock } from "../extensions/umem/config.ts";
import { parseWebCommand, extractServerUrl } from "../extensions/umem/web.ts";
import { PROMPT_GUIDELINES, resolveGuidance } from "../extensions/umem/guidance.ts";

test("every action asks for JSON output", () => {
  for (const action of ["load", "search", "write-log", "stats", "status"] as const) {
    const argv = buildArgs({ action });
    assert.equal(argv[0], action);
    assert.equal(argv.at(-1), "--json");
  }
});

test("without defaults, no --config or --date is invented", () => {
  assert.deepEqual(buildArgs({ action: "write-log", tag: "fix", text: "b" }), [
    "write-log",
    "--tag", "fix",
    "--text", "b",
    "--json",
  ]);
});

test("defaults inject the config path and today's date for the write verbs", () => {
  const argv = buildArgs(
    { action: "write-log", tag: "commit", text: "body" },
    { config: "/cfg/config.yaml", date: "2026-10-22" },
  );
  assert.deepEqual(argv, [
    "write-log",
    "--tag", "commit",
    "--text", "body",
    "--json",
    "--config", "/cfg/config.yaml",
    "--date", "2026-10-22",
  ]);
});

test("an explicit date from the model is not overwritten", () => {
  const argv = buildArgs(
    { action: "write-log", tag: "fix", text: "b", date: "2026-01-01" },
    { config: null, date: "2026-10-22" },
  );
  assert.equal(argv.filter((a) => a === "--date").length, 1);
  assert.ok(argv.includes("2026-01-01"));
  assert.ok(!argv.includes("2026-10-22"));
});

test("read verbs get --config but never --date", () => {
  const argv = buildArgs({ action: "stats" }, { config: "/cfg/config.yaml", date: "2026-10-22" });
  assert.ok(argv.includes("--config"));
  assert.ok(!argv.includes("--date"));
});

test("a null config default is not emitted", () => {
  const argv = buildArgs(
    { action: "write-memory", tag: "fact", text: "t" },
    { config: null, date: "2026-10-22" },
  );
  assert.ok(!argv.includes("--config"));
  assert.ok(argv.includes("--date"));
});

test("files are one --files flag per path, never joined", () => {
  const argv = buildArgs({
    action: "write-log",
    tag: "fix",
    text: "body",
    files: ["/a/b.py", "/c/d.py"],
  });
  assert.deepEqual(argv, [
    "write-log",
    "--tag", "fix",
    "--text", "body",
    "--files", "/a/b.py",
    "--files", "/c/d.py",
    "--json",
  ]);
  // The specific corruption to guard against.
  assert.ok(!argv.some((arg) => arg.includes(",")), "no comma-joined path list");
});

test("docTags repeat the same way", () => {
  const argv = buildArgs({ action: "load", docTags: ["x", "y"] });
  assert.deepEqual(argv.filter((a) => a === "--doc-tag").length, 2);
});

test("search takes its query as a positional", () => {
  const argv = buildArgs({ action: "search", query: "deploy rollback", project: "infra" });
  assert.deepEqual(argv, ["search", "deploy rollback", "--project", "infra", "--json"]);
});

test("write-memory carries no log-only flags", () => {
  const argv = buildArgs({
    action: "write-memory",
    tag: "decision",
    text: "x",
    files: ["/a"],
    level: "detail",
  });
  assert.deepEqual(argv, ["write-memory", "--tag", "decision", "--text", "x", "--json"]);
});

test("false booleans are omitted, true ones are bare flags", () => {
  assert.deepEqual(buildArgs({ action: "maintain", distill: false }), ["maintain", "--json"]);
  assert.deepEqual(buildArgs({ action: "maintain", distill: true }), [
    "maintain",
    "--distill",
    "--json",
  ]);
});

test("upsert-doc maps the doc metadata", () => {
  const argv = buildArgs({
    action: "upsert-doc",
    doc: "runbook",
    text: "body",
    docTitle: "Runbook",
    docType: "runbook",
    docTags: ["ops"],
    project: "infra",
    summary: "how to roll back",
  });
  assert.deepEqual(argv, [
    "upsert-doc",
    "--doc", "runbook",
    "--text", "body",
    "--title", "Runbook",
    "--doc-type", "runbook",
    "--doc-tag", "ops",
    "--project", "infra",
    "--summary", "how to roll back",
    "--json",
  ]);
});

test("summarizeCall stays one line and hides the body", () => {
  const summary = summarizeCall({
    action: "write-log",
    tag: "commit",
    text: "a very long body\nwith newlines",
  });
  assert.equal(summary, "write-log commit --text …");
  assert.ok(!summary.includes("\n"));
});

test("splitTokens honours quotes", () => {
  assert.deepEqual(splitTokens('search "two words" --project x'), [
    "search",
    "two words",
    "--project",
    "x",
  ]);
});

test("parsePiBlock reads only the pi block", () => {
  const block = parsePiBlock(
    [
      "logging:",
      "  detail_turn_interval: 20",
      "pi:",
      "  gate: off",
      "  detail_turn_interval: 45",
      "  # a comment",
      "  memory_tool_path: /opt/umem/memory_tool.py",
      "session_archive:",
      "  enabled: false",
    ].join("\n"),
  );
  assert.deepEqual(block, {
    gate: "off",
    detail_turn_interval: "45",
    memory_tool_path: "/opt/umem/memory_tool.py",
  });
});

test("parsePiBlock returns nothing when the block is absent", () => {
  assert.deepEqual(parsePiBlock("logging:\n  silent_summary: false\n"), {});
});

test("web command parses start and stop", () => {
  assert.deepEqual(parseWebCommand([]), { action: "start", args: [], error: null });
  assert.deepEqual(parseWebCommand(["--port", "9000"]), {
    action: "start",
    args: ["--port", "9000"],
    error: null,
  });
  assert.deepEqual(parseWebCommand(["stop"]), { action: "stop", args: [], error: null });
  assert.ok(parseWebCommand(["stop", "now"]).error);
  assert.ok(parseWebCommand(["banana"]).error);
});

test("extractServerUrl needs trailing whitespace", () => {
  // A URL cut by a chunk boundary must not be reported as a working address.
  assert.equal(extractServerUrl("Uvicorn running on http://127.0.0.1:87"), null);
  assert.equal(
    extractServerUrl("Uvicorn running on http://127.0.0.1:8765 (Press CTRL+C to quit)\n"),
    "http://127.0.0.1:8765",
  );
});

test("guidance carries the routing rules the model needs before loading the skill", () => {
  const { promptSnippet, promptGuidelines } = resolveGuidance();
  assert.ok(promptSnippet.length > 0);
  const joined = promptGuidelines.join("\n");
  assert.match(joined, /write-preference/);
  assert.match(joined, /write-memory/);
  assert.match(joined, /write-log/);
  assert.match(joined, /comma-separated/i);
  assert.equal(promptGuidelines, PROMPT_GUIDELINES);
});
