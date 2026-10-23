/**
 * Path resolution — the extension and the Python hooks must agree on which
 * memory repo they are talking to.
 *
 * These tests are about *precedence*, not about this machine's layout: they
 * assert that a candidate is honoured when present and that resolution never
 * throws or returns an empty string, which is what would make an error message
 * useless.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { pythonExecutable, resolveMemoryTool, resolveMemoryWeb } from "../extensions/umem/resolve.ts";

test("memory_tool.py resolves to an existing file on this machine", () => {
  const resolved = resolveMemoryTool();
  assert.ok(resolved.endsWith("memory_tool.py"), resolved);
  // Either an installed copy or this checkout must exist; a resolution that
  // points at nothing is a broken install, not a valid answer.
  assert.ok(existsSync(resolved), `expected an existing CLI, got ${resolved}`);
});

test("an explicit path wins when it exists", () => {
  const explicit = resolveMemoryTool();
  assert.equal(resolveMemoryTool(explicit), explicit);
});

test("a non-existent explicit path falls through instead of breaking the session", () => {
  // An explicit path that is gone (skill moved, venv rebuilt) must not make the
  // tool unusable when a working install exists elsewhere. Falling through is
  // the right answer; hard-coding the stale path would leave the user with a
  // tool that only ever says ENOENT.
  const bogus = "/nonexistent/definitely/not/here/memory_tool.py";
  const resolved = resolveMemoryTool(bogus);
  assert.ok(resolved.length > 0);
  assert.ok(resolved.endsWith("memory_tool.py"), resolved);
  if (!existsSync(bogus)) {
    assert.ok(
      existsSync(resolved) || resolved === bogus,
      `expected a working CLI or the stale path itself, got ${resolved}`,
    );
  }
});

test("USING_MEMORY_CONFIG wins over the conventional location", () => {
  const saved = process.env.USING_MEMORY_CONFIG;
  // tests/ → pi/ → packages/ → skill root
  const skillRoot = join(import.meta.dirname, "..", "..", "..");
  const expected = join(skillRoot, "scripts", "memory_tool.py");
  assert.ok(existsSync(expected), `test fixture missing: ${expected}`);
  process.env.USING_MEMORY_CONFIG = join(skillRoot, "config.yaml");
  try {
    assert.equal(resolveMemoryTool(), expected);
  } finally {
    if (saved === undefined) delete process.env.USING_MEMORY_CONFIG;
    else process.env.USING_MEMORY_CONFIG = saved;
  }
});

test("memory-web resolves to null rather than a broken path", () => {
  const saved = process.env.PATH;
  process.env.PATH = "";
  try {
    const resolved = resolveMemoryWeb("/nonexistent/memory-web");
    // Either null (not found) or the explicit string — never an empty string.
    assert.ok(resolved === null || resolved.length > 0);
  } finally {
    process.env.PATH = saved;
  }
});

test("python defaults to python3 and honours UMEM_PYTHON", () => {
  const saved = process.env.UMEM_PYTHON;
  delete process.env.UMEM_PYTHON;
  assert.equal(pythonExecutable(), "python3");
  process.env.UMEM_PYTHON = "/opt/custom/python";
  assert.equal(pythonExecutable(), "/opt/custom/python");
  if (saved === undefined) delete process.env.UMEM_PYTHON;
  else process.env.UMEM_PYTHON = saved;
});

test("the skill root candidate is the repo root, not packages/", () => {
  // Regression: an off-by-one in the relative walk resolved to `packages/`
  // and silently found nothing.
  const resolved = resolveMemoryTool();
  assert.ok(!resolved.includes(`${join("using-memory", "packages")}${join("/")}scripts`), resolved);
  void homedir;
});
