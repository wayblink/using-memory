"""`load --brief` — the compact snapshot the Pi extension injects.

The contract is two-sided: `--brief` must be small enough to post as a message,
and the plain form must be untouched, because hooks, the web app and every
scripting caller depend on the existing shape.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "memory_tool.py"

sys.path.insert(0, str(ROOT / "scripts"))

import memory_tool  # noqa: E402


def run_load(*args: str) -> tuple[dict, int]:
    result = subprocess.run(
        [sys.executable, str(TOOL), "load", "--json", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout or "{}"), len(result.stdout)


class BriefSnapshotTests(unittest.TestCase):
    def test_plain_snapshot_is_unchanged(self):
        data, _ = run_load()
        self.assertNotIn("brief", data)
        for key in (
            "mode",
            "write_enabled",
            "sources",
            "preferences",
            "durable_memory",
            "log_entries",
            "doc_hits",
            "warnings",
        ):
            self.assertIn(key, data)

    def test_brief_is_flagged_and_drops_the_docs_index(self):
        data, _ = run_load("--brief")
        self.assertTrue(data["brief"])
        types = [source.get("type") for source in data["sources"]]
        self.assertNotIn("docs_index", types)

    def test_brief_keeps_the_top_level_fields(self):
        data, _ = run_load("--brief")
        for key in ("preferences", "durable_memory", "log_entries", "warnings", "mode"):
            self.assertIn(key, data)

    def test_brief_is_materially_smaller(self):
        _, full_bytes = run_load()
        _, brief_bytes = run_load("--brief")
        if full_bytes == 0:
            self.skipTest("no memory configured")
        self.assertLess(brief_bytes, full_bytes)
        # Not a strict ratio: a nearly-empty memory repo has little to trim, and
        # a huge one has a floor of genuinely useful content. This only guards
        # against `--brief` becoming a no-op.
        self.assertLess(brief_bytes, full_bytes * 0.9 + 1000)

    def test_brief_truncation_is_marked_not_silent(self):
        # Unit-level, so it runs without a populated memory repo.
        long_text = "- [fact] " + ("x" * 5000)
        trimmed = memory_tool._brief_tail(long_text, 1000)
        self.assertIn("omitted", trimmed)
        self.assertLess(len(trimmed), len(long_text))

    def test_brief_tail_keeps_whole_lines(self):
        text = "\n".join(f"- entry {i} " + ("y" * 40) for i in range(200))
        trimmed = memory_tool._brief_tail(text, 500)
        body = trimmed.split("\n\n", 1)[1]
        for line in body.splitlines():
            self.assertTrue(line.startswith("- entry"), line)

    def test_brief_sources_drops_index_and_marks_truncation(self):
        sources = [
            {"type": "preferences", "content": "short"},
            {"type": "docs_index", "content": "{}"},
            {"type": "durable_memory", "content": "z" * 5000},
        ]
        out = memory_tool.brief_sources(sources)
        self.assertEqual([s["type"] for s in out], ["preferences", "durable_memory"])
        self.assertEqual(out[0]["content"], "short")
        self.assertTrue(out[1]["truncated"])
        self.assertIn("truncated", out[1]["content"])

    def test_brief_log_entries_cap_text(self):
        entries = [{"tag": "progress", "level": "summary", "text": "q" * 3000}]
        out = memory_tool._brief_log_entries(entries)
        self.assertTrue(out[0]["truncated"])
        self.assertLess(len(out[0]["text"]), 3000)
        # Identity fields survive, because a truncated entry with no tag is
        # useless for deciding whether to read the rest.
        self.assertEqual(out[0]["tag"], "progress")


if __name__ == "__main__":
    unittest.main()
