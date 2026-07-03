import json
import os
import subprocess
import sys
import tempfile
import unittest
import datetime as dt
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODEX_HOOK = ROOT / "scripts" / "hooks" / "codex_memory_hook.py"
CLAUDE_HOOK = ROOT / "scripts" / "hooks" / "claude_memory_hook.py"


class MemoryHookTests(unittest.TestCase):
    def write_memory_config(
        self,
        tmp_path: Path,
        *,
        extra_config: str = "",
    ) -> tuple[Path, Path, Path]:
        memory_root = tmp_path / "memories"
        scoped = memory_root / "main"
        scoped.mkdir(parents=True)
        subprocess.run(
            ["git", "init", str(memory_root)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (scoped / "PREFERENCES.md").write_text("# Preferences\n", encoding="utf-8")
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
            "  load_docs_on_demand: true\n"
            f"{extra_config}",
            encoding="utf-8",
        )
        return config_path, memory_root, scoped

    def write_transcript(self, tmp_path: Path, content: str = "please edit this") -> Path:
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps({"type": "user", "message": {"content": content}}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return transcript

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
            config_path, _memory_root, scoped = self.write_memory_config(tmp_path)
            (scoped / "PREFERENCES.md").write_text(
                "# Preferences\n\n"
                "- [2026-06-14] 与用户交流时始终使用简体中文回复。用户已明确指出不要使用日语等其他语言。\n"
                "- [2026-06-14] 喜欢中文回复、简洁直接、先执行再解释。\n",
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
            self.assertNotIn("## Anatomy", hook_output["additionalContext"])

    def test_post_tool_use_does_not_upsert_anatomy_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path, _memory_root, scoped = self.write_memory_config(tmp_path)
            project = tmp_path / "project"
            project.mkdir()
            (project / ".git").mkdir()
            (project / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
            target = project / "demo.py"

            self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(target), "content": "print('hi')\n"},
                },
                tmp_path,
                extra_env={"USING_MEMORY_CONFIG": str(config_path)},
            )

            self.assertFalse((scoped / "anatomy" / "_index.json").exists())

    def test_post_tool_use_upserts_anatomy_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path, _memory_root, scoped = self.write_memory_config(
                tmp_path,
                extra_config=(
                    "features:\n"
                    "  anatomy:\n"
                    "    enabled: true\n"
                ),
            )
            project = tmp_path / "project"
            project.mkdir()
            (project / ".git").mkdir()
            (project / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
            target = project / "demo.py"
            target.write_text("print('hi')\n", encoding="utf-8")

            self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(target), "content": "print('hi')\n"},
                },
                tmp_path,
                extra_env={"USING_MEMORY_CONFIG": str(config_path)},
            )

            self.assertTrue((scoped / "anatomy" / "_index.json").exists())

    def test_stop_does_not_write_silent_summary_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path, _memory_root, scoped = self.write_memory_config(tmp_path)
            transcript = self.write_transcript(tmp_path)

            self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "please edit this file",
                },
                tmp_path,
                extra_env={"USING_MEMORY_CONFIG": str(config_path)},
            )
            self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "apply_patch"},
                },
                tmp_path,
                extra_env={"USING_MEMORY_CONFIG": str(config_path)},
            )
            output = self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                    "transcript_path": str(transcript),
                    "last_assistant_message": "Edited the file.",
                },
                tmp_path,
                extra_env={"USING_MEMORY_CONFIG": str(config_path)},
            )

            self.assertEqual(output, {})
            today_log = scoped / "log" / f"{dt.date.today().isoformat()}.jsonl"
            self.assertFalse(today_log.exists())

    def test_stop_writes_silent_summary_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path, _memory_root, scoped = self.write_memory_config(
                tmp_path,
                extra_config=(
                    "logging:\n"
                    "  silent_summary: true\n"
                    "  detail_turn_interval: 20\n"
                    "  hard_gate:\n"
                    "    memory_prompt: true\n"
                    "    important_interval: true\n"
                ),
            )
            transcript = self.write_transcript(tmp_path)

            self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "please edit this file",
                },
                tmp_path,
                extra_env={"USING_MEMORY_CONFIG": str(config_path)},
            )
            self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "apply_patch"},
                },
                tmp_path,
                extra_env={"USING_MEMORY_CONFIG": str(config_path)},
            )
            output = self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                    "transcript_path": str(transcript),
                    "last_assistant_message": "Edited the file.",
                },
                tmp_path,
                extra_env={"USING_MEMORY_CONFIG": str(config_path)},
            )

            self.assertEqual(output, {})
            today_log = scoped / "log" / f"{dt.date.today().isoformat()}.jsonl"
            self.assertTrue(today_log.exists())
            entries = [json.loads(line) for line in today_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(entries[-1]["source"], "auto")
            self.assertEqual(entries[-1]["level"], "summary")

    def test_session_archive_pointer_is_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path, _memory_root, scoped = self.write_memory_config(
                tmp_path,
                extra_config=(
                    "session_archive:\n"
                    "  enabled: true\n"
                    "  mode: pointer\n"
                    "  auto_load: false\n"
                    "  index_events: true\n"
                ),
            )
            transcript = self.write_transcript(tmp_path, "please remember the session pointer")

            output = self.run_hook(
                CODEX_HOOK,
                {
                    "session_id": "abc",
                    "turn_id": "t1",
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                    "transcript_path": str(transcript),
                    "last_assistant_message": "Done.",
                },
                tmp_path,
                extra_env={"USING_MEMORY_CONFIG": str(config_path)},
            )

            self.assertEqual(output, {})
            index_path = scoped / "sessions" / "index.jsonl"
            self.assertTrue(index_path.exists())
            record = json.loads(index_path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(record["session_id"], "abc")
            self.assertEqual(record["transcript_path"], str(transcript))
            self.assertEqual(record["mode"], "pointer")


if __name__ == "__main__":
    unittest.main()
