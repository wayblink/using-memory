# Coding Standards

This wiki page shows doc type `wiki` - loaded on demand when the current task clearly matches a coding-standards query in `docs/index.json`.

## Python

- Follow PEP 8 for layout and naming.
- Type-hint public functions and return values.
- Use `pathlib.Path` instead of `os.path` for path work.
- Never write secrets in `.py` files; use environment variables.

## Shell scripts

- Use `#!/usr/bin/env bash` shebang.
- Set `-euo pipefail` at the top.
- Quote variable expansions: `"$var"` not `$var`.
- Prefer `$(command)` over backticks.

## Test files

- Name test files `test_<module>.py`.
- Use subTest for parametrised cases.
- Keep assertions focused: one reason per assert.

## Commit messages

- Imperative mood: "add", "fix", "refactor", not "added", "fixed".
- Subject <= 72 characters.
- Body explains *why*, not *how*.
