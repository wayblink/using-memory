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

    def test_default_page_groups_every_file(self):
        """A file is a scope; the default view shows them all, separately."""
        resp = self.client.get("/spec")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("global rule one", resp.text)
        self.assertIn("global rule two", resp.text)
        self.assertIn("dozo rule one", resp.text)
        # Grouped by file, not flattened into one list.
        self.assertIn("SPEC.md", resp.text)
        self.assertIn("spec/dozo.md", resp.text)

    def test_file_mode_narrows_to_one_file(self):
        resp = self.client.get("/spec?scope=dozo&mode=file")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("dozo rule one", resp.text)
        self.assertNotIn("global rule one", resp.text)

    def test_scope_tabs_are_rendered(self):
        resp = self.client.get("/spec")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('href="/spec?scope=global&mode=file"', resp.text)
        self.assertIn('href="/spec?scope=dozo&mode=file"', resp.text)
        # An unfiltered entry so the grouped view is one click away.
        self.assertIn('<a href="/spec"', resp.text)

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

    def test_each_file_block_shows_its_scope(self):
        """Which file a rule came from decides who has to obey it."""
        resp = self.client.get("/spec")
        import re
        scopes = re.findall(r'spec-file-scope">\s*([^<]+?)\s*<', resp.text)
        # The global scope is shown by its label, not the internal "global".
        self.assertIn("All projects", scopes)
        self.assertIn("dozo", scopes)

    def test_page_reports_file_and_entry_counts(self):
        resp = self.client.get("/spec")
        self.assertIn("4", resp.text)  # total entries
        self.assertIn("spec/dozo.md", resp.text)

    def test_the_whole_file_is_editable(self):
        """The file is the unit: its heading and preamble are part of it."""
        resp = self.client.get("/spec")
        self.assertIn('action="/spec/save"', resp.text)
        self.assertIn("spec-file-textarea", resp.text)
        # The heading and preamble are visible in the editor, not stripped.
        self.assertIn("Preamble that is not a rule", resp.text)
        # Rules are no longer rendered as separate cards.
        self.assertNotIn('class="entry-card"', resp.text)


if __name__ == "__main__":
    unittest.main()


class MemoryPageParsingTests(unittest.TestCase):
    """MEMORY entries carry an optional project list; the UI must still see them.

    When the project tag was introduced the web regex was not extended, so every
    tagged entry failed to match and the page reported "MEMORY.md is empty" with
    51 entries on disk. A whole page going blank because a field was added is
    the failure mode this covers.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory_root = base / "memories"
        subprocess.run(["git", "init", "-q", str(self.memory_root)], check=True)
        ns = self.memory_root / "main"
        (ns / "docs").mkdir(parents=True)
        (ns / "log").mkdir()
        (ns / "MEMORY.md").write_text(
            "# Memory\n\n"
            "- [fact] untagged entry\n"
            "- [decision|2026-01-01] dated, no project\n"
            "- [lesson|2026-01-02|dozo] project tagged\n"
            "- [decision|2026-01-03|dozo,iceberg] two projects\n",
            encoding="utf-8",
        )
        (ns / "SPEC.md").write_text("# Spec\n\n- a rule\n", encoding="utf-8")
        (ns / "docs" / "index.json").write_text(json.dumps([]), encoding="utf-8")
        cfg = base / "config.yaml"
        cfg.write_text(
            yaml.safe_dump({"memory_roots": [{"path": str(self.memory_root),
                            "role": "primary", "writable": True,
                            "namespace": "main", "machine_id": "t"}]}),
            encoding="utf-8",
        )
        self.client = TestClient(create_app(config_path=str(cfg)))

    def tearDown(self) -> None:
        self.client.close()
        self.tmp.cleanup()

    def test_every_tag_shape_is_rendered(self):
        resp = self.client.get("/memory")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("untagged entry", resp.text)
        self.assertIn("dated, no project", resp.text)
        self.assertIn("project tagged", resp.text)
        self.assertIn("two projects", resp.text)
        self.assertNotIn("MEMORY.md is empty", resp.text)


class SpecFileSaveTests(unittest.TestCase):
    """Saving writes the whole file, heading and preamble included."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory_root = base / "memories"
        subprocess.run(["git", "init", "-q", str(self.memory_root)], check=True)
        self.ns = self.memory_root / "main"
        (self.ns / "docs").mkdir(parents=True)
        (self.ns / "log").mkdir()
        (self.ns / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (self.ns / "SPEC.md").write_text("# Spec\n\n- one rule\n", encoding="utf-8")
        (self.ns / "spec").mkdir()
        (self.ns / "spec" / "dozo.md").write_text(
            "# Spec — dozo\n\nConstraints for the `dozo` repository.\n\n- dozo rule\n",
            encoding="utf-8",
        )
        (self.ns / "docs" / "index.json").write_text(json.dumps([]), encoding="utf-8")
        cfg = base / "config.yaml"
        cfg.write_text(
            yaml.safe_dump({"memory_roots": [{"path": str(self.memory_root),
                            "role": "primary", "writable": True,
                            "namespace": "main", "machine_id": "t"}]}),
            encoding="utf-8",
        )
        self.client = TestClient(create_app(config_path=str(cfg)))

    def tearDown(self) -> None:
        self.client.close()
        self.tmp.cleanup()

    def test_save_replaces_the_whole_file(self):
        new = "# Spec — dozo\n\nRewritten by the page.\n\n- rule a\n- rule b\n"
        resp = self.client.post(
            "/spec/save", data={"scope": "dozo", "text": new}, follow_redirects=False
        )
        self.assertEqual(resp.status_code, 303)
        body = (self.ns / "spec" / "dozo.md").read_text(encoding="utf-8")
        self.assertIn("Rewritten by the page.", body)
        self.assertIn("- rule b", body)
        self.assertNotIn("dozo rule", body)

    def test_save_does_not_touch_other_files(self):
        before = (self.ns / "SPEC.md").read_text(encoding="utf-8")
        self.client.post("/spec/save", data={"scope": "dozo", "text": "# new\n"})
        self.assertEqual((self.ns / "SPEC.md").read_text(encoding="utf-8"), before)

    def test_save_adds_a_missing_trailing_newline(self):
        self.client.post("/spec/save", data={"scope": "dozo", "text": "# no newline"})
        body = (self.ns / "spec" / "dozo.md").read_text(encoding="utf-8")
        self.assertTrue(body.endswith("\n"))

    def test_textarea_shows_the_file_verbatim(self):
        resp = self.client.get("/spec?scope=dozo&mode=file")
        self.assertIn("Constraints for the `dozo` repository.", resp.text)
        self.assertIn("- dozo rule", resp.text)
