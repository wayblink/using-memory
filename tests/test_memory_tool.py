import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
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

    def namespace_root(self, repo: Path, namespace: str = "main") -> Path:
        return repo / namespace

    def make_repo(self, base: Path, name: str, *, machine_id: str, namespace: str = "main") -> Path:
        repo = base / name
        (repo / ".git").mkdir(parents=True)
        scoped = self.namespace_root(repo, namespace)
        (scoped / "log").mkdir(parents=True)
        (scoped / "local").mkdir()
        (scoped / "docs").mkdir()
        (scoped / "PREFERENCES.md").write_text(f"# prefs {machine_id}\n", encoding="utf-8")
        (scoped / "MEMORY.md").write_text(f"# memory {machine_id}\n", encoding="utf-8")
        (scoped / "log" / "2026-05-06.jsonl").write_text(
            '{"ts":"2026-05-06T00:00:00Z","date":"2026-05-06","tag":"fact","source":"user","text":"today primary machine","confidence":7,"files":[]}\n',
            encoding="utf-8",
        )
        (scoped / "log" / "2026-05-05.jsonl").write_text(
            '{"ts":"2026-05-05T00:00:00Z","date":"2026-05-05","tag":"lesson","source":"user","text":"yesterday primary machine","confidence":8,"files":[]}\n',
            encoding="utf-8",
        )
        (scoped / "local" / "MACHINE.md").write_text(f"# machine {machine_id}\n", encoding="utf-8")
        (scoped / "local" / "ENV.md").write_text(f"# env {machine_id}\n", encoding="utf-8")
        (scoped / "local" / "WORKSPACE.md").write_text(f"# workspace {machine_id}\n", encoding="utf-8")
        (scoped / "docs" / "index.json").write_text(
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
        (scoped / "docs" / "workflow.md").write_text(f"# workflow {machine_id}\n", encoding="utf-8")
        return repo

    def write_config(self, path: Path, primary: Path, reference: Path | None = None, *, namespace: str = "main"):
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
    namespace: {namespace}
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

    def test_load_reads_fixed_sources_and_ignores_reference_log_and_local(self):
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
                    self.namespace_root(primary) / "PREFERENCES.md",
                    self.namespace_root(reference) / "PREFERENCES.md",
                    self.namespace_root(primary) / "MEMORY.md",
                    self.namespace_root(reference) / "MEMORY.md",
                    self.namespace_root(primary) / "docs" / "index.json",
                    self.namespace_root(reference) / "docs" / "index.json",
                    self.namespace_root(primary) / "log" / "2026-05-06.jsonl",
                    self.namespace_root(primary) / "log" / "2026-05-05.jsonl",
                ],
            )
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertNotIn("today reference", serialized)
            self.assertIn("today primary", serialized)
            self.assertEqual(result["doc_hits"], [])

    def test_load_uses_configured_namespace_for_all_memory_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary", namespace="shaipower")
            (primary / "main").mkdir()
            (primary / "main" / "docs").mkdir()
            (primary / "main" / "log").mkdir()
            (primary / "main" / "local").mkdir()
            (primary / "main" / "PREFERENCES.md").write_text("# prefs wrong namespace\n", encoding="utf-8")
            (primary / "main" / "MEMORY.md").write_text("# memory wrong namespace\n", encoding="utf-8")
            (primary / "main" / "docs" / "index.json").write_text(
                json.dumps({"version": 1, "documents": []}),
                encoding="utf-8",
            )
            (primary / "main" / "log" / "2026-05-06.jsonl").write_text(
                '{"ts":"2026-05-06T00:00:00Z","date":"2026-05-06","tag":"fact","source":"user","text":"wrong namespace log","confidence":7,"files":[]}\n',
                encoding="utf-8",
            )
            (primary / "main" / "local" / "ENV.md").write_text("# env wrong namespace\n", encoding="utf-8")
            config = base / "config.yaml"
            self.write_config(config, primary, namespace="shaipower")

            result = self.run_tool("load", "--config", str(config), "--date", "2026-05-06", "--json")

            loaded = self.loaded_paths(result)
            self.assertIn(primary / "shaipower" / "PREFERENCES.md", loaded)
            self.assertIn(primary / "shaipower" / "MEMORY.md", loaded)
            self.assertIn(primary / "shaipower" / "docs" / "index.json", loaded)
            self.assertIn(primary / "shaipower" / "log" / "2026-05-06.jsonl", loaded)
            # local/ files are no longer auto-loaded (V2.3 removed local_context).
            self.assertNotIn(primary / "shaipower" / "local" / "ENV.md", loaded)
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertIn("today primary machine", serialized)
            self.assertNotIn("wrong namespace", serialized)

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
                    self.namespace_root(primary) / "PREFERENCES.md",
                    self.namespace_root(high) / "PREFERENCES.md",
                    self.namespace_root(low) / "PREFERENCES.md",
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
                    self.namespace_root(primary) / "PREFERENCES.md",
                    self.namespace_root(reference) / "PREFERENCES.md",
                    self.namespace_root(primary) / "MEMORY.md",
                    self.namespace_root(reference) / "MEMORY.md",
                    self.namespace_root(primary) / "docs" / "index.json",
                    self.namespace_root(primary) / "docs" / "workflow.md",
                ],
            )
            self.assertEqual(len(result["doc_hits"]), 2)
            self.assertEqual(result["doc_hits"][0]["metadata"]["title"], "Workflow")
            self.assertIn("# workflow primary", result["doc_hits"][0]["content"])

    def test_load_log_range_reads_primary_dates_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            reference = self.make_repo(base, "reference", machine_id="reference")
            (self.namespace_root(primary) / "log" / "2026-05-04.jsonl").write_text(
                '{"ts":"2026-05-04T00:00:00Z","date":"2026-05-04","tag":"fact","source":"user","text":"two days ago primary","confidence":5,"files":[]}\n',
                encoding="utf-8",
            )
            (self.namespace_root(reference) / "log" / "2026-05-04.jsonl").write_text(
                '{"ts":"2026-05-04T00:00:00Z","date":"2026-05-04","tag":"fact","source":"user","text":"two days ago reference","confidence":5,"files":[]}\n',
                encoding="utf-8",
            )
            config = base / "config.yaml"
            self.write_config(config, primary, reference)

            result = self.run_tool(
                "load",
                "--config",
                str(config),
                "--log-from",
                "2026-05-04",
                "--log-to",
                "2026-05-06",
                "--json",
            )

            loaded = self.loaded_paths(result)
            self.assertIn(self.namespace_root(primary) / "log" / "2026-05-04.jsonl", loaded)
            self.assertIn(self.namespace_root(primary) / "log" / "2026-05-05.jsonl", loaded)
            self.assertIn(self.namespace_root(primary) / "log" / "2026-05-06.jsonl", loaded)
            self.assertNotIn(self.namespace_root(reference) / "log" / "2026-05-04.jsonl", loaded)
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertIn("two days ago primary", serialized)
            self.assertNotIn("two days ago reference", serialized)

    def test_load_log_query_with_days_loads_only_matching_primary_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            (self.namespace_root(primary) / "log" / "2026-05-04.jsonl").write_text(
                '{"ts":"2026-05-04T00:00:00Z","date":"2026-05-04","tag":"fact","source":"user","text":"roadmap match primary","confidence":5,"files":[]}\n'
                '{"ts":"2026-05-04T00:00:00Z","date":"2026-05-04","tag":"fact","source":"roadmap-source","text":"same file but text does not match","confidence":5,"files":[]}\n',
                encoding="utf-8",
            )
            (self.namespace_root(primary) / "log" / "2026-05-03.jsonl").write_text(
                '{"ts":"2026-05-03T00:00:00Z","date":"2026-05-03","tag":"fact","source":"user","text":"roadmap outside window","confidence":5,"files":[]}\n',
                encoding="utf-8",
            )
            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool(
                "load",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--log-days",
                "3",
                "--log-query",
                "roadmap",
                "--json",
            )

            loaded = self.loaded_paths(result)
            self.assertEqual(
                [path for path in loaded if path.parent.name == "log"],
                [self.namespace_root(primary) / "log" / "2026-05-04.jsonl"],
            )
            self.assertEqual([entry["text"] for entry in result["log_entries"]], ["roadmap match primary"])
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertIn("roadmap match primary", serialized)
            self.assertNotIn("today primary", serialized)
            self.assertNotIn("yesterday primary", serialized)
            self.assertNotIn("roadmap outside window", serialized)
            self.assertNotIn("same file but text does not match", serialized)

    def test_load_rejects_invalid_log_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            proc = self.run_tool(
                "load",
                "--config",
                str(config),
                "--log-from",
                "2026-05-06",
                "--log-to",
                "2026-05-04",
                "--json",
                expect_ok=False,
            )

            self.assertIn("log range start must be before or equal to end", proc.stderr)

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
                        "--log-from",
                        "not-a-date",
                        "--log-to",
                        "2026-05-06",
                        "--json",
                    ),
                    "invalid --log-from; expected YYYY-MM-DD",
                ),
                (
                    (
                        "write-log",
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
            (self.namespace_root(primary) / "docs" / "index.json").write_text(
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
                "write-log",
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
            (primary / "main").mkdir(parents=True)
            config = base / "config.yaml"
            self.write_config(config, primary)

            proc = self.run_tool(
                "write-log",
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

            self.assertIn("neither memory root nor namespace root is a Git repo", proc.stderr)

    def test_write_log_appends_to_primary_flat_log_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            reference = self.make_repo(base, "reference", machine_id="reference")
            config = base / "config.yaml"
            self.write_config(config, primary, reference)
            reference_before = (self.namespace_root(reference) / "log" / "2026-05-06.jsonl").read_text(encoding="utf-8")

            result = self.run_tool(
                "write-log",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--tag",
                "commit",
                "--text",
                "deterministic writer only targets primary log",
                "--json",
            )

            self.assertTrue(result["changed"])
            self.assertEqual(Path(result["path"]), self.namespace_root(primary) / "log" / "2026-05-06.jsonl")
            self.assertRegex(result["sha256"], r"^[0-9a-f]{64}$")
            primary_text = (self.namespace_root(primary) / "log" / "2026-05-06.jsonl").read_text(encoding="utf-8")
            self.assertIn("deterministic writer only targets primary log", primary_text)
            self.assertIn('"tag": "commit"', primary_text)

    def test_write_log_uses_configured_namespace_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary", namespace="shaipower")
            config = base / "config.yaml"
            self.write_config(config, primary, namespace="shaipower")

            result = self.run_tool(
                "write-log",
                "--config",
                str(config),
                "--date",
                "2026-05-07",
                "--tag",
                "fact",
                "--text",
                "namespaced log write",
                "--json",
            )

            self.assertEqual(Path(result["path"]), primary / "shaipower" / "log" / "2026-05-07.jsonl")
            self.assertFalse((primary / "log" / "2026-05-07.jsonl").exists())
            self.assertIn(
                "namespaced log write",
                (primary / "shaipower" / "log" / "2026-05-07.jsonl").read_text(encoding="utf-8"),
            )

    def test_write_log_supports_namespace_git_repo_under_memory_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = base / "primary"
            namespace_repo = self.make_repo(primary, "main", machine_id="primary", namespace=".")
            config = base / "config.yaml"
            self.write_config(config, primary, namespace="main")

            result = self.run_tool(
                "write-log",
                "--config", str(config),
                "--date", "2026-05-06",
                "--tag", "fix",
                "--text", "repo root namespace write",
                "--json",
            )

            self.assertEqual(Path(result["path"]), namespace_repo / "log" / "2026-05-06.jsonl")
            self.assertFalse((namespace_repo / "main" / "log" / "2026-05-06.jsonl").exists())
            self.assertIn("repo root namespace write", (namespace_repo / "log" / "2026-05-06.jsonl").read_text(encoding="utf-8"))

    def test_write_log_rejects_namespace_root_as_memory_root_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            namespace_repo = self.make_repo(base, "main", machine_id="primary", namespace=".")
            config = base / "config.yaml"
            self.write_config(config, namespace_repo, namespace="main")

            proc = self.run_tool(
                "write-log",
                "--config", str(config),
                "--date", "2026-05-06",
                "--tag", "fix",
                "--text", "bad root",
                "--json",
                expect_ok=False,
            )

            self.assertIn("appears to be a namespace root", proc.stderr)
            self.assertFalse((namespace_repo / "main" / "log" / "2026-05-06.jsonl").exists())

    def test_namespace_dot_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary, namespace=".")

            proc = self.run_tool(
                "write-log",
                "--config", str(config),
                "--date", "2026-05-06",
                "--tag", "fix",
                "--text", "bad namespace",
                "--json",
                expect_ok=False,
            )

            self.assertIn("invalid namespace", proc.stderr)

    def test_write_commands_use_configured_namespace_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary", namespace="shaipower")
            config = base / "config.yaml"
            self.write_config(config, primary, namespace="shaipower")

            memory_result = self.run_tool(
                "write-memory",
                "--config",
                str(config),
                "--date",
                "2026-05-07",
                "--tag",
                "fact",
                "--text",
                "namespaced durable memory",
                "--json",
            )
            preference_result = self.run_tool(
                "write-preference",
                "--config",
                str(config),
                "--text",
                "prefer namespace-separated memory files",
                "--json",
            )
            doc_result = self.run_tool(
                "upsert-doc",
                "--config",
                str(config),
                "--doc",
                "plans/namespace-design",
                "--title",
                "Namespace Design",
                "--doc-type",
                "decision",
                "--modified",
                "2026-05-07",
                "--project",
                "using-memory",
                "--doc-tag",
                "namespace",
                "--summary",
                "Namespace scoped memory layout",
                "--text",
                "# Namespace Design\n\n- All memory files live under the configured namespace.\n",
                "--json",
            )

            self.assertEqual(Path(memory_result["path"]), primary / "shaipower" / "MEMORY.md")
            self.assertEqual(Path(preference_result["path"]), primary / "shaipower" / "PREFERENCES.md")
            self.assertEqual(Path(doc_result["path"]), primary / "shaipower" / "docs" / "plans" / "namespace-design.md")
            self.assertEqual(Path(doc_result["index_path"]), primary / "shaipower" / "docs" / "index.json")
            self.assertFalse((primary / "MEMORY.md").exists())
            self.assertFalse((primary / "PREFERENCES.md").exists())
            self.assertFalse((primary / "docs" / "plans" / "namespace-design.md").exists())

    def test_write_log_records_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            self.run_tool(
                "write-log",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--tag",
                "result",
                "--level",
                "summary",
                "--text",
                "summary level log",
                "--json",
            )

            entries = [
                json.loads(line)
                for line in (self.namespace_root(primary) / "log" / "2026-05-06.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            written = [entry for entry in entries if entry["text"] == "summary level log"]
            self.assertEqual(len(written), 1)
            self.assertEqual(written[0]["level"], "summary")

    def test_write_log_and_memory_append_on_new_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            self.run_tool(
                "write-log",
                "--config",
                str(config),
                "--date",
                "2026-05-06",
                "--tag",
                "fact",
                "--text",
                "line separated log",
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

            log_lines = [json.loads(l) for l in (self.namespace_root(primary) / "log" / "2026-05-06.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            log_texts = [e["text"] for e in log_lines]
            self.assertIn("line separated log", log_texts)

            memory_text = (self.namespace_root(primary) / "MEMORY.md").read_text(encoding="utf-8")
            self.assertIn("line separated memory", memory_text)
            self.assertNotIn("line separated log", memory_text)
            self.assertNotIn("line separated memory", log_texts[:1] + log_texts[1:])

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
                "open issues belong in log or docs",
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
            reference_before = (self.namespace_root(reference) / "PREFERENCES.md").read_text(encoding="utf-8")

            result = self.run_tool(
                "write-preference",
                "--config",
                str(config),
                "--text",
                "prefer concise Chinese replies",
                "--json",
            )

            self.assertTrue(result["changed"])
            self.assertEqual(Path(result["path"]), self.namespace_root(primary) / "PREFERENCES.md")
            primary_text = (self.namespace_root(primary) / "PREFERENCES.md").read_text(encoding="utf-8")
            self.assertIn("- [pref] prefer concise Chinese replies", primary_text)
            self.assertEqual((self.namespace_root(reference) / "PREFERENCES.md").read_text(encoding="utf-8"), reference_before)

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
            self.assertEqual(Path(result["path"]), self.namespace_root(primary) / "docs" / "plans" / "q2-roadmap.md")
            self.assertEqual(Path(result["index_path"]), self.namespace_root(primary) / "docs" / "index.json")
            self.assertEqual(
                (self.namespace_root(primary) / "docs" / "plans" / "q2-roadmap.md").read_text(encoding="utf-8"),
                "# Q2 Roadmap\n\n- Ship docs writer\n",
            )
            index = json.loads((self.namespace_root(primary) / "docs" / "index.json").read_text(encoding="utf-8"))
            entry = next(doc for doc in index["documents"] if doc["path"] == "plans/q2-roadmap.md")
            self.assertEqual(entry["title"], "Q2 Roadmap")
            self.assertEqual(entry["type"], "plan")
            self.assertEqual(entry["modified"], "2026-05-06")
            self.assertEqual(entry["projects"], ["using-memory"])
            self.assertEqual(entry["tags"], ["roadmap"])

    def test_write_log_uses_warning_free_local_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            proc = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    "write-log",
                    "--config", str(config),
                    "--date", "2026-05-06",
                    "--tag", "fact",
                    "--text", "warning-free timestamp",
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            result = json.loads(proc.stdout)
            self.assertEqual(result["changed"], True)
            lines = (self.namespace_root(primary) / "log" / "2026-05-06.jsonl").read_text(encoding="utf-8").splitlines()
            record = json.loads(lines[-1])
            parsed_ts = datetime.fromisoformat(record["ts"])
            self.assertIsNotNone(parsed_ts.tzinfo)
            self.assertIsNotNone(parsed_ts.utcoffset())
            self.assertFalse(record["ts"].endswith("Z"))

    def test_upsert_doc_invalid_metadata_does_not_write_orphan_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            proc = self.run_tool(
                "upsert-doc",
                "--config", str(config),
                "--doc", "plans/bad-title",
                "--title", "",
                "--doc-type", "plan",
                "--modified", "2026-05-06",
                "--text", "# Should not be written\n",
                "--json",
                expect_ok=False,
            )

            self.assertIn("invalid doc metadata", proc.stderr)
            self.assertFalse((self.namespace_root(primary) / "docs" / "plans" / "bad-title.md").exists())

    def test_upsert_doc_invalid_index_does_not_write_orphan_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            (self.namespace_root(primary) / "docs" / "index.json").write_text("{bad json\n", encoding="utf-8")
            config = base / "config.yaml"
            self.write_config(config, primary)

            proc = self.run_tool(
                "upsert-doc",
                "--config", str(config),
                "--doc", "plans/bad-index",
                "--title", "Bad Index",
                "--doc-type", "plan",
                "--modified", "2026-05-06",
                "--text", "# Should not be written\n",
                "--json",
                expect_ok=False,
            )

            self.assertIn("invalid docs index", proc.stderr)
            self.assertFalse((self.namespace_root(primary) / "docs" / "plans" / "bad-index.md").exists())

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

    def test_load_populates_log_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool(
                "load",
                "--config", str(config),
                "--date", "2026-05-06",
                "--json",
            )
            self.assertEqual(result["mode"], "memory")
            self.assertTrue(result["write_enabled"])
            self.assertIsInstance(result["log_entries"], list)
            self.assertGreater(len(result["log_entries"]), 0)
            entry = result["log_entries"][0]
            for key in ("ts", "date", "tag", "source", "text"):
                self.assertIn(key, entry)

            # confirm log_entries is populated from JSONL
            self.assertIsInstance(result["log_entries"], list)
            self.assertGreater(len(result["log_entries"]), 0)
            entry = result["log_entries"][0]
            for key in ("ts", "date", "tag", "source", "text"):
                self.assertIn(key, entry)

            # confirm log_entries text is the structured parsed content
            log_texts = [e["text"] for e in result["log_entries"]]
            self.assertIn("today primary machine", log_texts)

    def test_load_keeps_log_entries_out_of_local_context(self):
        # V2.3 removed local_context entirely. This test now just verifies the
        # parsed log line lands in log_entries and not in some other section.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool(
                "load",
                "--config", str(config),
                "--date", "2026-05-06",
                "--json",
            )

            self.assertNotIn("local_context", result)
            log_texts = [entry["text"] for entry in result["log_entries"]]
            self.assertIn("today primary machine", log_texts)

    def test_load_reports_corrupt_log_jsonl_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            jsonl_path = self.namespace_root(primary) / "log" / "2026-05-06.jsonl"
            jsonl_path.write_text(
                '{"ts":"2026-05-06T00:00:00Z","date":"2026-05-06","tag":"fact","source":"user","text":"valid line","confidence":7,"files":[]}\n'
                "bad json line\n",
                encoding="utf-8",
            )
            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool(
                "load",
                "--config", str(config),
                "--date", "2026-05-06",
                "--json",
            )

            self.assertEqual([entry["text"] for entry in result["log_entries"]], ["valid line", "yesterday primary machine"])
            self.assertTrue(any("invalid log jsonl" in warning for warning in result["warnings"]))
            self.assertTrue(any("2026-05-06.jsonl:2" in warning for warning in result["warnings"]))

    def test_search_hits_docs_memory_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            (self.namespace_root(primary) / "MEMORY.md").write_text("- [fact] deploy-safe test\n", encoding="utf-8")
            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool(
                "search", "deploy-safe",
                "--config", str(config),
                "--log-days", "2",
                "--json",
            )
            sources = {hit["source"] for hit in result["hits"]}
            self.assertGreater(result["total"], 0)
            self.assertIn("MEMORY.md", sources)
            self.assertEqual(result["scope"]["docs"], "primary_and_reference")
            self.assertEqual(result["scope"]["memory"], "primary_and_reference")
            self.assertEqual(result["scope"]["log"], "primary_only")

    def test_search_missing_config_still_reports_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_config = Path(tmp) / "missing.yaml"

            result = self.run_tool(
                "search", "anything",
                "--config", str(missing_config),
                "--json",
            )

            self.assertEqual(result["total"], 0)
            self.assertEqual(result["scope"]["docs"], "primary_and_reference")
            self.assertEqual(result["scope"]["memory"], "primary_and_reference")
            self.assertEqual(result["scope"]["log"], "primary_only")

    def test_search_respects_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            (self.namespace_root(primary) / "MEMORY.md").write_text("- [fact] deploy-safe test\n", encoding="utf-8")
            config = base / "config.yaml"
            self.write_config(config, primary)

            result_no_mem = self.run_tool(
                "search", "deploy-safe",
                "--config", str(config),
                "--no-memory",
                "--json",
            )
            self.assertEqual(result_no_mem["total"], 0)

            today_log = self.namespace_root(primary) / "log" / f"{date.today():%Y-%m-%d}.jsonl"
            today_log.write_text(
                json.dumps({
                    "ts": f"{date.today():%Y-%m-%d}T00:00:00+08:00",
                    "date": f"{date.today():%Y-%m-%d}",
                    "tag": "operation",
                    "source": "user",
                    "text": "search flags live today",
                    "confidence": 7,
                    "files": [],
                }) + "\n",
                encoding="utf-8",
            )

            result_log_only = self.run_tool(
                "search", "search flags live today",
                "--config", str(config),
                "--no-docs", "--no-memory",
                "--json",
            )
            self.assertGreater(result_log_only["total"], 0)
            self.assertTrue(all(h["source"] == "log" for h in result_log_only["hits"]))

    def test_prune_command_is_removed(self):
        proc = self.run_tool("prune", "--json", expect_ok=False)
        self.assertIn("invalid choice", proc.stderr)

    def test_maintain_reports_stale_file_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            jsonl_path = self.namespace_root(primary) / "log" / "2026-05-06.jsonl"
            stale_line = json.dumps({
                "ts": "2026-05-06T00:00:00Z",
                "date": "2026-05-06",
                "tag": "lesson",
                "source": "user",
                "text": "stale reference here",
                "confidence": 5,
                "files": ["stale_file.py"],
            })
            jsonl_path.write_text(stale_line + "\n", encoding="utf-8")

            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool("maintain", "--config", str(config), "--json")
            self.assertGreater(result["ok"], 0)
            self.assertEqual(len(result["stale"]), 1)
            self.assertIn("stale_file.py", result["stale"][0]["file"])

    def test_maintain_rejects_file_references_outside_primary_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            outside = base / "outside.txt"
            outside.write_text("outside exists\n", encoding="utf-8")
            (self.namespace_root(primary) / "log" / "2026-05-07.jsonl").write_text(
                json.dumps({
                    "ts": "2026-05-07T00:00:00Z",
                    "date": "2026-05-07",
                    "tag": "fact",
                    "source": "user",
                    "text": "unsafe refs",
                    "confidence": 7,
                    "files": ["../outside.txt", str(outside)],
                }) + "\n",
                encoding="utf-8",
            )
            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool("maintain", "--config", str(config), "--json")

            unsafe = [item for item in result["stale"] if item.get("text") == "unsafe refs"]
            self.assertEqual(len(unsafe), 2)
            self.assertTrue(all(item.get("error") == "invalid file reference" for item in unsafe))

    def test_maintain_reports_corrupt_jsonl_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            jsonl_path = self.namespace_root(primary) / "log" / "2026-05-06.jsonl"
            jsonl_path.write_text(
                'bad json line here\n',
                encoding="utf-8",
            )

            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool("maintain", "--config", str(config), "--json")
            self.assertEqual(len(result["corrupt"]), 1)
            self.assertEqual(result["corrupt"][0]["line"], 1)

    def test_maintain_indexes_manually_added_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            manual_doc = self.namespace_root(primary) / "docs" / "manual-note.md"
            manual_doc.write_text("# Manual Note\n\nAdded outside the CLI.\n", encoding="utf-8")

            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool("maintain", "--config", str(config), "--json")
            self.assertEqual(
                result["indexed_docs"],
                [{
                    "path": "manual-note.md",
                    "title": "Manual Note",
                    "type": "wiki",
                }],
            )

            index = json.loads((self.namespace_root(primary) / "docs" / "index.json").read_text(encoding="utf-8"))
            manual_entries = [
                entry for entry in index["documents"]
                if entry["path"] == "manual-note.md"
            ]
            self.assertEqual(len(manual_entries), 1)
            self.assertEqual(manual_entries[0]["title"], "Manual Note")
            self.assertEqual(manual_entries[0]["type"], "wiki")
            self.assertEqual(manual_entries[0]["tags"], [])
            self.assertEqual(manual_entries[0]["projects"], [])

    def test_maintain_rejects_non_writable_primary_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            manual_doc = self.namespace_root(primary) / "docs" / "manual-note.md"
            manual_doc.write_text("# Manual Note\n", encoding="utf-8")
            config = base / "config.yaml"
            config.write_text(
                f"""version: 1
memory_roots:
  - path: {primary}
    role: primary
    writable: false
    machine_id: primary-machine
    priority: 100
""",
                encoding="utf-8",
            )

            proc = self.run_tool("maintain", "--config", str(config), "--json", expect_ok=False)

            self.assertIn("primary root is not writable", proc.stderr)
            index = json.loads((self.namespace_root(primary) / "docs" / "index.json").read_text(encoding="utf-8"))
            self.assertNotIn(
                "manual-note.md",
                [entry["path"] for entry in index["documents"]],
            )

    def test_stats_counts_tags_in_log_and_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            # add extra log entry
            extra = {"ts":"2026-05-06T01:00:00Z","date":"2026-05-06","tag":"lesson","source":"user","text":"extra","confidence":3,"files":[]}
            (self.namespace_root(primary) / "log" / "2026-05-06.jsonl").write_text(
                '{"ts":"2026-05-06T00:00:00Z","date":"2026-05-06","tag":"fact","source":"user","text":"extra lesson","confidence":7,"files":[]}\n'
                + json.dumps(extra) + "\n",
                encoding="utf-8",
            )
            (self.namespace_root(primary) / "MEMORY.md").write_text("- [lesson] memory lesson\n", encoding="utf-8")
            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool("stats", "--config", str(config), "--json")
            log = result["log"]
            memory = result["memory"]
            self.assertEqual(log["total"], 3)  # 1 from 2026-05-05 + 2 from 2026-05-06
            self.assertIn("fact", log["by_tag"])
            self.assertIn("lesson", log["by_tag"])
            self.assertEqual(memory["total"], 1)
            self.assertEqual(result["scope"]["log"], "primary_only")
            self.assertEqual(result["scope"]["memory"], "primary_only")

    def test_search_rejects_multiple_primary_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary_a = self.make_repo(base, "primary-a", machine_id="primary-a")
            primary_b = self.make_repo(base, "primary-b", machine_id="primary-b")
            config = base / "config.yaml"
            config.write_text(
                f"""version: 1
memory_roots:
  - path: {primary_a}
    role: primary
    writable: true
  - path: {primary_b}
    role: primary
    writable: true
""",
                encoding="utf-8",
            )

            proc = self.run_tool("search", "anything", "--config", str(config), "--json", expect_ok=False)

            self.assertIn("config must declare exactly one primary root", proc.stderr)

    def test_stats_rejects_multiple_primary_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary_a = self.make_repo(base, "primary-a", machine_id="primary-a")
            primary_b = self.make_repo(base, "primary-b", machine_id="primary-b")
            config = base / "config.yaml"
            config.write_text(
                f"""version: 1
memory_roots:
  - path: {primary_a}
    role: primary
    writable: true
  - path: {primary_b}
    role: primary
    writable: true
""",
                encoding="utf-8",
            )

            proc = self.run_tool("stats", "--config", str(config), "--json", expect_ok=False)

            self.assertIn("config must declare exactly one primary root", proc.stderr)

    def test_export_writes_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool(
                "export",
                "--config", str(config),
                "--json",
            )
            self.assertIn("Project Memory", result["text"])
            self.assertIn("Log JSONL", result["text"])

    def test_export_appends_to_dest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self.make_repo(base, "primary", machine_id="primary")
            dest = Path(tmp) / "SUMMARY.md"
            dest.write_text("# existing\n", encoding="utf-8")
            config = base / "config.yaml"
            self.write_config(config, primary)

            result = self.run_tool(
                "export",
                "--config", str(config),
                "--dest", str(dest),
                "--json",
            )
            self.assertTrue(result["changed"])
            text = dest.read_text(encoding="utf-8")
            self.assertIn("# existing", text)
            self.assertIn("Project Memory", text)


class MemorySetupTests(unittest.TestCase):
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

    def test_setup_initializes_local_git_repo_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = base / "config.yaml"
            memory_root = base / "memories"

            result = self.run_tool(
                "setup",
                "--config", str(config),
                "--path", str(memory_root),
                "--namespace", "work",
                "--machine-id", "laptop",
                "--non-interactive",
                "--json",
            )

            self.assertTrue(result["changed"])
            self.assertEqual(result["git_action"], "initialized")
            self.assertTrue((memory_root / ".git").is_dir())
            self.assertTrue((memory_root / "work" / "MEMORY.md").exists())
            self.assertTrue((memory_root / "work" / "PREFERENCES.md").exists())
            self.assertTrue((memory_root / "work" / "docs" / "index.json").exists())
            self.assertTrue(result["next_steps"], "local setup should remind users to add a remote later")
            text = config.read_text(encoding="utf-8")
            self.assertIn(f"path: {result['memory_root']}", text)
            self.assertIn("namespace: work", text)
            self.assertIn("machine_id: laptop", text)

    def test_setup_clones_remote_git_repo_when_path_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            origin = base / "origin.git"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            config = base / "config.yaml"
            memory_root = base / "checkout"

            result = self.run_tool(
                "setup",
                "--config", str(config),
                "--path", str(memory_root),
                "--remote", str(origin),
                "--namespace", "main",
                "--machine-id", "desktop",
                "--non-interactive",
                "--json",
            )

            self.assertTrue(result["changed"])
            self.assertEqual(result["git_action"], "cloned")
            self.assertEqual(result["remote"], str(origin))
            self.assertTrue((memory_root / ".git").is_dir())
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(memory_root), "remote", "get-url", "origin"],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ).stdout.strip(),
                str(origin),
            )
            # Setup seeds the namespace baseline files; local/* was dropped in V2.3.
            self.assertTrue((memory_root / "main" / "MEMORY.md").exists())
            self.assertTrue((memory_root / "main" / "PREFERENCES.md").exists())
            self.assertTrue((memory_root / "main" / "docs" / "index.json").exists())
            self.assertFalse((memory_root / "main" / "local").exists())
            self.assertIn("remote:", config.read_text(encoding="utf-8"))

    def test_setup_pulls_existing_git_checkout_when_remote_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            origin = base / "origin.git"
            writer = base / "writer"
            checkout = base / "checkout"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "clone", str(origin), str(writer)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "-C", str(writer), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(writer), "config", "user.name", "Test User"], check=True)
            (writer / "README.md").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(writer), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(writer), "commit", "-m", "seed"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "-C", str(writer), "push", "origin", "HEAD:main"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "clone", str(origin), str(checkout)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "-C", str(checkout), "checkout", "main"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            (writer / "new.txt").write_text("new memory repo content\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(writer), "add", "new.txt"], check=True)
            subprocess.run(["git", "-C", str(writer), "commit", "-m", "update"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "-C", str(writer), "push", "origin", "HEAD:main"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            result = self.run_tool(
                "setup",
                "--config", str(base / "config.yaml"),
                "--path", str(checkout),
                "--remote", str(origin),
                "--namespace", "main",
                "--machine-id", "desktop",
                "--non-interactive",
                "--json",
            )

            self.assertEqual(result["git_action"], "pulled")
            self.assertTrue((checkout / "new.txt").exists())
            self.assertTrue((checkout / "main" / "MEMORY.md").exists())


if __name__ == "__main__":
    unittest.main()
