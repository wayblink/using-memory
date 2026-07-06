import sys
import subprocess
import tempfile
import unittest
from datetime import date
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
            '{"version":1,"documents":[{"path":"workflow.md","title":"Workflow","type":"wiki","created":"2026-06-20","modified":"2026-06-29","projects":[],"tags":[],"summary":"doc"}]}\n',
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
        subprocess.run(["git", "init", str(self.memory_root)], check=True, capture_output=True, text=True)
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

    def test_doc_download_rejects_path_traversal(self):
        resp = self.client.get("/docs/../../secret/download")
        self.assertEqual(resp.status_code, 404)

    def test_doc_edit_updates_modified_and_preserves_created(self):
        resp = self.client.post(
            "/docs/save",
            data={
                "slug": "workflow.md",
                "ext": "md",
                "title": "Workflow Updated",
                "doc_type": "wiki",
                "modified": "",
                "projects": "",
                "tags": "",
                "summary": "updated doc",
                "body": "# Workflow Updated\n\nEdited.\n",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        index_text = (self.memory_root / "main" / "docs" / "index.json").read_text(encoding="utf-8")
        self.assertIn('"created": "2026-06-20"', index_text)
        self.assertIn(f'"modified": "{date.today().isoformat()}"', index_text)
        self.assertIn('"title": "Workflow Updated"', index_text)

    def test_doc_view_falls_back_to_modified_when_created_missing(self):
        (self.memory_root / "main" / "docs" / "index.json").write_text(
            '{"version":1,"documents":[{"path":"workflow.md","title":"Workflow","type":"wiki","modified":"2026-06-29","projects":[],"tags":[],"summary":"doc"}]}\n',
            encoding="utf-8",
        )
        resp = self.client.get("/docs/workflow.md")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("created 2026-06-29", resp.text)


if __name__ == "__main__":
    unittest.main()
