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


class MemoryWebDownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory_root = base / "memories"
        ns_root = self.memory_root / "main"
        (ns_root / "docs").mkdir(parents=True)
        (ns_root / "anatomy").mkdir(parents=True)
        (ns_root / "log").mkdir()

        (ns_root / "MEMORY.md").write_text(
            "# Memory\n\n- [fact|2026-06-29] Download support matters.\n",
            encoding="utf-8",
        )
        (ns_root / "PREFERENCES.md").write_text(
            "# Preferences\n\n- [2026-06-29] Prefer file downloads from the web UI.\n",
            encoding="utf-8",
        )
        (ns_root / "docs" / "workflow.md").write_text(
            "# Workflow\n\nDownload this file.\n",
            encoding="utf-8",
        )
        (ns_root / "docs" / "index.json").write_text(
            '[{"path":"workflow.md","title":"Workflow","type":"wiki","modified":"2026-06-29","projects":[],"tags":[],"summary":"doc"}]\n',
            encoding="utf-8",
        )
        (ns_root / "anatomy" / "demo.json").write_text(
            '{"root":"/tmp/demo","scanned_at":"2026-06-29T10:00:00+08:00","totals":{"files":1,"tokens_est":10},"files":{"src/app.py":{"desc":"entry","kind":"code","tokens_est":10}}}\n',
            encoding="utf-8",
        )
        (ns_root / "anatomy" / "demo.md").write_text(
            "# Anatomy demo\n\n- src/app.py\n",
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

    def test_doc_download_returns_attachment(self):
        resp = self.client.get("/docs/workflow.md/download")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment; filename="workflow.md"', resp.headers.get("content-disposition", ""))
        self.assertIn("# Workflow", resp.text)

    def test_memory_and_preferences_downloads_work(self):
        memory_resp = self.client.get("/memory/download")
        self.assertEqual(memory_resp.status_code, 200)
        self.assertIn('attachment; filename="MEMORY.md"', memory_resp.headers.get("content-disposition", ""))
        self.assertIn("Download support matters", memory_resp.text)

        pref_resp = self.client.get("/preferences/download")
        self.assertEqual(pref_resp.status_code, 200)
        self.assertIn('attachment; filename="PREFERENCES.md"', pref_resp.headers.get("content-disposition", ""))
        self.assertIn("Prefer file downloads", pref_resp.text)

    def test_anatomy_download_supports_both_formats(self):
        json_resp = self.client.get("/anatomy/demo/download?format=json")
        self.assertEqual(json_resp.status_code, 200)
        self.assertIn('attachment; filename="demo.json"', json_resp.headers.get("content-disposition", ""))
        self.assertIn('"root":"/tmp/demo"', json_resp.text)

        md_resp = self.client.get("/anatomy/demo/download?format=md")
        self.assertEqual(md_resp.status_code, 200)
        self.assertIn('attachment; filename="demo.md"', md_resp.headers.get("content-disposition", ""))
        self.assertIn("# Anatomy demo", md_resp.text)

    def test_doc_download_rejects_path_traversal(self):
        resp = self.client.get("/docs/../../secret/download")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
