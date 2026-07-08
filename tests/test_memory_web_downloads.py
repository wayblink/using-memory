import sys
import subprocess
import tempfile
import unittest
from datetime import datetime
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
                "projects": "",
                "tags": "",
                "summary": "updated doc",
                "body": "# Workflow Updated\n\nEdited.\n",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        index = yaml.safe_load((self.memory_root / "main" / "docs" / "index.json").read_text(encoding="utf-8"))
        entry = index["documents"][0]
        self.assertEqual(entry["created"], "2026-06-20")
        self.assertIn("T", entry["modified"])
        parsed_modified = datetime.fromisoformat(entry["modified"])
        self.assertIsNotNone(parsed_modified.tzinfo)
        self.assertIsNotNone(parsed_modified.utcoffset())
        self.assertEqual(entry["title"], "Workflow Updated")

    def test_doc_timestamps_display_to_minute_and_edit_hides_modified_field(self):
        (self.memory_root / "main" / "docs" / "index.json").write_text(
            '{"version":1,"documents":[{"path":"workflow.md","title":"Workflow","type":"wiki","created":"2026-06-20T09:08:07+08:00","modified":"2026-06-29T10:11:12+08:00","projects":[],"tags":[],"summary":"doc"}]}\n',
            encoding="utf-8",
        )

        index_resp = self.client.get("/docs")
        self.assertEqual(index_resp.status_code, 200)
        self.assertIn("created 2026-06-20 09:08", index_resp.text)
        self.assertIn("modified 2026-06-29 10:11", index_resp.text)
        self.assertNotIn("2026-06-20T09:08:07+08:00", index_resp.text)

        view_resp = self.client.get("/docs/workflow.md")
        self.assertEqual(view_resp.status_code, 200)
        self.assertIn("created 2026-06-20 09:08", view_resp.text)
        self.assertIn("modified 2026-06-29 10:11", view_resp.text)

        edit_resp = self.client.get("/docs/workflow.md?edit=1")
        self.assertEqual(edit_resp.status_code, 200)
        self.assertNotIn('name="modified"', edit_resp.text)
        self.assertIn("2026-06-20 09:08", edit_resp.text)

    def test_doc_view_falls_back_to_modified_when_created_missing(self):
        (self.memory_root / "main" / "docs" / "index.json").write_text(
            '{"version":1,"documents":[{"path":"workflow.md","title":"Workflow","type":"wiki","modified":"2026-06-29","projects":[],"tags":[],"summary":"doc"}]}\n',
            encoding="utf-8",
        )
        resp = self.client.get("/docs/workflow.md")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("created 2026-06-29", resp.text)

    def test_docs_index_exposes_refresh_and_upload_controls(self):
        resp = self.client.get("/docs")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('action="/docs/refresh"', resp.text)
        self.assertIn('<button type="button" class="btn" data-open-modal="docs-upload-dialog"', resp.text)
        self.assertIn('<dialog class="entry-modal docs-upload-modal" id="docs-upload-dialog"', resp.text)
        self.assertIn('action="/docs/upload"', resp.text)
        self.assertIn('name="file"', resp.text)
        self.assertIn('name="replace"', resp.text)
        self.assertNotIn('class="upload-strip"', resp.text)
        self.assertNotIn('reload-btn', resp.text)

    def test_docs_refresh_runs_maintain_and_indexes_disk_files(self):
        (self.memory_root / "main" / "docs" / "dropped.md").write_text(
            "# Dropped\n\nAdded outside the index.\n",
            encoding="utf-8",
        )

        resp = self.client.post("/docs/refresh", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("maintained=1", resp.headers["location"])

        index = yaml.safe_load((self.memory_root / "main" / "docs" / "index.json").read_text(encoding="utf-8"))
        by_path = {entry["path"]: entry for entry in index["documents"]}
        self.assertIn("dropped.md", by_path)
        self.assertEqual(by_path["dropped.md"]["title"], "Dropped")

    def test_docs_upload_writes_file_and_indexes_it(self):
        resp = self.client.post(
            "/docs/upload",
            files={"file": ("uploaded.md", b"# Uploaded\n\nBody.\n", "text/markdown")},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/docs/uploaded.md")

        uploaded = self.memory_root / "main" / "docs" / "uploaded.md"
        self.assertEqual(uploaded.read_text(encoding="utf-8"), "# Uploaded\n\nBody.\n")
        index = yaml.safe_load((self.memory_root / "main" / "docs" / "index.json").read_text(encoding="utf-8"))
        by_path = {entry["path"]: entry for entry in index["documents"]}
        self.assertIn("uploaded.md", by_path)
        self.assertEqual(by_path["uploaded.md"]["title"], "Uploaded")


if __name__ == "__main__":
    unittest.main()
