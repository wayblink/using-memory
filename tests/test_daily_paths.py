import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DailyPathTests(unittest.TestCase):
    def test_docs_name_the_canonical_flat_daily_path(self):
        for rel in [
            "SKILL.md",
            "references/startup-and-write-rules.md",
            "references/repo-layout.md",
            "examples/memory-repo/SCHEMA.md",
            "examples/memory-repo/docs/workflow.md",
        ]:
            with self.subTest(rel=rel):
                text = (ROOT / rel).read_text(encoding="utf-8")
                self.assertIn("daily/YYYY-MM-DD.md", text)

    def test_docs_do_not_publish_year_layered_daily_paths(self):
        legacy_paths = [
            "memory/YYYY/YYYY-MM-DD.md",
            "daily/YYYY/YYYY-MM-DD.md",
            "memory/YYYY/",
            "daily/YYYY/",
        ]
        for rel in [
            "SKILL.md",
            "references/startup-and-write-rules.md",
            "references/repo-layout.md",
            "examples/memory-repo/SCHEMA.md",
            "examples/memory-repo/docs/workflow.md",
        ]:
            with self.subTest(rel=rel):
                text = (ROOT / rel).read_text(encoding="utf-8")
                for legacy_path in legacy_paths:
                    self.assertNotIn(legacy_path, text)
