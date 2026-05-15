import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReadmeTests(unittest.TestCase):
    def test_readme_uses_current_config_and_local_layout(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("memory_roots:", text)
        self.assertIn("role: primary", text)
        # V2.0+ layers
        self.assertIn("<namespace>/anatomy/", text)
        self.assertIn("<namespace>/STATS.json", text)
        # Legacy local/ files were removed in V2.3; the README must not
        # advertise them anymore.
        self.assertNotIn("<namespace>/local/MACHINE.md", text)
        self.assertNotIn("<namespace>/local/ENV.md", text)
        self.assertNotIn("<namespace>/local/WORKSPACE.md", text)
        self.assertNotIn("primary_repo:", text)
        self.assertNotIn("local/<machine-id>/", text)
        self.assertNotIn("namespaces/", text)

    def test_readme_commands_match_cli_flags(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")

        for required in [
            "write-preference \\\n  --config",
            "write-memory \\\n  --config",
            "write-memory \\\n  --config",
            "--date 2026-05-06",
            "--tag fact",
            "upsert-doc \\\n  --config",
            "--doc project-alpha",
            "--doc-type project",
            "--doc-tag planning",
            "write-log \\\n  --config",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, text)

        self.assertNotRegex(text, re.compile(r"(^|\n)\s*--type\s"))
        self.assertNotRegex(text, re.compile(r"\b--tag planning\b"))

    def test_readme_command_overview_lists_all_cli_commands(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")

        for command in [
            "load",
            "search",
            "maintain",
            "stats",
            "status",
            "export",
            "write-log",
            "write-memory",
            "write-preference",
            "upsert-doc",
            "anatomy-register",
            "anatomy-scan",
            "anatomy-show",
            "anatomy-set",
            "anatomy-list",
            "anatomy-upsert-file",
        ]:
            with self.subTest(command=command):
                self.assertIn(f"`{command}`", text)

    def test_project_declares_python_dependency(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("PyYAML", requirements)


if __name__ == "__main__":
    unittest.main()
