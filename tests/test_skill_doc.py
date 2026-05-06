import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


class SkillDocTests(unittest.TestCase):
    def test_skill_frontmatter_and_startup_contract(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

        match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
        self.assertIsNotNone(match, "SKILL.md must start with a valid YAML frontmatter block")
        self.assertEqual(
            match.group(0),
            (
                "---\n"
                "name: using-memory\n"
                "description: Use when starting any conversation, before responding to tasks, to load and maintain shared global memory from configured Git-managed Markdown repos\n"
                "---\n"
            ),
        )

        self.assertIn("Load memory before handling the task.", text)
        self.assertIn("Startup comes first", text)
        self.assertIn("Load order is strict and must happen in this exact sequence:", text)
        self.assertIn("On-demand document loading is allowed only when the user task clearly matches entries in `docs/index.json`.", text)
        self.assertIn("load --daily-from/--daily-to", text)
        self.assertIn("load --daily-days", text)
        self.assertIn("load --daily-query", text)

        self.assertIn("Never write:", text)
        self.assertIn("every turn", text)
        self.assertIn("every tool call", text)
        self.assertIn("temporary command output", text)
        self.assertIn("scripts/memory_tool.py write-preference", text)
        self.assertIn("scripts/memory_tool.py write-memory", text)
        self.assertIn("scripts/memory_tool.py upsert-doc", text)
        self.assertIn("write-memory` accepts only `fact`, `decision`, and `lesson`", text)
        self.assertIn("Open issues, parking points, unresolved risks, and temporary execution context stay in daily notes or an indexed `docs/` todo/plan", text)
        self.assertIn("## Hot Write Rules", text)
        self.assertIn("## Maintenance Rules", text)
        self.assertIn("Routing:", text)
        self.assertIn("Never write:", text)
        self.assertLess(text.index("Never write:"), text.index("## Maintenance Rules"))
        never_block = text.split("Never write:", 1)[1].split("## Maintenance Rules", 1)[0]
        self.assertNotIn("Distill useful patterns", never_block)
        self.assertIn(
            "Distill useful patterns from daily notes into curated long-term files during light maintenance moments.",
            text.split("## Maintenance Rules", 1)[1],
        )
        self.assertIn("## Memory Tool Commands", text)
        for command in [
            "`load`",
            "`write-daily`",
            "`write-memory`",
            "`write-preference`",
            "`upsert-doc`",
            "`--daily-from` + `--daily-to`",
            "`--daily-days`",
            "`--daily-query`",
            "`--doc` / `--doc-type` / `--doc-tag` / `--project` / `--doc-query`",
        ]:
            with self.subTest(command=command):
                self.assertIn(command, text)
        self.assertIn("Distill useful patterns from daily notes into curated long-term files during light maintenance moments.", text)
        self.assertIn("Only the local primary repo is writable by default", text)
        self.assertIn("Daily notes from other machines are ignored by default", text)
        self.assertIn("Write only when information is worth preserving", text)

        for needle in [
            "## Root Skill Position",
            "## Config Resolution",
            "## Session Snapshot",
            "references/repo-layout.md",
            "references/startup-and-write-rules.md",
            "references/machine-setup.md",
            "Codex or Claude Code startup",
            "parallel root skills",
            "host startup wiring",
            "USING_MEMORY_CONFIG",
            "~/.skills/using-memory/config.yaml",
            "preferences",
            "durable_memory",
            "local_context",
            "doc_hits",
            "sources",
            "skip",
            "append_daily",
            "append_daily_and_queue_distill",
            "write_long_term_now",
            "no-memory mode",
            "do not block the session",
            "add a warning that setup is needed",
        ]:
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
