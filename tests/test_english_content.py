import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Directories that are never project source (virtualenvs, VCS, tool caches,
# generated bundles). rglob would otherwise descend into an installed .venv and
# flag Chinese text inside third-party packages, which has nothing to do with
# this project's own content.
EXEMPT_DIR_PARTS = {
    ".venv",
    "venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".playwright-mcp",
    ".mypy_cache",
    "node_modules",
    "egg-info",
    "tmp",
    "output",
}

# Files/subtrees that legitimately contain non-English text. The English-only
# rule protects agent-facing skill content (SKILL.md, references/, scripts/
# logic, examples) so the skill stays portable across agents; it deliberately
# does NOT cover the bilingual web UI, the language-detection regex, multilingual
# test fixtures, or historical design specs.
EXEMPT_PREFIXES = (
    "web/",  # bilingual UI: i18n translation table + README describe the zh locale
    "docs/superpowers/",  # historical design specs authored partly in Chinese
)
EXEMPT_FILES = {
    # Language-preference detection must match Chinese/Japanese trigger words.
    "scripts/hooks/memory_hook_common.py",
    # Fixtures exercise the Chinese language-preference feature end to end.
    "tests/test_memory_hooks.py",
}


def _is_exempt(rel_posix: str, parts: tuple[str, ...]) -> bool:
    if any(part in EXEMPT_DIR_PARTS or part.endswith(".egg-info") for part in parts):
        return True
    if rel_posix in EXEMPT_FILES:
        return True
    return any(rel_posix.startswith(prefix) for prefix in EXEMPT_PREFIXES)


class EnglishContentTests(unittest.TestCase):
    def test_project_text_files_do_not_contain_han_characters(self):
        suffixes = {".md", ".json", ".py", ".yaml", ".sh"}
        offenders = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            rel = path.relative_to(ROOT)
            rel_posix = rel.as_posix()
            if _is_exempt(rel_posix, rel.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"[\u4e00-\u9fff]", text):
                offenders.append(rel_posix)

        self.assertEqual(offenders, [], f"Han characters found in English-only files: {offenders}")


if __name__ == "__main__":
    unittest.main()
