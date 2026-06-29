import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODEX_HOOK = ROOT / "scripts" / "hooks" / "codex_memory_hook.py"
CLAUDE_HOOK = ROOT / "scripts" / "hooks" / "claude_memory_hook.py"


class MemoryHookTests(unittest.TestCase):
    def run_hook(self, script: Path, payload: dict, state_dir: Path, extra_env: dict | None = None) -> dict:
        env = os.environ.copy()
        env["USING_MEMORY_HOOK_STATE_DIR"] = str(state_dir)
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=ROOT,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout or "{}")

    def test_codex_stop_blocks_when_operation_has_no_memory_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            # Explicit memory trigger via UserPromptSubmit short-circuits the
            # N=8 turn-count throttle, so a single PostToolUse + Stop suffices
            # to test the block path.
            self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "please save this commit to memory",
                },
                state_dir,
            )
            self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git commit -m refine-memory"},
                    "tool_response": {"output": "[main abc123] refine-memory"},
                },
                state_dir,
            )

            output = self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                    "last_assistant_message": "Committed the memory refinement.",
                },
                state_dir,
            )

            self.assertEqual(output["decision"], "block")
            self.assertIn("write-log", output["reason"])

    def test_claude_stop_allows_after_memory_write_is_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            self.run_hook(
                CLAUDE_HOOK,
                {
                    "session_id": "abc",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "python3 scripts/memory_tool.py write-log --tag commit --text done"},
                },
                state_dir,
            )

            output = self.run_hook(
                CLAUDE_HOOK,
                {
                    "session_id": "abc",
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                    "last_assistant_message": "Done.",
                },
                state_dir,
            )

            self.assertEqual(output, {})

    def test_session_start_adds_protocol_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            memory_root = tmp_path / "memories"
            scoped = memory_root / "main"
            scoped.mkdir(parents=True)
            (scoped / "PREFERENCES.md").write_text(
                "# Preferences\n\n"
                "- [2026-06-14] 与用户交流时始终使用简体中文回复。用户已明确指出不要使用日语等其他语言。\n"
                "- [2026-06-14] 喜欢中文回复、简洁直接、先执行再解释。\n",
                encoding="utf-8",
            )
            (scoped / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
            (scoped / "STATS.json").write_text("{\"lifetime\": {}}\n", encoding="utf-8")
            (scoped / "docs").mkdir()
            (scoped / "docs" / "index.json").write_text("[]\n", encoding="utf-8")
            (scoped / "log").mkdir()
            config_path = tmp_path / "config.yaml"
            config_path.write_text(
                "version: 1\n"
                "memory_roots:\n"
                f"  - path: {memory_root}\n"
                "    role: primary\n"
                "    writable: true\n"
                "    namespace: main\n"
                "    machine_id: test-main\n"
                "    priority: 100\n"
                "defaults:\n"
                "  read_today: true\n"
                "  read_yesterday: true\n"
                "  load_docs_on_demand: true\n",
                encoding="utf-8",
            )
            output = self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "SessionStart",
                },
                tmp_path,
                extra_env={"USING_MEMORY_CONFIG": str(config_path)},
            )

            hook_output = output["hookSpecificOutput"]
            self.assertEqual(hook_output["hookEventName"], "SessionStart")
            self.assertIn("using-memory hook reminder", hook_output["additionalContext"])
            self.assertIn("## Active preferences", hook_output["additionalContext"])
            self.assertIn("始终使用简体中文回复", hook_output["additionalContext"])
            self.assertIn("不要使用日语", hook_output["additionalContext"])


if __name__ == "__main__":
    unittest.main()
