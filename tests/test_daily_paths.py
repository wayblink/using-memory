import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DailyPathTests(unittest.TestCase):
    def test_docs_name_the_canonical_flat_log_path(self):
        for rel in [
            "SKILL.md",
            "README.md",
            "references/startup-and-write-rules.md",
            "references/repo-layout.md",
            "examples/memory-repo/main/SCHEMA.md",
            "examples/memory-repo/main/docs/workflow.md",
        ]:
            with self.subTest(rel=rel):
                text = (ROOT / rel).read_text(encoding="utf-8")
                self.assertIn("<namespace>/log/YYYY-MM-DD.jsonl", text)

    def test_docs_do_not_publish_year_layered_log_paths(self):
        legacy_paths = [
            "memory/YYYY/YYYY-MM-DD.md",
            "log/YYYY/YYYY-MM-DD.md",
            "memory/YYYY/",
            "log/YYYY/",
        ]
        for rel in [
            "SKILL.md",
            "README.md",
            "references/startup-and-write-rules.md",
            "references/repo-layout.md",
            "examples/memory-repo/main/SCHEMA.md",
            "examples/memory-repo/main/docs/workflow.md",
        ]:
            with self.subTest(rel=rel):
                text = (ROOT / rel).read_text(encoding="utf-8")
                for legacy_path in legacy_paths:
                    self.assertNotIn(legacy_path, text)

    def test_docs_do_not_publish_legacy_markdown_log_path(self):
        legacy_path = "log/YYYY-MM-DD.md"
        for rel in [
            "SKILL.md",
            "README.md",
            "references/startup-and-write-rules.md",
            "references/repo-layout.md",
            "examples/memory-repo/main/SCHEMA.md",
            "examples/memory-repo/main/docs/workflow.md",
        ]:
            with self.subTest(rel=rel):
                text = (ROOT / rel).read_text(encoding="utf-8")
                self.assertNotIn(legacy_path, text)

    def test_schema_does_not_publish_removed_commands_or_flags(self):
        text = (ROOT / "examples/memory-repo/main/SCHEMA.md").read_text(encoding="utf-8")

        self.assertNotIn("prune", text)
        self.assertNotIn("load --daily-entries", text)
        self.assertIn("maintain", text)
