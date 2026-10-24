"""MEMORY delivery: every saved entry is visible as a title.

The bug this covers was silent twice over. On Claude and Codex the MEMORY list
was loaded and then discarded before rendering, so the model never saw the saved
decisions at all. On Pi it was tail-kept, which on a curated decision store is
backwards: it retained the newest environment snapshots and dropped the oldest
product decisions (51 entries in, 6 out; the 45 dropped ones dated from April to
September).

Neither failure raised an error. The model simply answered from general
reasoning, and nothing in the session showed that a body of knowledge existed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from hooks import memory_hook_common as hook  # noqa: E402

MEMORY_DOC = """# Memory

- [fact] Memory repos center on Git so they sync and audit across machines.
- [decision|2026-04-13] Record daily decisions first, then settle them in MEMORY.md.
- [decision|2026-09-29] ## Knowledge git engine choice

The Knowledge module uses dulwich as an in-process git engine.

- [lesson|2026-10-16] **macOS app icon standard and the Tauri icon pipeline**
- [decision|2026-10-23] ## Working rule: isolate each card in a worktree
"""


def index_rows(markdown: str) -> list[str]:
    return [line for line in markdown.splitlines() if line.startswith("- [")]


class MemoryIndexTests(unittest.TestCase):
    def test_every_entry_appears(self):
        """The head of the file must not be dropped in favour of the tail."""
        out = hook.render_memory_index([MEMORY_DOC])
        self.assertIsNotNone(out)
        rows = index_rows(out)
        self.assertEqual(len(rows), 5)
        # The oldest entry is the one the tail-keeping approach discarded.
        self.assertIn("center on Git", out)
        self.assertIn("Knowledge git engine choice", out)

    def test_entries_are_titles_not_bodies(self):
        """Bodies stay out of the snapshot; only the first clause travels."""
        out = hook.render_memory_index([MEMORY_DOC])
        # The multi-paragraph body of the dulwich entry must not be included.
        self.assertNotIn("in-process git engine", out)

    def test_newest_first(self):
        out = hook.render_memory_index([MEMORY_DOC])
        rows = index_rows(out)
        self.assertIn("2026-10-23", rows[0])

    def test_header_invites_a_search(self):
        """An index without instructions reads like an excerpt."""
        out = hook.render_memory_index([MEMORY_DOC])
        self.assertIn("index", out.lower())
        self.assertIn("umem search", out)
        self.assertIn("Do not guess", out)

    def test_tag_and_date_are_kept(self):
        out = hook.render_memory_index([MEMORY_DOC])
        self.assertIn("[decision 2026-04-13]", out)
        self.assertIn("[lesson 2026-10-16]", out)
        # An entry with no date still renders, without a stray separator.
        self.assertIn("[fact]", out)

    def test_duplicates_across_roots_collapse(self):
        doc = "- [fact|2026-01-01] same entry\n"
        out = hook.render_memory_index([doc, doc])
        self.assertEqual(index_rows(out or "").__len__(), 1)

    def test_empty_input_renders_nothing(self):
        self.assertIsNone(hook.render_memory_index([]))
        self.assertIsNone(hook.render_memory_index(["# Memory\n\nno entries\n"]))

    def test_heading_markup_is_stripped(self):
        out = hook.render_memory_index(["- [decision|2026-01-01] ## Some Title\n"])
        self.assertIn("Some Title", out or "")
        self.assertNotIn("## Some Title", out or "")


class SessionStartSnapshotTests(unittest.TestCase):
    """The Claude/Codex path must render MEMORY, not just SPEC."""

    def test_snapshot_includes_memory_and_spec(self):
        import json
        import tempfile
        from unittest import mock

        payload = {
            "preferences": ["# Spec\n\n- always reply in Simplified Chinese\n"],
            "durable_memory": [MEMORY_DOC],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write("version: 1\nmemory_roots:\n  - path: /tmp\n")
            cfg = fh.name
        try:
            completed = mock.Mock(returncode=0, stdout=json.dumps(payload))
            with mock.patch.object(hook, "_resolve_memory_config", return_value=cfg), \
                 mock.patch.object(hook.subprocess, "run", return_value=completed):
                out = hook.fetch_session_start_snapshot({})
        finally:
            Path(cfg).unlink(missing_ok=True)

        self.assertIsNotNone(out)
        self.assertIn("## Active spec", out)
        self.assertIn("## Long-term memory", out)
        self.assertEqual(len(index_rows(out.split("## Long-term memory")[1])), 5)

    def test_missing_memory_does_not_remove_the_spec(self):
        import json
        import tempfile
        from unittest import mock

        payload = {"preferences": ["# Spec\n\n- a rule\n"]}
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write("version: 1\nmemory_roots:\n  - path: /tmp\n")
            cfg = fh.name
        try:
            completed = mock.Mock(returncode=0, stdout=json.dumps(payload))
            with mock.patch.object(hook, "_resolve_memory_config", return_value=cfg), \
                 mock.patch.object(hook.subprocess, "run", return_value=completed):
                out = hook.fetch_session_start_snapshot({})
        finally:
            Path(cfg).unlink(missing_ok=True)

        self.assertIn("## Active spec", out or "")
        self.assertNotIn("## Long-term memory", out or "")


if __name__ == "__main__":
    unittest.main()
