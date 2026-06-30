import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = ROOT / "web" / "src"
if str(WEB_SRC) not in sys.path:
    sys.path.insert(0, str(WEB_SRC))

from memory_web.app import create_app


class MemoryWebPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory_root = base / "memories"
        ns_root = self.memory_root / "main"
        docs_dir = ns_root / "docs"
        log_dir = ns_root / "log"
        docs_dir.mkdir(parents=True)
        log_dir.mkdir(parents=True)

        (ns_root / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (ns_root / "PREFERENCES.md").write_text("# Preferences\n", encoding="utf-8")

        doc_index = []
        for i in range(1, 26):
            rel = f"doc-{i:02d}.md"
            (docs_dir / rel).write_text(f"# Doc {i:02d}\n\nBody {i:02d}\n", encoding="utf-8")
            doc_index.append(
                {
                    "path": rel,
                    "title": f"Doc {i:02d}",
                    "type": "wiki",
                    "created": f"2026-05-{i:02d}",
                    "modified": f"2026-06-{i:02d}" if i <= 30 else "2026-06-30",
                    "projects": [],
                    "tags": [],
                    "summary": f"Summary {i:02d}",
                }
            )
        (docs_dir / "index.json").write_text(json.dumps(doc_index), encoding="utf-8")

        log_entries = []
        for i in range(1, 26):
            day = f"2026-06-{(i % 28) + 1:02d}"
            log_entries.append(
                {
                    "ts": f"{day}T12:{i:02d}:00+08:00",
                    "date": day,
                    "tag": "note",
                    "level": "summary",
                    "source": "user",
                    "text": f"Log entry {i:02d}",
                }
            )
        (log_dir / "2026-06-30.jsonl").write_text(
            "\n".join(json.dumps(entry, ensure_ascii=False) for entry in log_entries) + "\n",
            encoding="utf-8",
        )

        self.config_path = base / "config.yaml"
        self.config_path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "memory_roots": [
                        {
                            "path": str(self.memory_root),
                            "role": "primary",
                            "writable": True,
                            "namespace": "main",
                            "machine_id": "test-main",
                            "priority": 100,
                        }
                    ],
                    "defaults": {
                        "read_today": True,
                        "read_yesterday": True,
                        "load_docs_on_demand": True,
                    },
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        self.client = TestClient(create_app(config_path=str(self.config_path)))

    def tearDown(self) -> None:
        self.client.close()
        self.tmp.cleanup()

    def test_docs_support_page_and_per_page(self):
        resp = self.client.get("/docs?sort=name&page=2&per_page=10")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("showing 11-20 of 25", resp.text)
        self.assertIn("25 total · page 2 of 3 · 10 on this page", resp.text)
        self.assertIn("Doc 11", resp.text)
        self.assertIn("Doc 20", resp.text)
        self.assertNotIn("Doc 01", resp.text)
        self.assertIn("per_page=10", resp.text)

    def test_docs_support_created_sort(self):
        resp = self.client.get("/docs?sort=created&page=1&per_page=10")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("showing 1-10 of 25", resp.text)
        self.assertIn("Doc 25", resp.text)
        self.assertIn("Doc 16", resp.text)
        self.assertNotIn("Doc 15", resp.text)

    def test_logs_support_page_and_per_page(self):
        resp = self.client.get("/logs?days=30&page=3&per_page=10")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("showing 21-25 of 25", resp.text)
        self.assertIn("25 total · page 3 of 3 · 5 on this page", resp.text)
        self.assertIn("Log entry 05", resp.text)
        self.assertNotIn("Log entry 25", resp.text)
        self.assertIn("per_page=10", resp.text)

    def test_logs_default_shows_all_range_with_zero_days(self):
        resp = self.client.get("/logs")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('name="days" min="0" max="365" value="0"', resp.text)
        self.assertIn("showing 1-10 of 25", resp.text)
        self.assertIn('aria-label="Pagination"', resp.text)

    def test_logs_zero_days_means_all_entries(self):
        resp = self.client.get("/logs?days=0")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("showing 1-10 of 25", resp.text)
        self.assertIn('aria-label="Pagination"', resp.text)


if __name__ == "__main__":
    unittest.main()
