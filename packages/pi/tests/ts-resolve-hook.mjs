/**
 * Resolve hook: `./x.js` → `./x.ts` when only the TypeScript source exists.
 *
 * The extension imports `./turns.js` — the convention Pi's jiti loader expects
 * and the one that keeps the published package valid ESM. Node's own type
 * stripping does not rewrite `.js` to `.ts`, so the test runner needs this shim.
 * It only *falls back* to the `.ts` sibling when the `.js` import fails, so a
 * real `.js` file is never shadowed. Production behaviour is untouched.
 *
 * Imported by every test file's first line via `--import`.
 */

import { registerHooks } from "node:module";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(".") && specifier.endsWith(".js")) {
      try {
        return nextResolve(specifier, context);
      } catch {
        const asTs = `${specifier.slice(0, -3)}.ts`;
        try {
          return nextResolve(asTs, context);
        } catch {
          // Fall through to the original error: a missing module should report
          // the specifier the source actually wrote.
        }
      }
    }
    return nextResolve(specifier, context);
  },
});
