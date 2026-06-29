import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


class IntegrationDocTests(unittest.TestCase):
    def test_install_script_refuses_implicit_overwrite_and_excludes_dev_files(self):
        text = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        self.assertIn("USING_MEMORY_INSTALL_FORCE", text)
        self.assertIn("refusing to overwrite existing destination", text)
        self.assertIn("--exclude=.git", text)
        self.assertIn("--exclude=tests", text)
        self.assertIn("--exclude=__pycache__", text)
        self.assertIn("claude_session_start_hook.py", text)
        self.assertNotIn('cp -a "$HERE"/. "$dest"/', text)

    def test_link_script_refuses_to_replace_existing_directory(self):
        text = (ROOT / "scripts" / "link.sh").read_text(encoding="utf-8")
        self.assertIn("refusing to replace existing directory", text)
        self.assertIn('if [ -e "$dest" ] && [ ! -L "$dest" ]; then', text)
        self.assertIn("claude_session_start_hook.py", text)

    def test_machine_setup_mentions_install_and_decision_based_retrieval_behavior(self):
        text = (ROOT / "references/machine-setup.md").read_text(encoding="utf-8")
        for needle in [
            "GEMINI.md",
            "CLAUDE.md",
            "decision-based use",
            "must not force memory loading before every task",
            "new session",
            "scripts/link.sh",
            "scripts/install.sh",
            "codex",
            "claude-code",
            "both",
            "USING_MEMORY_CONFIG",
            "startup-and-write-rules.md",
            "repo-layout.md",
        ]:
            self.assertIn(needle, text)

        wiring_block = re.search(
            r"Edit `~/.codex/superpowers/GEMINI\.md` so it contains these lines in order:\n\n(.*?)\n\nThis exposes the skill for decision-based use",
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(wiring_block, "codex doc must include skill exposure block")
        ordered_lines = [
            line.strip()
            for line in wiring_block.group(1).strip().splitlines()
            if line.strip()
        ]
        self.assertEqual(
            ordered_lines,
            [
                "@../skills/using-memory/SKILL.md",
                "@./skills/using-superpowers/SKILL.md",
                "@./skills/using-superpowers/references/gemini-tools.md",
            ],
            "codex doc must keep skill exposure lines in order",
        )
        base_path = Path("/fakehome/.codex/superpowers/GEMINI.md")
        expected_resolved = [
            Path("/fakehome/.codex/skills/using-memory/SKILL.md"),
            Path("/fakehome/.codex/superpowers/skills/using-superpowers/SKILL.md"),
            Path("/fakehome/.codex/superpowers/skills/using-superpowers/references/gemini-tools.md"),
        ]
        resolved_paths = []
        for line in ordered_lines:
            self.assertTrue(line.startswith("@"), f"each wiring line must be an include: {line}")
            candidate = (base_path.parent / line[1:]).resolve(strict=False)
            resolved_paths.append(candidate)
        self.assertEqual(
            resolved_paths,
            expected_resolved,
            "skill exposure wiring must point to the real skill tree topology relative to GEMINI.md",
        )
        self.assertNotIn("guaranteed ordering", text)
        self.assertNotIn("runs before `using-superpowers` to guarantee", text)
        self.assertNotIn("startup habit", text)
        self.assertNotRegex(text, re.compile(r"before any task-specific SKILL\\.md", re.IGNORECASE))

    def test_machine_setup_mentions_claude_code_as_first_class_host(self):
        text = (ROOT / "references/machine-setup.md").read_text(encoding="utf-8")
        for needle in [
            "same memory repo",
            "first-class hosts",
            "agent-agnostic",
            "~/.claude/skills/using-memory",
            "~/.claude/CLAUDE.md",
            "@./skills/using-memory/SKILL.md",
            "local-primary-write",
            "USING_MEMORY_CONFIG",
            "not a Claude-only memory format",
        ]:
            self.assertIn(needle, text)
        self.assertNotIn("never gets divergent histories", text)

    def test_root_readme_mentions_using_memory(self):
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("using-memory/", text)

    def test_web_readme_mentions_download_endpoints(self):
        text = (ROOT / "web" / "README.md").read_text(encoding="utf-8")
        for needle in [
            "/docs/<rel>/download",
            "/memory/download",
            "/preferences/download",
            "/anatomy/<slug>/download?format=json|md",
        ]:
            self.assertIn(needle, text)
