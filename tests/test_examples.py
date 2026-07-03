import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExampleTests(unittest.TestCase):
    def test_config_example_declares_primary_root_with_namespace(self):
        text = (ROOT / "examples/config.example.yaml").read_text(encoding="utf-8")
        for needle in [
            "memory_roots:",
            "role: primary",
            "writable: true",
            "namespace: main",
            "priority:",
            "features:",
            "anatomy:",
            "enabled: false",
            "silent_summary: false",
            "detail_turn_interval: 20",
            "session_archive:",
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
            "path: ~/.memories",
            "role: primary",
            "writable: true",
            "namespace: main",
            "machine_id: local-main",
            "priority: 100",
            "features:",
            "anatomy:",
            "enabled: false",
            "silent_summary: false",
            "detail_turn_interval: 20",
            "session_archive:",
            "mode: pointer",
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
            "main/README.md",
            "main/SCHEMA.md",
            "main/MEMORY.md",
            "main/PREFERENCES.md",
            "main/STATS.json",
            "main/docs/index.json",
            "main/docs/workflow.md",
            "main/sessions/index.jsonl",
            "main/anatomy/_index.json",
            "main/anatomy/spark-ann.json",
            "main/anatomy/spark-ann.md",
            "main/log/2026-04-13.jsonl",
        ]
        for rel in required:
            self.assertTrue((ROOT / "examples/memory-repo" / rel).exists(), rel)
        # The legacy local/ directory must not be re-introduced; V2.3 dropped it.
        self.assertFalse((ROOT / "examples/memory-repo/main/local").exists())

    def test_log_example_uses_lightweight_tags(self):
        import json

        text = (ROOT / "examples/memory-repo/main/log/2026-04-13.jsonl").read_text(encoding="utf-8")
        tags = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                tags.append(f"[{entry['tag']}]")
                if entry.get("date"):
                    tags.append(f"[{entry['tag']}|{entry['date']}]")
            except json.JSONDecodeError:
                continue
        self.assertIn("[note]", tags)
        self.assertIn("[decision|2026-04-13]", tags)
        self.assertIn("[lesson|2026-04-13]", tags)
