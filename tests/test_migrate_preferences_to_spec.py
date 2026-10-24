"""One-off PREFERENCES.md -> SPEC.md splitter.

The script's output is a durable rewrite of the user's real memory files, so the
tests focus on the things that would make it dangerous to run: it must not guess
silently, must not overwrite an existing SPEC.md, and must not delete the source
until the new files are on disk.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import migrate_preferences_to_spec as mig  # noqa: E402


def run(argv: list[str]) -> tuple[int, str]:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = mig.main(argv)
    return code, buf.getvalue()


class MigrateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ns = self.root / "main"
        self.ns.mkdir(parents=True)
        self.source = self.ns / "PREFERENCES.md"
        self.source.write_text(
            "# Preferences\n\n"
            "- [2026-01-01] Always reply in Simplified Chinese.\n\n"
            "- [2026-02-02] For the Gala desktop app, theme every dropdown.\n\n"
            "- [2026-03-03] Shared repos (any project, not only iceberg): isolate each card in a worktree.\n\n"
            "- [2026-04-04] using-memory bumps version.txt on every commit.\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_classification(self) -> None:
        self.assertEqual(mig.classify("Always reply in Simplified Chinese."), "global")
        self.assertEqual(mig.classify("For the Gala desktop app, theme dropdowns."), "gala")
        self.assertEqual(mig.classify("using-memory bumps version.txt."), "using-memory")
        # A rule naming a repo only as an example stays global.
        self.assertEqual(
            mig.classify("Shared repos (any project, not only iceberg): use worktrees."),
            "global",
        )

    def test_dry_run_writes_nothing(self) -> None:
        code, out = run(["--root", str(self.root), "--backup-dir", str(self.root / "bk")])
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        self.assertTrue(self.source.is_file())
        self.assertFalse((self.ns / "SPEC.md").exists())
        self.assertFalse((self.root / "bk").exists())

    def test_apply_splits_and_removes_source(self) -> None:
        code, _ = run(["--root", str(self.root), "--apply"])
        self.assertEqual(code, 0)

        global_text = (self.ns / "SPEC.md").read_text(encoding="utf-8")
        self.assertIn("Simplified Chinese", global_text)
        self.assertIn("any project, not only iceberg", global_text)
        self.assertNotIn("Gala", global_text)
        self.assertNotIn("version.txt", global_text)

        gala = (self.ns / "spec" / "gala.md").read_text(encoding="utf-8")
        self.assertIn("theme every dropdown", gala)
        self.assertIn("gala", gala.splitlines()[0])

        um = (self.ns / "spec" / "using-memory.md").read_text(encoding="utf-8")
        self.assertIn("version.txt", um)

        # The flat file is gone only after the split exists.
        self.assertFalse(self.source.exists())

    def test_backup_keeps_the_original(self) -> None:
        original = self.source.read_text(encoding="utf-8")
        run(["--root", str(self.root), "--apply"])
        backups = list(self.root.glob(".migration-backup-*/*PREFERENCES.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), original)

    def test_refuses_to_overwrite_existing_spec(self) -> None:
        (self.ns / "SPEC.md").write_text("# Spec\n\n- [2026-05-05] hand written\n", encoding="utf-8")
        code, _ = run(["--root", str(self.root), "--apply"])
        self.assertEqual(code, 0)
        # Untouched, and the legacy file is left for a human to reconcile.
        self.assertIn("hand written", (self.ns / "SPEC.md").read_text(encoding="utf-8"))
        self.assertTrue(self.source.is_file())

    def test_namespace_without_preferences_is_skipped(self) -> None:
        other = self.root / "other"
        other.mkdir()
        code, out = run(["--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertFalse((other / "SPEC.md").exists())

    def test_no_rules_parsed_is_not_an_error(self) -> None:
        self.source.write_text("# Preferences\n\nnothing here\n", encoding="utf-8")
        code, out = run(["--root", str(self.root), "--apply"])
        self.assertEqual(code, 0)
        self.assertTrue(self.source.is_file())


if __name__ == "__main__":
    unittest.main()
