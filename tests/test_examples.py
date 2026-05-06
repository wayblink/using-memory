import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExampleTests(unittest.TestCase):
    def test_config_example_declares_primary_and_reference_roots(self):
        text = (ROOT / "examples/config.example.yaml").read_text(encoding="utf-8")
        for needle in [
            "memory_roots:",
            "role: primary",
            "role: reference",
            "writable: true",
            "writable: false",
            "priority:",
        ]:
            self.assertIn(needle, text)

    def test_new_machine_templates_match_expected_layout(self):
        config_text = (ROOT / "examples/new-machine/config.template.yaml").read_text(
            encoding="utf-8"
        )
        gemini_text = (ROOT / "examples/new-machine/GEMINI.template.md").read_text(
            encoding="utf-8"
        )
        claude_text = (ROOT / "examples/new-machine/CLAUDE.template.md").read_text(
            encoding="utf-8"
        )

        for needle in [
            "version: 1",
            "path: ~/.memories/main",
            "role: primary",
            "writable: true",
            "machine_id: local-main",
            "priority: 100",
            "role: reference",
            "writable: false",
            "~/.skills/using-memory/config.yaml",
        ]:
            with self.subTest(needle=needle):
                self.assertIn(needle, config_text)

        self.assertEqual(
            gemini_text.strip().splitlines(),
            [
                "@../skills/using-memory/SKILL.md",
                "@./skills/using-superpowers/SKILL.md",
                "@./skills/using-superpowers/references/gemini-tools.md",
            ],
        )
        self.assertEqual(claude_text.strip().splitlines(), ["@./skills/using-memory/SKILL.md"])

    def test_memory_repo_example_contains_expected_seed_files(self):
        required = [
            "README.md",
            "SCHEMA.md",
            "MEMORY.md",
            "PREFERENCES.md",
            "docs/index.json",
            "docs/workflow.md",
            "local/MACHINE.md",
            "local/ENV.md",
            "local/WORKSPACE.md",
            "daily/2026-04-13.md",
        ]
        for rel in required:
            self.assertTrue((ROOT / "examples/memory-repo" / rel).exists(), rel)

    def test_daily_example_uses_lightweight_tags(self):
        text = (ROOT / "examples/memory-repo/daily/2026-04-13.md").read_text(encoding="utf-8")
        self.assertIn("[pref]", text)
        self.assertIn("[decision|2026-04-13]", text)
        self.assertIn("[lesson|2026-04-13]", text)
