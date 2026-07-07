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
        self.assertIn("<namespace>/STATS.json", text)
        # Legacy local/ files were removed in V2.3; the README must not
        # advertise them anymore.
        self.assertNotIn("<namespace>/local/MACHINE.md", text)
        self.assertNotIn("<namespace>/local/ENV.md", text)
        self.assertNotIn("<namespace>/local/WORKSPACE.md", text)
        self.assertNotIn("primary_repo:", text)
        self.assertNotIn("local/<machine-id>/", text)
        self.assertNotIn("namespaces/", text)

    def test_readme_lists_commands(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for cmd in ["umem load", "umem search", "umem write-log", "umem write-memory",
                    "umem write-preference", "umem upsert-doc", "umem status"]:
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, readme)
        # Flag details live in `umem <cmd> --help` and references/cli-reference.md,
        # intentionally not duplicated in the README.
        self.assertIn("--help", readme)
        self.assertIn("cli-reference.md", readme)

    def test_cli_reference_documents_flags(self):
        ref = (ROOT / "references" / "cli-reference.md").read_text(encoding="utf-8")
        for needle in ["--date", "--tag", "--doc-type", "--doc-tag", "--project", "--topic"]:
            with self.subTest(needle=needle):
                self.assertIn(needle, ref)

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
        ]:
            with self.subTest(command=command):
                self.assertIn(f"`{command}`", text)

    def test_project_declares_python_dependency(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("PyYAML", requirements)


if __name__ == "__main__":
    unittest.main()
