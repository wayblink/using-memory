"""The `hook-context` CLI surface the Pi extension reads its copy from.

The extension cannot import Python, so it shells out to `hook-context` once per
process to get the reminder and gate wording. That makes this subcommand part of
the Pi contract: if it disappears or changes shape, the extension silently falls
back to its own hard-coded English, and the wording drifts from the other hosts.

The tests here assert the *shared-copy* invariant — Pi and generic output come
from the same function, differing only in the instruction sentence.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "memory_tool.py"

sys.path.insert(0, str(ROOT / "scripts" / "hooks"))

import memory_hook_common as hook  # noqa: E402


def hook_context(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(TOOL), "hook-context", "--json", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class HookContextCommandTests(unittest.TestCase):
    def test_pi_host_returns_the_tool_wording(self):
        data = hook_context("--host", "pi")
        self.assertEqual(data["host"], "pi")
        self.assertIn("`umem` tool", data["reminder"])
        self.assertIn("action=write-log", data["gate_instruction"])
        self.assertNotIn("scripts/memory_tool.py", data["gate_instruction"])

    def test_generic_host_returns_the_script_wording(self):
        data = hook_context("--host", "generic")
        self.assertIn("scripts/memory_tool.py write-log", data["reminder"])

    def test_default_host_is_generic(self):
        # The extension always passes --host pi, but an un-flagged call must not
        # silently become Pi-flavoured: other callers rely on the default.
        data = hook_context()
        self.assertEqual(data["host"], "generic")

    def test_events_are_rendered_into_the_gate_reason(self):
        data = hook_context("--host", "pi", "--events", "Bash: git commit", "--events", "Edit: /a.py")
        self.assertIn("2 important event(s)", data["gate_reason"])
        self.assertIn("Bash", data["gate_reason"])

    def test_pi_settings_are_included(self):
        data = hook_context("--host", "pi")
        self.assertIn("pi", data)
        for key in ("gate", "detail_turn_interval", "silent_summary", "inject_preferences", "brief_snapshot"):
            self.assertIn(key, data["pi"])

    def test_gate_instruction_matches_the_reason_prefix(self):
        # The extension composes the final reason from `gate_instruction` plus a
        # local event list. It must be the same sentence the reason uses, or the
        # two paths would say different things.
        data = hook_context("--host", "pi")
        self.assertTrue(data["gate_reason"].startswith(data["gate_instruction"]), data)

    def test_every_host_shares_one_implementation(self):
        for host in ("pi", "codex", "claude", "generic"):
            with self.subTest(host=host):
                self.assertEqual(
                    hook_context("--host", host)["reminder"],
                    hook.memory_protocol_reminder(host),
                )
                self.assertEqual(
                    hook_context("--host", host)["gate_instruction"],
                    hook.stop_gate_instruction(host),
                )


class StopGateInstructionTests(unittest.TestCase):
    def test_instruction_is_host_specific(self):
        self.assertIn("`umem` tool", hook.stop_gate_instruction("pi"))
        self.assertIn("scripts/memory_tool.py", hook.stop_gate_instruction())
        self.assertIn("scripts/memory_tool.py", hook.stop_gate_instruction("codex"))

    def test_reason_starts_with_the_instruction(self):
        for host in ("pi", "generic"):
            with self.subTest(host=host):
                reason = hook.stop_gate_reason(["Bash: x"], "", None, host)
                self.assertTrue(reason.startswith(hook.stop_gate_instruction(host)))


if __name__ == "__main__":
    unittest.main()
