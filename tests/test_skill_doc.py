import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


class SkillDocTests(unittest.TestCase):
    def test_skill_frontmatter_and_retrieval_contract(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        # After the SKILL.md slimming, CLI-flag details legitimately moved into
        # references/cli-reference.md. Flag-level assertions are checked against
        # the union of SKILL.md and the reference docs it links to, so that
        # content living in a linked reference does not count as missing.
        cli_ref = (ROOT / "references" / "cli-reference.md").read_text(encoding="utf-8")
        combined = text + "\n\n" + cli_ref

        match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
        self.assertIsNotNone(match, "SKILL.md must start with a valid YAML frontmatter block")
        self.assertEqual(
            match.group(0),
            (
                "---\n"
                "name: using-memory\n"
                "description: Memory protocol for persisted cross-session context and operation continuity. Use when a task mentions memory, remember, forget, preference, prior context, previous work, continue, resume, project history, saved decisions, logs, operations, commits, pushes, builds, tests, deploys, hooks, or equivalent non-English memory/logging triggers; also use whenever persisted memory could change the answer or the turn may create operation history that should survive restart.\n"
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
        self.assertIn("one JSONL entry for every tool call as a mechanical mirror", text)
        self.assertIn("full temporary command output when a concise result summary is enough", text)
        self.assertIn("scripts/memory_tool.py write-preference", text)
        self.assertIn("scripts/memory_tool.py write-memory", text)
        self.assertIn("scripts/memory_tool.py upsert-doc", text)
        self.assertIn("write-memory` accepts only `fact`, `decision`, and `lesson`", combined)
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
            "`--doc` / `--doc-type` / `--doc-tag` / `--project` / `--topic` / `--doc-query`",
            "`--anatomy`",
            "`status`",
            "`anatomy-list`",
            "`anatomy-register",
            "`anatomy-scan",
        ]:
            with self.subTest(command=command):
                self.assertIn(command, combined)
        self.assertIn("Distill useful patterns from log entries into curated long-term files during light maintenance moments.", text)
        self.assertIn("Only the local primary repo is writable by default", text)
        self.assertIn("Log entries from other namespaces are ignored by default", text)
        self.assertIn("write a log entry for key operation history that should survive restart", text)
        self.assertIn("key concrete operation, state change, verification, issue, fix, decision, commit, push, build, deployment, hook change, config change", text)

        for needle in [
            "## Skill Position",
            "## Config Resolution",
            "## Session Snapshot",
            "## Memory Dimensions",
            "## Anatomy",
            "## Health Dashboard",
            "## Hook Behaviour",
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
            "log_entries",
            "doc_hits",
            "sources",
            "anatomy",
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
        # V2.3 removed local_context from the session snapshot; ensure the
        # SKILL.md no longer advertises it.
        self.assertNotIn("`local_context`", text)
