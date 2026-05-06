import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "memory_tool.py"


class MemoryToolBehaviorTests(unittest.TestCase):
    def run_tool(self, *args, expect_ok=True, env=None):
        merged_env = os.environ.copy()
        merged_env.pop("USING_MEMORY_CONFIG", None)
        if env:
            merged_env.update(env)
        proc = subprocess.run(
            [sys.executable, str(TOOL), *args],
            cwd=ROOT,
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if expect_ok:
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        return proc

    def make_repo(self, base: Path, name: str, *, machine_id: str) -> Path:
        repo = base / name
        (repo / ".git").mkdir(parents=True)
        (repo / "daily").mkdir()
        (repo / "local").mkdir()
        (repo / "docs").mkdir()
        (repo / "PREFERENCES.md").write_text(f"# prefs {machine_id}\n", encoding="utf-8")
        (repo / "MEMORY.md").write_text(f"# memory {machine_id}\n", encoding="utf-8")
        (repo / "daily" / "2026-05-06.md").write_text(f"# today {machine_id}\n", encoding="utf-8")
        (repo / "daily" / "2026-05-05.md").write_text(f"# yesterday {machine_id}\n", encoding="utf-8")
        (repo / "local" / "MACHINE.md").write_text(f"# machine {machine_id}\n", encoding="utf-8")
        (repo / "local" / "ENV.md").write_text(f"# env {machine_id}\n", encoding="utf-8")
        (repo / "local" / "WORKSPACE.md").write_text(f"# workspace {machine_id}\n", encoding="utf-8")
        (repo / "docs" / "index.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "documents": [
                        {
                            "path": "workflow.md",
                            "title": "Workflow",
                            "type": "SOP",
                            "modified": "2026-05-06",
                            "projects": ["using-memory"],
                            "tags": ["workflow", machine_id],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (repo / "docs" / "workflow.md").write_text(f"# workflow {machine_id}\n", encoding="utf-8")
        return repo

    def write_config(self, path: Path, primary: Path, reference: Path | None = None):
        refs = ""
        if reference:
            refs = f"""
  - path: {reference}
    role: reference
    writable: false
    machine_id: reference-machine
    priority: 50
"""
        path.write_text(
            f"""version: 1
memory_roots:
  - path: {primary}
    role: primary
    writable: true
    machine_id: primary-machine
    priority: 100
{refs}defaults:
  read_today: true
  read_yesterday: true
  load_docs_on_demand: true
""",
            encoding="utf-8",
        )

    def loaded_paths(self, result):
        return [Path(source["path"]) for source in result["sources"] if source["loaded"]]

    def test_load_reads_fixed_sources_and_ignores_reference_daily_and_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            reference = self.make_repo(base, "reference", machine_id="reference")
            config = base / "config.yaml"
            self.write_config(config, primary, reference)

            result = self.run_tool("load", "--config", str(config), "--date", "2026-05-06", "--json")

            self.assertEqual(result["mode"], "memory")
            self.assertTrue(result["write_enabled"])
            self.assertEqual(
                self.loaded_paths(result),
                [
                    primary / "PREFERENCES.md",
                    reference / "PREFERENCES.md",
                    primary / "MEMORY.md",
                    reference / "MEMORY.md",
                    primary / "docs" / "index.json",
                    reference / "docs" / "index.json",
                    primary / "daily" / "2026-05-06.md",
                    primary / "daily" / "2026-05-05.md",
                    primary / "local" / "MACHINE.md",
                    primary / "local" / "ENV.md",
                    primary / "local" / "WORKSPACE.md",
                ],
            )
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertNotIn("today reference", serialized)
            self.assertNotIn("env reference", serialized)
            self.assertNotIn("workspace reference", serialized)
            self.assertIn("today primary", serialized)
            self.assertEqual(result["doc_hits"], [])

    def test_load_orders_references_by_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            low = self.make_repo(base, "low", machine_id="low")
            high = self.make_repo(base, "high", machine_id="high")
            config = base / "config.yaml"
            config.write_text(
                f"""version: 1
memory_roots:
  - path: {primary}
    role: primary
    writable: true
    machine_id: primary-machine
    priority: 100
  - path: {low}
    role: reference
    writable: false
    machine_id: low-machine
    priority: 10
  - path: {high}
    role: reference
    writable: false
    machine_id: high-machine
    priority: 90
defaults:
  read_today: true
  read_yesterday: true
  load_docs_on_demand: true
""",
                encoding="utf-8",
            )

            result = self.run_tool("load", "--config", str(config), "--date", "2026-05-06", "--json")

            self.assertEqual(
                self.loaded_paths(result)[:3],
                [
                    primary / "PREFERENCES.md",
                    high / "PREFERENCES.md",
                    low / "PREFERENCES.md",
                ],
            )

    def test_load_doc_reads_index_then_matching_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            reference = self.make_repo(base, "reference", machine_id="reference")
            config = base / "config.yaml"
            self.write_config(config, primary, reference)

            result = self.run_tool(
                "load",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--doc",
                "workflow",
                "--json",
            )

            self.assertEqual(
                self.loaded_paths(result)[:6],
                [
                    primary / "PREFERENCES.md",
                    reference / "PREFERENCES.md",
                    primary / "MEMORY.md",
                    reference / "MEMORY.md",
                    primary / "docs" / "index.json",
                    primary / "docs" / "workflow.md",
                ],
            )
            self.assertEqual(len(result["doc_hits"]), 2)
            self.assertEqual(result["doc_hits"][0]["metadata"]["title"], "Workflow")
            self.assertIn("# workflow primary", result["doc_hits"][0]["content"])

    def test_load_daily_range_reads_primary_dates_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            reference = self.make_repo(base, "reference", machine_id="reference")
            (primary / "daily" / "2026-05-04.md").write_text("# two days ago primary\n", encoding="utf-8")
            (reference / "daily" / "2026-05-04.md").write_text("# two days ago reference\n", encoding="utf-8")
            config = base / "config.yaml"
            self.write_config(config, primary, reference)

            result = self.run_tool(
                "load",
                "--config",
                str(config),
                "--daily-from",
                "2026-05-04",
                "--daily-to",
                "2026-05-06",
                "--json",
            )

            loaded = self.loaded_paths(result)
            self.assertIn(primary / "daily" / "2026-05-04.md", loaded)
            self.assertIn(primary / "daily" / "2026-05-05.md", loaded)
            self.assertIn(primary / "daily" / "2026-05-06.md", loaded)
            self.assertNotIn(reference / "daily" / "2026-05-04.md", loaded)
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertIn("two days ago primary", serialized)
            self.assertNotIn("two days ago reference", serialized)

    def test_load_daily_query_with_days_loads_only_matching_primary_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            (primary / "daily" / "2026-05-04.md").write_text("# roadmap match primary\n", encoding="utf-8")
            (primary / "daily" / "2026-05-03.md").write_text("# roadmap outside window\n", encoding="utf-8")
            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool(
                "load",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--daily-days",
                "3",
                "--daily-query",
                "roadmap",
                "--json",
            )

            loaded = self.loaded_paths(result)
            self.assertEqual(
                [path for path in loaded if path.parent.name == "daily"],
                [primary / "daily" / "2026-05-04.md"],
            )
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertIn("roadmap match primary", serialized)
            self.assertNotIn("today primary", serialized)
            self.assertNotIn("yesterday primary", serialized)
            self.assertNotIn("roadmap outside window", serialized)

    def test_load_rejects_invalid_daily_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            proc = self.run_tool(
                "load",
                "--config",
                str(config),
                "--daily-from",
                "2026-05-06",
                "--daily-to",
                "2026-05-04",
                "--json",
                expect_ok=False,
            )

            self.assertIn("daily range start must be before or equal to end", proc.stderr)

    def test_invalid_dates_report_clean_cli_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            cases = [
                (
                    ("load", "--config", str(config), "--date", "not-a-date", "--json"),
                    "invalid --date; expected YYYY-MM-DD",
                ),
                (
                    (
                        "load",
                        "--config",
                        str(config),
                        "--daily-from",
                        "not-a-date",
                        "--daily-to",
                        "2026-05-06",
                        "--json",
                    ),
                    "invalid --daily-from; expected YYYY-MM-DD",
                ),
                (
                    (
                        "write-daily",
                        "--config",
                        str(config),
                        "--date",
                        "not-a-date",
                        "--tag",
                        "fact",
                        "--text",
                        "invalid date should be reported cleanly",
                        "--json",
                    ),
                    "invalid --date; expected YYYY-MM-DD",
                ),
                (
                    (
                        "write-memory",
                        "--config",
                        str(config),
                        "--date",
                        "not-a-date",
                        "--tag",
                        "fact",
                        "--text",
                        "invalid date should be reported cleanly",
                        "--json",
                    ),
                    "invalid --date; expected YYYY-MM-DD",
                ),
            ]

            for args, message in cases:
                with self.subTest(args=args):
                    proc = self.run_tool(*args, expect_ok=False)
                    self.assertIn(message, proc.stderr)
                    self.assertNotIn("Traceback", proc.stderr)

    def test_load_missing_config_degrades_to_no_memory_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_config = Path(tmp) / "missing.yaml"
            result = self.run_tool("load", "--config", str(missing_config), "--date", "2026-05-06", "--json")

            self.assertEqual(result["mode"], "no_memory")
            self.assertFalse(result["write_enabled"])
            self.assertEqual(result["sources"], [])
            self.assertTrue(any("config not found" in warning for warning in result["warnings"]))

    def test_load_missing_env_config_degrades_with_actionable_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_config = Path(tmp) / "missing.yaml"
            result = self.run_tool(
                "load",
                "--date",
                "2026-05-06",
                "--json",
                env={"USING_MEMORY_CONFIG": str(missing_config)},
            )

            self.assertEqual(result["mode"], "no_memory")
            self.assertFalse(result["write_enabled"])
            self.assertTrue(
                any("USING_MEMORY_CONFIG points to missing file" in warning for warning in result["warnings"])
            )
            self.assertTrue(any("create it" in warning for warning in result["warnings"]))

    def test_load_invalid_doc_index_reports_warning_in_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)
            (primary / "docs" / "index.json").write_text(
                json.dumps({"version": 1, "documents": [{"path": "broken.md"}]}),
                encoding="utf-8",
            )

            result = self.run_tool("load", "--config", str(config), "--doc-query", "broken", "--json")

            index_source = next(source for source in result["sources"] if source["type"] == "docs_index")
            self.assertFalse(index_source["loaded"])
            self.assertIn("invalid docs index", index_source["warning"])
            self.assertEqual(result["doc_hits"], [])

    def test_load_rejects_multiple_primary_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = self.make_repo(base, "first", machine_id="first")
            second = self.make_repo(base, "second", machine_id="second")
            config = base / "bad.yaml"
            config.write_text(
                f"""version: 1
memory_roots:
  - path: {first}
    role: primary
    writable: true
    machine_id: first
    priority: 100
  - path: {second}
    role: primary
    writable: true
    machine_id: second
    priority: 90
""",
                encoding="utf-8",
            )

            proc = self.run_tool("load", "--config", str(config), "--date", "2026-05-06", "--json", expect_ok=False)

            self.assertIn("exactly one primary", proc.stderr)

    def test_write_rejects_missing_primary_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            missing = base / "missing"
            config = base / "config.yaml"
            self.write_config(config, missing)

            proc = self.run_tool(
                "write-daily",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--tag",
                "fact",
                "--text",
                "do not create missing roots",
                "--json",
                expect_ok=False,
            )

            self.assertIn("primary root does not exist", proc.stderr)
            self.assertFalse(missing.exists())

    def test_write_rejects_non_git_primary_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = base / "primary"
            primary.mkdir()
            config = base / "config.yaml"
            self.write_config(config, primary)

            proc = self.run_tool(
                "write-daily",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--tag",
                "fact",
                "--text",
                "do not write outside managed git roots",
                "--json",
                expect_ok=False,
            )

            self.assertIn("primary root is not a Git repo", proc.stderr)

    def test_write_daily_appends_to_primary_flat_daily_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            reference = self.make_repo(base, "reference", machine_id="reference")
            config = base / "config.yaml"
            self.write_config(config, primary, reference)
            reference_before = (reference / "daily" / "2026-05-06.md").read_text(encoding="utf-8")

            result = self.run_tool(
                "write-daily",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--tag",
                "decision",
                "--text",
                "deterministic writer only targets primary daily",
                "--json",
            )

            self.assertTrue(result["changed"])
            self.assertEqual(Path(result["path"]), primary / "daily" / "2026-05-06.md")
            self.assertRegex(result["sha256"], r"^[0-9a-f]{64}$")
            primary_text = (primary / "daily" / "2026-05-06.md").read_text(encoding="utf-8")
            self.assertIn("- [decision|2026-05-06] deterministic writer only targets primary daily", primary_text)
            self.assertEqual((reference / "daily" / "2026-05-06.md").read_text(encoding="utf-8"), reference_before)

    def test_write_daily_and_memory_append_on_new_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            self.run_tool(
                "write-daily",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--tag",
                "fact",
                "--text",
                "line separated daily",
                "--json",
            )
            self.run_tool(
                "write-memory",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--tag",
                "fact",
                "--text",
                "line separated memory",
                "--json",
            )

            daily_text = (primary / "daily" / "2026-05-06.md").read_text(encoding="utf-8")
            memory_text = (primary / "MEMORY.md").read_text(encoding="utf-8")
            self.assertIn("# today primary\n- [fact|2026-05-06] line separated daily\n", daily_text)
            self.assertIn("# memory primary\n- [fact|2026-05-06] line separated memory\n", memory_text)
            self.assertNotIn("# today primary- [fact", daily_text)
            self.assertNotIn("# memory primary- [fact", memory_text)

    def test_write_memory_rejects_preference_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            proc = self.run_tool(
                "write-memory",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--tag",
                "pref",
                "--text",
                "preferences belong in PREFERENCES.md",
                "--json",
                expect_ok=False,
            )

            self.assertIn("tag is not allowed for write-memory", proc.stderr)

    def test_write_memory_rejects_issue_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            proc = self.run_tool(
                "write-memory",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--tag",
                "issue",
                "--text",
                "open issues belong in daily or docs",
                "--json",
                expect_ok=False,
            )

            self.assertIn("tag is not allowed for write-memory", proc.stderr)

    def test_write_preference_appends_to_primary_preferences_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            reference = self.make_repo(base, "reference", machine_id="reference")
            config = base / "config.yaml"
            self.write_config(config, primary, reference)
            reference_before = (reference / "PREFERENCES.md").read_text(encoding="utf-8")

            result = self.run_tool(
                "write-preference",
                "--config",
                str(config),
                "--text",
                "prefer concise Chinese replies",
                "--json",
            )

            self.assertTrue(result["changed"])
            self.assertEqual(Path(result["path"]), primary / "PREFERENCES.md")
            primary_text = (primary / "PREFERENCES.md").read_text(encoding="utf-8")
            self.assertIn("- [pref] prefer concise Chinese replies", primary_text)
            self.assertEqual((reference / "PREFERENCES.md").read_text(encoding="utf-8"), reference_before)

    def test_upsert_doc_writes_body_and_updates_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool(
                "upsert-doc",
                "--config",
                str(config),
                "--doc",
                "plans/q2-roadmap",
                "--title",
                "Q2 Roadmap",
                "--doc-type",
                "plan",
                "--modified",
                "2026-05-06",
                "--project",
                "using-memory",
                "--doc-tag",
                "roadmap",
                "--summary",
                "Plan for Q2 using-memory work",
                "--text",
                "# Q2 Roadmap\n\n- Ship docs writer\n",
                "--json",
            )

            self.assertTrue(result["changed"])
            self.assertEqual(Path(result["path"]), primary / "docs" / "plans" / "q2-roadmap.md")
            self.assertEqual(Path(result["index_path"]), primary / "docs" / "index.json")
            self.assertEqual(
                (primary / "docs" / "plans" / "q2-roadmap.md").read_text(encoding="utf-8"),
                "# Q2 Roadmap\n\n- Ship docs writer\n",
            )
            index = json.loads((primary / "docs" / "index.json").read_text(encoding="utf-8"))
            entry = next(doc for doc in index["documents"] if doc["path"] == "plans/q2-roadmap.md")
            self.assertEqual(entry["title"], "Q2 Roadmap")
            self.assertEqual(entry["type"], "plan")
            self.assertEqual(entry["modified"], "2026-05-06")
            self.assertEqual(entry["projects"], ["using-memory"])
            self.assertEqual(entry["tags"], ["roadmap"])

    def test_load_doc_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            proc = self.run_tool(
                "load",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--doc",
                "../secrets",
                "--json",
                expect_ok=False,
            )

            self.assertIn("invalid doc name", proc.stderr)


if __name__ == "__main__":
    unittest.main()
