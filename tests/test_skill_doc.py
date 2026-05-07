import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


class SkillDocTests(unittest.TestCase):
    def test_skill_frontmatter_and_retrieval_contract(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

        match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
        self.assertIsNotNone(match, "SKILL.md must start with a valid YAML frontmatter block")
        self.assertEqual(
            match.group(0),
            (
                "---\n"
                "name: using-memory\n"
                "description: Use when a task needs persisted cross-session context, saved user preferences, prior decisions, project memory, or explicit memory read/write/search/maintenance.\n"
                "---\n"
            ),
        )

        self.assertIn("## Retrieval Contract", text)
        self.assertIn("Do not load memory by default for every conversation or every turn.", text)
        self.assertIn("Use this skill only when memory could change the answer", text)
        self.assertIn("Skip this skill for greetings", text)
        self.assertIn("isolated coding tasks with enough local context", text)
        self.assertIn("When memory loading is needed, load order is strict and must happen in this exact sequence:", text)
        self.assertIn("On-demand document loading is allowed only when the user task clearly matches entries in `<namespace>/docs/index.json`.", text)
        self.assertIn("load --log-from/--log-to", text)
        self.assertIn("load --log-days", text)
        self.assertIn("load --log-query", text)

        self.assertIn("Never write:", text)
        self.assertIn("every turn", text)
        self.assertIn("every tool call", text)
        self.assertIn("temporary command output", text)
        self.assertIn("scripts/memory_tool.py write-preference", text)
        self.assertIn("scripts/memory_tool.py write-memory", text)
        self.assertIn("scripts/memory_tool.py upsert-doc", text)
        self.assertIn("write-memory` accepts only `fact`, `decision`, and `lesson`", text)
        self.assertIn(
            "Open issues",
            text,
        )
        self.assertIn(
            "parking points",
            text,
        )
        self.assertIn(
            "unresolved risks",
            text,
        )
        self.assertIn("## Write Strategy", text)
        self.assertIn("## Maintenance Rules", text)
        self.assertIn("Routing:", text)
        self.assertIn("Never write:", text)
        self.assertLess(text.index("Never write:"), text.index("## Maintenance Rules"))
        never_block = text.split("Never write:", 1)[1].split("## Maintenance Rules", 1)[0]
        self.assertNotIn("Distill useful patterns", never_block)
        self.assertIn(
            "Distill useful patterns from log entries into curated long-term files during light maintenance moments.",
            text.split("## Maintenance Rules", 1)[1],
        )
        self.assertIn("## Memory Tool Commands", text)
        for command in [
            "`load`",
            "`write-log`",
            "`--level detail|summary`",
            "`write-memory`",
            "`write-preference`",
            "`upsert-doc`",
            "`--log-from` + `--log-to`",
            "`--log-days`",
            "`--log-query`",
            "`--doc` / `--doc-type` / `--doc-tag` / `--project` / `--doc-query`",
        ]:
            with self.subTest(command=command):
                self.assertIn(command, text)
        self.assertIn("Distill useful patterns from log entries into curated long-term files during light maintenance moments.", text)
        self.assertIn("Only the local primary repo is writable by default", text)
        self.assertIn("Log entries from other namespaces are ignored by default", text)
        self.assertIn("Write only when information is worth preserving", text)

        for needle in [
            "## Skill Position",
            "## Config Resolution",
            "## Session Snapshot",
            "references/repo-layout.md",
            "references/startup-and-write-rules.md",
            "references/machine-setup.md",
            "exposing the skill to Codex or Claude Code",
            "on-demand context retrieval",
            "Host skill exposure",
            "USING_MEMORY_CONFIG",
            "~/.skills/using-memory/config.yaml",
            "preferences",
            "durable_memory",
            "local_context",
            "log_entries",
            "doc_hits",
            "sources",
            "skip",
            "log_detail",
            "log_summary",
            "write_memory",
            "no-memory mode",
            "do not block the session",
            "add a warning that setup is needed",
        ]:
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
