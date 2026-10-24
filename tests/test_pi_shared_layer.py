"""Regression guards for the shared hook layer after the Pi integration.

The Pi work added a `host` parameter to the reminder and gate copy, and made
`_memory_tool_path()` resolve instead of hardcoding `~/.claude/...`. Codex and
Claude Code consume both, so the contract these tests protect is blunt: an
un-parameterised call must produce the exact string it produced before Pi
existed. If someone later "tidies" the wording, these fail and they have to
think about the two hosts already in production.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "hooks"))

import memory_hook_common as hook  # noqa: E402


# Frozen copies of the pre-Pi strings. Do not regenerate these from the source —
# that would make the test pass by definition.
GENERIC_REMINDER = (
    "using-memory hook reminder: consider the using-memory skill for persisted context. "
    "Load memory only when it can change the answer. For writes, default toward recording "
    "concrete operations and key events to <namespace>/log/YYYY-MM-DD.jsonl via "
    "scripts/memory_tool.py write-log. Do not mirror every tool call or raw transcript. "
    "Rules go to write-preference with --scope global (SPEC.md, every project) or --scope <repo> "
    "(spec/<repo>.md, that repo only); stable facts, confirmed decisions, and lessons go to write-memory."
)


class HostAwareCopyTests(unittest.TestCase):
    def test_unparameterised_reminder_is_unchanged(self):
        self.assertEqual(hook.memory_protocol_reminder(), GENERIC_REMINDER)
        self.assertEqual(hook.memory_protocol_reminder("generic"), GENERIC_REMINDER)

    def test_other_hosts_still_get_the_script_instruction(self):
        for host in ("codex", "claude", "generic"):
            self.assertIn("scripts/memory_tool.py write-log", hook.memory_protocol_reminder(host))

    def test_pi_reminder_names_the_tool_not_the_script(self):
        text = hook.memory_protocol_reminder("pi")
        self.assertIn("`umem` tool", text)
        self.assertIn("action=write-log", text)
        self.assertNotIn("scripts/memory_tool.py", text)

    def test_unparameterised_gate_reason_is_unchanged(self):
        events = ["Bash: git commit -m x", "Edit: /tmp/a.py"]
        text = hook.stop_gate_reason(events, "done")
        self.assertTrue(
            text.startswith(
                "Before stopping, run scripts/memory_tool.py write-log to record this turn: "
                "2 important event(s) [Bash, Edit]."
            ),
            text,
        )

    def test_unparameterised_gate_reason_without_events_is_unchanged(self):
        self.assertEqual(
            hook.stop_gate_reason([], ""),
            "Before stopping, run scripts/memory_tool.py write-log to record this turn's "
            "concrete operations, result, identifiers, verification, and unresolved risks.",
        )

    def test_pi_gate_reason_names_the_tool(self):
        text = hook.stop_gate_reason(["Bash: pytest"], "done", None, "pi")
        self.assertTrue(text.startswith("Before stopping, call the `umem` tool with action=write-log"), text)
        self.assertIn("1 important event(s) [Bash]", text)
        self.assertNotIn("scripts/memory_tool.py", text)

    def test_pi_gate_reason_still_carries_distill_candidates(self):
        text = hook.stop_gate_reason([], "", "## Distill candidates", "pi")
        self.assertIn("## Distill candidates", text)


class PiSettingsTests(unittest.TestCase):
    """`pi_settings()` reads config; with no config file the defaults apply."""

    def setUp(self):
        self._saved = hook._read_memory_config
        self._saved_env = hook.os.environ.get("USING_MEMORY_CONFIG")

    def tearDown(self):
        hook._read_memory_config = self._saved
        if self._saved_env is None:
            hook.os.environ.pop("USING_MEMORY_CONFIG", None)
        else:
            hook.os.environ["USING_MEMORY_CONFIG"] = self._saved_env

    def test_defaults(self):
        hook._read_memory_config = lambda: {}
        settings = hook.pi_settings()
        self.assertEqual(settings["gate"], "message")
        self.assertEqual(settings["detail_turn_interval"], 30)
        self.assertFalse(settings["silent_summary"])
        self.assertTrue(settings["inject_preferences"])
        self.assertTrue(settings["brief_snapshot"])
        self.assertIsNone(settings["memory_tool_path"])

    def test_pi_block_overrides(self):
        hook._read_memory_config = lambda: {
            "pi": {
                "gate": "off",
                "detail_turn_interval": 5,
                "silent_summary": True,
                "brief_snapshot": False,
                "memory_tool_path": "/opt/umem/memory_tool.py",
            }
        }
        settings = hook.pi_settings()
        self.assertEqual(settings["gate"], "off")
        self.assertEqual(settings["detail_turn_interval"], 5)
        self.assertTrue(settings["silent_summary"])
        self.assertFalse(settings["brief_snapshot"])
        self.assertEqual(settings["memory_tool_path"], "/opt/umem/memory_tool.py")

    def test_invalid_gate_value_falls_back_to_message(self):
        hook._read_memory_config = lambda: {"pi": {"gate": "banana"}}
        self.assertEqual(hook.pi_settings()["gate"], "message")

    def test_interval_must_be_positive(self):
        hook._read_memory_config = lambda: {"pi": {"detail_turn_interval": 0}}
        self.assertEqual(hook.pi_settings()["detail_turn_interval"], 30)


class MemoryToolPathTests(unittest.TestCase):
    def test_explicit_path_wins_when_it_exists(self):
        target = ROOT / "scripts" / "memory_tool.py"
        self.assertEqual(hook.resolve_memory_tool_path(str(target)), str(target))

    def test_falls_back_to_this_checkout(self):
        # No explicit path and no env config in the test environment: the
        # function must still find the CLI inside its own skill tree rather
        # than returning Claude's path unconditionally (the pre-Pi bug).
        import os

        saved = os.environ.pop("USING_MEMORY_CONFIG", None)
        try:
            resolved = hook.resolve_memory_tool_path(None)
        finally:
            if saved is not None:
                os.environ["USING_MEMORY_CONFIG"] = saved
        self.assertTrue(Path(resolved).is_file(), resolved)
        self.assertEqual(Path(resolved).name, "memory_tool.py")


if __name__ == "__main__":
    unittest.main()
