"""SPEC.md + spec/<repo>.md read/write behaviour.

The rule file is split by scope: `SPEC.md` holds rules that apply to every
project, `spec/<repo>.md` holds rules that apply only inside that repository.
These tests pin the two properties that make the split worth having:

1. The project spec resolves by **repository**, not by working directory, so a
   rule does not silently disappear when the agent is three subdirectories deep.
2. A repository without a spec file is the ordinary case and must load cleanly.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "memory_tool.py"


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)


class SpecScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mem = self.root / "mem"
        git_init(self.mem)
        (self.mem / "main").mkdir(parents=True, exist_ok=True)
        self.cfg = self.root / "cfg.yaml"
        self.cfg.write_text(
            "version: 1\n"
            "memory_roots:\n"
            f"  - path: {self.mem}\n"
            "    role: primary\n"
            "    writable: true\n"
            "    namespace: main\n"
            "    machine_id: test\n"
            "    priority: 100\n"
            "defaults:\n"
            "  read_today: false\n"
            "  read_yesterday: false\n",
            encoding="utf-8",
        )
        self.memroot = self.mem / "main"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # -- helpers ---------------------------------------------------------

    def write(self, text: str, scope: str | None = None, cwd: Path | None = None):
        args = ["write-preference", "--config", str(self.cfg), "--text", text]
        if scope is not None:
            args += ["--scope", scope]
        return run(args, cwd or self.root)

    def spec_sources(self, cwd: Path) -> list[tuple[str, bool]]:
        out = run(["load", "--config", str(self.cfg), "--json"], cwd)
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        return [
            (s["type"], s["loaded"])
            for s in data["sources"]
            if s["type"] == "preferences" or s["type"].startswith("spec:")
        ]

    # -- write path ------------------------------------------------------

    def test_global_scope_writes_spec_md(self):
        out = self.write("always use tabs", scope="global")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue((self.memroot / "SPEC.md").is_file())
        body = (self.memroot / "SPEC.md").read_text(encoding="utf-8")
        self.assertIn("always use tabs", body)
        self.assertIn("# Spec", body)

    def test_default_scope_is_global(self):
        out = self.write("no scope given")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue((self.memroot / "SPEC.md").is_file())
        self.assertFalse((self.memroot / "spec").exists())

    def test_repo_scope_writes_project_file(self):
        out = self.write("clean test workspaces", scope="dozo")
        self.assertEqual(out.returncode, 0, out.stderr)
        target = self.memroot / "spec" / "dozo.md"
        self.assertTrue(target.is_file())
        body = target.read_text(encoding="utf-8")
        self.assertIn("clean test workspaces", body)
        self.assertIn("dozo", body)
        # The global file must not gain the project rule (it may not exist yet).
        if (self.memroot / "SPEC.md").is_file():
            global_body = (self.memroot / "SPEC.md").read_text(encoding="utf-8")
            self.assertNotIn("clean test workspaces", global_body)

    def test_invalid_scope_is_rejected_and_writes_nothing(self):
        out = self.write("nope", scope="Bad Name")
        self.assertEqual(out.returncode, 2)
        self.assertIn("invalid --scope", out.stderr)
        self.assertFalse((self.memroot / "SPEC.md").exists())
        self.assertFalse((self.memroot / "spec").exists())

    # -- read path -------------------------------------------------------

    def test_repo_spec_loaded_inside_matching_repo(self):
        self.write("global rule", scope="global")
        self.write("dozo rule", scope="dozo")
        work = self.root / "dozo"
        git_init(work)
        types = self.spec_sources(work)
        self.assertIn(("preferences", True), types)
        self.assertIn(("spec:dozo", True), types)

    def test_repo_spec_not_loaded_in_other_repo(self):
        self.write("global rule", scope="global")
        self.write("dozo rule", scope="dozo")
        work = self.root / "unrelated"
        git_init(work)
        types = self.spec_sources(work)
        self.assertIn(("preferences", True), types)
        self.assertNotIn("spec:dozo", [t for t, _ in types])

    def test_repo_spec_resolves_from_nested_subdirectory(self):
        """Scoping must follow the repository root, not the cwd name."""
        self.write("dozo rule", scope="dozo")
        work = self.root / "dozo"
        git_init(work)
        nested = work / "a" / "b"
        nested.mkdir(parents=True)
        types = self.spec_sources(nested)
        self.assertIn(("spec:dozo", True), types)

    def test_repo_without_spec_file_loads_cleanly(self):
        """No spec file is normal, not an error, and must not add a source row."""
        self.write("global rule", scope="global")
        work = self.root / "bare"
        git_init(work)
        out = run(["load", "--config", str(self.cfg), "--json"], work)
        self.assertEqual(out.returncode, 0, out.stderr)
        types = [t for t, _ in self.spec_sources(work)]
        self.assertEqual(types, ["preferences"])

    def test_explicit_project_overrides_cwd(self):
        self.write("dozo rule", scope="dozo")
        work = self.root / "unrelated"
        git_init(work)
        out = run(
            ["load", "--config", str(self.cfg), "--project", "dozo", "--json"], work
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        types = [s["type"] for s in data["sources"]]
        self.assertIn("spec:dozo", types)

    def test_legacy_preferences_md_still_read(self):
        """An un-migrated namespace keeps its rules readable."""
        (self.memroot / "PREFERENCES.md").write_text(
            "# Preferences\n\n- [2026-01-01] legacy rule\n", encoding="utf-8"
        )
        work = self.root / "bare"
        git_init(work)
        out = run(["load", "--config", str(self.cfg), "--json"], work)
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        pref = [s for s in data["sources"] if s["type"] == "preferences"][0]
        self.assertTrue(pref["loaded"])
        self.assertIn("legacy rule", pref["content"])
        self.assertTrue(pref["path"].endswith("PREFERENCES.md"))

    def test_spec_md_wins_over_legacy_when_both_exist(self):
        """Never read both: double-sourcing is what the split exists to remove."""
        self.write("new rule", scope="global")
        (self.memroot / "PREFERENCES.md").write_text(
            "# Preferences\n\n- [2026-01-01] legacy rule\n", encoding="utf-8"
        )
        work = self.root / "bare"
        git_init(work)
        out = run(["load", "--config", str(self.cfg), "--json"], work)
        data = json.loads(out.stdout)
        pref = [s for s in data["sources"] if s["type"] == "preferences"]
        self.assertEqual(len(pref), 1)
        self.assertIn("new rule", pref[0]["content"])
        self.assertNotIn("legacy rule", pref[0]["content"])


if __name__ == "__main__":
    unittest.main()


class MemoryProjectTagWriteTests(unittest.TestCase):
    """write-memory --project tags an entry; a bad tag is rejected, not repaired."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mem = self.root / "mem"
        git_init(self.mem)
        (self.mem / "main").mkdir(parents=True, exist_ok=True)
        self.cfg = self.root / "cfg.yaml"
        self.cfg.write_text(
            "version: 1\nmemory_roots:\n"
            f"  - path: {self.mem}\n    role: primary\n    writable: true\n"
            "    namespace: main\n    machine_id: test\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, text: str, *projects: str):
        args = ["write-memory", "--config", str(self.cfg), "--date", "2026-10-24",
                "--tag", "fact", "--text", text]
        for p in projects:
            args += ["--project", p]
        return run(args, self.root)

    def test_no_project_writes_a_cross_cutting_entry(self):
        out = self.write("general")
        self.assertEqual(out.returncode, 0, out.stderr)
        body = (self.mem / "main" / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("[fact|2026-10-24] general", body)

    def test_one_project_is_recorded(self):
        out = self.write("scoped", "dozo")
        self.assertEqual(out.returncode, 0, out.stderr)
        body = (self.mem / "main" / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("[fact|2026-10-24|dozo] scoped", body)

    def test_several_projects_are_recorded(self):
        """One entry may relate to more than one repository."""
        out = self.write("shared", "dozo", "civil-forest")
        self.assertEqual(out.returncode, 0, out.stderr)
        body = (self.mem / "main" / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("[fact|2026-10-24|dozo,civil-forest] shared", body)

    def test_invalid_project_is_rejected_not_rewritten(self):
        """'Bad Name' must not become 'badname' — a rewritten tag never matches."""
        out = self.write("nope", "Bad Name")
        self.assertEqual(out.returncode, 2)
        self.assertIn("invalid project", out.stderr)
        self.assertFalse((self.mem / "main" / "MEMORY.md").exists())
