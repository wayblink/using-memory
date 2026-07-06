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
            "<namespace>/MEMORY.md",
            "<namespace>/PREFERENCES.md",
            "<namespace>/docs/index.json",
            "<namespace>/STATS.json",
            "<namespace>/log/",
            "<namespace>/sessions/index.jsonl",
        ]

        for snippet in required_snippets:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, text, f"repo-layout.md must mention {snippet}")

        for legacy in [
            "<namespace>/local/MACHINE.md",
            "<namespace>/local/ENV.md",
            "<namespace>/local/WORKSPACE.md",
        ]:
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, text, f"repo-layout.md must no longer mention {legacy}")

    def test_repo_layout_has_recommended_tree_lines(self):
        text = self.read_repo_layout()
        match = re.search(r"## Recommended Structure\s+```(?:text)?\n(.*?)\n```", text, re.DOTALL)
        self.assertIsNotNone(match, "repo-layout.md must include a fenced recommended tree block")

        expected_tree = "\n".join(
            [
                "memory-repo/",
                "  main/",
                "    README.md",
                "    SCHEMA.md",
                "    MEMORY.md",
                "    PREFERENCES.md",
                "    STATS.json",
                "    docs/",
                "      index.json",
                "      workflow.md",
                "      coding.md",
                "    log/",
                "      2026-04-13.jsonl",
                "    sessions/",
                "      index.jsonl",
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
            "`<namespace>/README.md`",
            "`<namespace>/SCHEMA.md`",
            "`<namespace>/MEMORY.md`",
            "`<namespace>/PREFERENCES.md`",
            "`<namespace>/log/`",
            "`<namespace>/sessions/index.jsonl`",
            "`<namespace>/docs/`",
            "`<namespace>/docs/index.json`",
            "`<namespace>/STATS.json`",
        ]:
            with self.subTest(resource=resource):
                self.assertTrue(
                    any(line.startswith(f"- {resource}") for line in lines),
                    f"repo-layout.md must include responsibility bullet for {resource}",
                )

        for tag in ["[note]", "[decision|2026-04-13]", "[lesson|2026-04-13]", "[fact]"]:
            with self.subTest(tag=tag):
                self.assertIn(tag, text, f"repo-layout.md must show sample tag {tag}")

    def test_startup_doc_has_sections_and_local_rules(self):
        text = self.read_startup_doc()

        for heading in [
            "## Retrieval Triggers",
            "## Retrieval Read Order",
            "## docs On-Demand Expansion",
            "## Write Rules",
            "## Distillation Rules",
            "## Non-Goals",
        ]:
            with self.subTest(heading=heading):
                self.assertIn(heading, text, f"{heading} must appear in startup doc")

        local_first_phrases = [
            "Do not load memory by default for every conversation or every turn.",
            "Use memory retrieval only when memory could change the answer",
            "Skip memory for greetings",
            "isolated coding tasks with enough local context",
            "Local primary repo first",
            "Reference repos are read-only",
            "load --log-from/--log-to",
            "load --log-days",
            "load --log-query",
            "Log entries from other namespaces are ignored by default",
            "default toward recording concrete operation history and key events",
            "Do not apply a heavy",
        ]

        for phrase in local_first_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text, f"startup doc must mention '{phrase}'")

        do_not_phrases = [
            "no daemon",
            "no DB",
            "no automatic multi-writer sync",
            "Do not mirror every tool call mechanically",
        ]

        for todo in do_not_phrases:
            with self.subTest(todo=todo):
                self.assertIn(todo, text, f"Non-Goals section must mention {todo}")

        for phrase in [
            "preferences",
            "durable_memory",
            "doc_hits",
            "sources",
            "`level`",
            "skip",
            "log_detail",
            "log_summary",
            "write_memory",
            "primary temporarily unwritable -> read-only mode",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        # local_context was removed in V2.3.
        self.assertNotIn("local_context", text)

        for phrase in [
            "scripts/memory_tool.py write-preference",
            "scripts/memory_tool.py write-memory",
            "scripts/memory_tool.py upsert-doc",
            "only `fact`, `decision`, and `lesson` are allowed",
            "not written to `<namespace>/MEMORY.md` by default",
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
            "## Host skill exposure",
            "## Hook Enforcement",
            "### Codex",
            "### Claude Code",
            "### Codex hook install",
            "### Claude Code hook install",
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
            "~/.codex/hooks.json",
            "~/.claude/settings.json",
            "codex_hooks = true",
            "scripts/hooks/codex_memory_hook.py",
            "scripts/hooks/claude_memory_hook.py",
            "scripts/hooks/claude_session_start_hook.py",
            "`Stop` is the enforcement point",
            "@../skills/using-memory/SKILL.md",
            "@./skills/using-memory/SKILL.md",
            "Start a brand-new Codex or Claude Code session",
            "This exposes the skill for decision-based use; it must not force memory loading before every task.",
            "First probe: ask a prompt that should not need memory",
            "Second probe: ask a prompt that explicitly needs saved memory",
            "SessionStart preference probe",
            "PREFERENCES.md",
            "MEMORY.md",
            "log_detail",
            "write_memory",
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
            "namespace",
            "priority",
            "writable: true",
            "examples/new-machine/config.template.yaml",
            "examples/new-machine/GEMINI.template.md",
            "examples/new-machine/CLAUDE.template.md",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
