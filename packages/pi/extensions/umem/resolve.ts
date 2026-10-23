/**
 * resolve.ts — where the Python side actually lives.
 *
 * The extension never reimplements memory logic; it shells out to
 * `scripts/memory_tool.py` and, for `/umem web`, to the `memory-web` console
 * script. Both have to be *found*, and the finding order matters: the skill can
 * be installed by `install.sh` into a host directory, symlinked by `link.sh`
 * from a working checkout, or loaded straight from this repo during
 * development. Getting a different answer than the Python hooks would mean the
 * extension reads one memory repo while the hooks write another.
 *
 * So the resolution order here mirrors `resolve_memory_tool_path()` in
 * `scripts/hooks/memory_hook_common.py` — same inputs, same precedence — and a
 * test asserts the two agree on the obvious cases.
 */

import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** `~/.pi/agent/extensions/umem/index.ts` → the extension directory. */
const here = dirname(fileURLToPath(import.meta.url));

/**
 * `<skill>/scripts/memory_tool.py` relative to a candidate skill root,
 * ranked by how likely that root is the one the user actually configured.
 */
function memoryToolCandidates(explicit: string | undefined): string[] {
  const home = homedir();
  const out: string[] = [];
  if (explicit) out.push(explicit.replace(/^~(?=$|\/)/, home));

  // USING_MEMORY_CONFIG points at <skill>/config.yaml, so the CLI is its
  // sibling. This is the one that keeps the extension and the hooks in step.
  const envConfig = process.env.USING_MEMORY_CONFIG?.trim();
  if (envConfig) {
    out.push(join(dirname(envConfig.replace(/^~(?=$|\/)/, home)), "scripts", "memory_tool.py"));
  }

  out.push(
    join(home, ".skills", "using-memory", "scripts", "memory_tool.py"),
    join(process.env.CODEX_HOME?.trim() || join(home, ".codex"), "skills", "using-memory", "scripts", "memory_tool.py"),
    join(process.env.CLAUDE_HOME?.trim() || join(home, ".claude"), "skills", "using-memory", "scripts", "memory_tool.py"),
  );

  // extensions/umem/resolve.ts → umem, extensions, pi, then the skill root.
  out.push(resolve(here, "..", "..", "..", "..", "scripts", "memory_tool.py"));
  return out;
}

/**
 * First existing candidate; otherwise the candidate the caller most likely
 * meant, so the resulting error message names a path that would actually fix
 * the problem. Order of preference when nothing exists: the explicit path, then
 * the env-config sibling, then this checkout (the one a developer can repair).
 */
export function resolveMemoryTool(explicit?: string): string {
  const candidates = memoryToolCandidates(explicit);
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  if (explicit) return explicit.replace(/^~(?=$|\/)/, homedir());
  const envConfig = process.env.USING_MEMORY_CONFIG?.trim();
  if (envConfig) {
    const sibling = join(
      dirname(envConfig.replace(/^~(?=$|\/)/, homedir())),
      "scripts",
      "memory_tool.py",
    );
    return sibling;
  }
  // Last resort: this checkout. It is the copy the user can fix, and it is
  // where a development install expects the CLI to live.
  return resolve(here, "..", "..", "..", "..", "scripts", "memory_tool.py");
}

/**
 * The `memory-web` console script.
 *
 * Unlike `memory_tool.py` this is not a script we can invoke with `python3 <path>`
 * — it is an installed entry point, and it usually lives in the `web/` venv
 * rather than on PATH. Preference: `pi.memory_web_path`, then PATH, then the
 * venvs a checkout or install would plausibly have.
 */
export function resolveMemoryWeb(explicit?: string): string | null {
  const home = homedir();
  const candidates: string[] = [];
  if (explicit) candidates.push(explicit.replace(/^~(?=$|\/)/, home));

  // extensions/umem/resolve.ts → umem, extensions, pi, then the skill root.
  const skillRoot = resolve(here, "..", "..", "..", "..");
  candidates.push(
    join(skillRoot, "web", ".venv", "bin", "memory-web"),
    join(home, ".skills", "using-memory", "web", ".venv", "bin", "memory-web"),
    join(home, ".local", "bin", "memory-web"),
  );

  const pathDirs = (process.env.PATH ?? "").split(delimiter).filter(Boolean);
  for (const dir of pathDirs) candidates.push(join(dir, "memory-web"));

  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

/** `python3`, unless the environment names something better. */
export function pythonExecutable(): string {
  return process.env.UMEM_PYTHON?.trim() || "python3";
}
