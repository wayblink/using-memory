import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


class ReferenceDocTests(unittest.TestCase):
    @property
    def references_dir(self) -> Path:
        return ROOT / "references"

    @property
    def repo_layout_path(self) -> Path:
        return self.references_dir / "repo-layout.md"

    @property
    def startup_path(self) -> Path:
        return self.references_dir / "startup-and-write-rules.md"

    @property
    def machine_setup_path(self) -> Path:
        return self.references_dir / "machine-setup.md"

    def read_repo_layout(self) -> str:
        return self.repo_layout_path.read_text(encoding="utf-8")

    def read_startup_doc(self) -> str:
        return self.startup_path.read_text(encoding="utf-8")

    def read_machine_setup_doc(self) -> str:
        return self.machine_setup_path.read_text(encoding="utf-8")

    def startup_section(self, heading: str) -> str:
        text = self.read_startup_doc()
        pattern = rf"{re.escape(heading)}\n(.*?)(?:\n## |\Z)"
        match = re.search(pattern, text, re.DOTALL)
        self.assertIsNotNone(match, f"{heading} section must exist")
        return match.group(1).strip()

    def test_repo_layout_mentions_required_paths(self):
        text = self.read_repo_layout()
        required_snippets = [
            "MEMORY.md",
            "PREFERENCES.md",
            "docs/",
            "docs/index.json",
            "local/MACHINE.md",
            "local/ENV.md",
            "local/WORKSPACE.md",
            "daily/",
        ]

        for snippet in required_snippets:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, text, f"repo-layout.md must mention {snippet}")

    def test_repo_layout_has_recommended_tree_lines(self):
        text = self.read_repo_layout()
        match = re.search(r"## Recommended Structure\s+```(?:text)?\n(.*?)\n```", text, re.DOTALL)
        self.assertIsNotNone(match, "repo-layout.md must include a fenced recommended tree block")

        expected_tree = "\n".join(
            [
                "memory-repo/",
                "  README.md",
                "  SCHEMA.md",
                "  MEMORY.md",
                "  PREFERENCES.md",
                "  daily/",
                "    2026-04-13.jsonl",
                "  docs/",
                "    index.json",
                "    workflow.md",
                "    coding.md",
                "  local/",
                "    MACHINE.md",
                "    ENV.md",
                "    WORKSPACE.md",
            ]
        )
        self.assertEqual(
            match.group(1).strip(),
            expected_tree,
            "repo-layout.md must document the exact recommended tree in order",
        )

    def test_repo_layout_lists_responsibilities_and_tags(self):
        text = self.read_repo_layout()
        lines = [line.strip() for line in text.splitlines()]

        for resource in [
            "`README.md`",
            "`SCHEMA.md`",
            "`MEMORY.md`",
            "`PREFERENCES.md`",
            "`daily/`",
            "`docs/`",
            "`docs/index.json`",
            "`local/MACHINE.md`",
            "`local/ENV.md`",
            "`local/WORKSPACE.md`",
        ]:
            with self.subTest(resource=resource):
                self.assertTrue(
                    any(line.startswith(f"- {resource}") for line in lines),
                    f"repo-layout.md must include responsibility bullet for {resource}",
                )

        for tag in ["[pref]", "[decision|2026-04-13]", "[lesson|2026-04-13]", "[fact]"]:
            with self.subTest(tag=tag):
                self.assertIn(tag, text, f"repo-layout.md must show sample tag {tag}")

    def test_startup_doc_has_sections_and_local_rules(self):
        text = self.read_startup_doc()

        for heading in [
            "## Startup Read Order",
            "## docs On-Demand Expansion",
            "## Write Rules",
            "## Distillation Rules",
            "## Non-Goals",
        ]:
            with self.subTest(heading=heading):
                self.assertIn(heading, text, f"{heading} must appear in startup doc")

        local_first_phrases = [
            "Local primary repo first",
            "Reference repos are read-only",
            "load --daily-from/--daily-to",
            "load --daily-days",
            "load --daily-query",
            "`local/*` from other machines is ignored by default",
            "Daily notes from other machines are ignored by default",
            "Write only when information is worth preserving",
        ]

        for phrase in local_first_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text, f"startup doc must mention '{phrase}'")

        do_not_phrases = [
            "no daemon",
            "no DB",
            "no automatic multi-writer sync",
            "Do not record every tool call",
        ]

        for todo in do_not_phrases:
            with self.subTest(todo=todo):
                self.assertIn(todo, text, f"Non-Goals section must mention {todo}")

        for phrase in [
            "preferences",
            "durable_memory",
            "local_context",
            "doc_hits",
            "sources",
            "skip",
            "append_daily",
            "append_daily_and_queue_distill",
            "write_long_term_now",
            "primary temporarily unwritable -> read-only mode",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        for phrase in [
            "scripts/memory_tool.py write-preference",
            "scripts/memory_tool.py write-memory",
            "scripts/memory_tool.py upsert-doc",
            "only `fact`, `decision`, and `lesson` are allowed",
            "not written to `MEMORY.md` by default",
            "The index is the loader's entry point for deciding whether to open document bodies",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_startup_doc_lists_config_lookup_order(self):
        config_section = self.startup_section("## Config Lookup Order")
        lines = [line.strip() for line in config_section.splitlines() if line.strip()]
        self.assertGreaterEqual(
            len(lines),
            2,
            "Config Lookup Order section must include at least two ordered lookup steps",
        )
        self.assertEqual(lines[0], "1. `USING_MEMORY_CONFIG`")
        self.assertEqual(lines[1], "2. `~/.skills/using-memory/config.yaml`")

    def test_machine_setup_doc_covers_smoke_test_and_migration(self):
        text = self.read_machine_setup_doc()

        for heading in [
            "# Host Setup and Smoke Test",
            "## Host startup wiring",
            "### Codex",
            "### Claude Code",
            "## Fresh-session smoke test",
            "## Pass conditions",
            "## Common failures to check first",
            "## Multi-machine rollout",
            "## Per-machine values only",
        ]:
            with self.subTest(heading=heading):
                self.assertIn(heading, text)

        for phrase in [
            "~/.codex/superpowers/GEMINI.md",
            "~/.claude/CLAUDE.md",
            "@../skills/using-memory/SKILL.md",
            "@./skills/using-memory/SKILL.md",
            "Start a brand-new Codex or Claude Code session",
            "PREFERENCES.md",
            "MEMORY.md",
            "append_daily",
            "write_long_term_now",
            "write-preference",
            "USING_MEMORY_CONFIG",
            "~/.skills/using-memory/config.yaml",
            "scripts/link.sh",
            "scripts/install.sh",
            "claude-code",
            "both",
            "git clone",
            "git pull",
            "machine_id",
            "priority",
            "writable: true",
            "examples/new-machine/config.template.yaml",
            "examples/new-machine/GEMINI.template.md",
            "examples/new-machine/CLAUDE.template.md",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
