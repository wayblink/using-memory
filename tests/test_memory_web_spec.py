"""Web UI for SPEC: global and per-project rule scopes.

Rules live in two different files depending on scope, so the page has to keep
track of which one an edit touches. Getting this wrong is destructive rather
than merely cosmetic: an edit aimed at a project rule that lands in the global
file silently changes behaviour for every other repository.
"""

from __future__ import annotations

import json
import subprocess
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

from memory_web.app import create_app  # noqa: E402


class SpecScopeWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory_root = base / "memories"
        self.memory_root.mkdir(parents=True)
        # Writes are only allowed into a git repo; the web write path enforces it.
        subprocess.run(["git", "init", "-q", str(self.memory_root)], check=True)
        self.ns = self.memory_root / "main"
        (self.ns / "docs").mkdir(parents=True)
        (self.ns / "log").mkdir()
        (self.ns / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (self.ns / "SPEC.md").write_text(
            "# Spec\n\nPreamble that is not a rule.\n\n"
            "- [2026-10-01] global rule one\n"
            "- [2026-10-02] global rule two\n",
            encoding="utf-8",
        )
        (self.ns / "spec").mkdir()
        (self.ns / "spec" / "dozo.md").write_text(
            "# Spec — dozo\n\nConstraints for dozo.\n\n"
            "- [2026-10-03] dozo rule one\n",
            encoding="utf-8",
        )
        (self.ns / "docs" / "index.json").write_text(json.dumps([]), encoding="utf-8")
        self.config_path = base / "config.yaml"
        self.config_path.write_text(
            yaml.safe_dump(
                {
                    "memory_roots": [
                        {
                            "path": str(self.memory_root),
                            "role": "primary",
                            "writable": True,
                            "namespace": "main",
                            "machine_id": "test",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.client = TestClient(create_app(config_path=str(self.config_path)))

    def tearDown(self) -> None:
        self.client.close()
        self.tmp.cleanup()

    def test_default_page_shows_global_rules(self):
        resp = self.client.get("/spec")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("global rule one", resp.text)
        self.assertIn("global rule two", resp.text)
        # A project rule must not leak into the global view.
        self.assertNotIn("dozo rule one", resp.text)

    def test_project_scope_shows_only_its_own_rules(self):
        resp = self.client.get("/spec?scope=dozo")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("dozo rule one", resp.text)
        self.assertNotIn("global rule one", resp.text)

    def test_scope_tabs_are_rendered(self):
        resp = self.client.get("/spec")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('href="/spec?scope=global"', resp.text)
        self.assertIn('href="/spec?scope=dozo"', resp.text)

    def test_append_to_project_scope_writes_that_file(self):
        resp = self.client.post(
            "/spec/append",
            data={"text": "dozo rule two", "when": "2026-10-24", "scope": "dozo"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        dozo = (self.ns / "spec" / "dozo.md").read_text(encoding="utf-8")
        self.assertIn("dozo rule two", dozo)
        # The global file must be untouched.
        global_text = (self.ns / "SPEC.md").read_text(encoding="utf-8")
        self.assertNotIn("dozo rule two", global_text)

    def test_append_to_global_scope_writes_spec_md(self):
        resp = self.client.post(
            "/spec/append",
            data={"text": "third global rule", "when": "2026-10-24", "scope": "global"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        global_text = (self.ns / "SPEC.md").read_text(encoding="utf-8")
        self.assertIn("third global rule", global_text)

    def test_unknown_scope_falls_back_to_global_instead_of_crashing(self):
        """A stale tab can submit a scope whose file was deleted."""
        resp = self.client.get("/spec?scope=deleted-repo")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("global rule one", resp.text)

    def test_delete_removes_from_the_right_file(self):
        resp = self.client.post(
            "/spec/delete/5",  # dozo.md line 5: heading, blank, preamble, blank, rule
            data={"scope": "dozo"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        dozo = (self.ns / "spec" / "dozo.md").read_text(encoding="utf-8")
        self.assertNotIn("dozo rule one", dozo)
        # Global rules survive a project-scope delete.
        global_text = (self.ns / "SPEC.md").read_text(encoding="utf-8")
        self.assertIn("global rule one", global_text)

    def test_legacy_route_redirects_to_spec(self):
        resp = self.client.get("/preferences", follow_redirects=False)
        self.assertEqual(resp.status_code, 301)
        self.assertTrue(resp.headers["location"].startswith("/spec"))

    def test_preamble_is_not_offered_as_an_editable_rule(self):
        resp = self.client.get("/spec")
        self.assertNotIn("Preamble that is not a rule", resp.text)


if __name__ == "__main__":
    unittest.main()
