"""SessionStart rule delivery: every SPEC entry, complete and unfiltered.

The failure this guards against is silent. An earlier implementation scored
rule lines with keyword matching and kept the top four, so a rule that did not
happen to contain words like "reply" or "always" was dropped with no error —
the agent then behaved as if the rule did not exist and nothing looked wrong.
These tests pin the three properties that prevent a repeat:

1. Every rule line is delivered, no cap.
2. Rule text is never truncated mid-sentence.
3. File headings and preambles are not rendered as if they were rules.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from hooks import memory_hook_common as hook  # noqa: E402


def rendered_rule_lines(markdown: str) -> list[str]:
    return [line for line in markdown.splitlines() if line.startswith("- ")]


class RuleDeliveryTests(unittest.TestCase):
    def test_every_rule_is_delivered(self):
        """A cap would silently drop rules that lack signal keywords."""
        rules = [f"rule number {i} about git worktree isolation" for i in range(30)]
        doc = "# Spec\n\npreamble\n\n" + "\n".join(f"- {r}" for r in rules)
        out = hook.render_preference_summary([doc])
        self.assertIsNotNone(out)
        lines = rendered_rule_lines(out)
        self.assertEqual(len(lines), 30)
        for rule in rules:
            self.assertIn(rule, out)

    def test_rule_without_signal_words_survives(self):
        """The old scorer ranked this last; it must not be dropped."""
        doc = (
            "# Spec\n\n"
            "- Always reply in Simplified Chinese.\n"
            "- Shared-repo work: isolate every card in a git worktree, rebase main, then merge.\n"
        )
        out = hook.render_preference_summary([doc])
        self.assertIn("worktree", out)
        self.assertIn("Simplified Chinese", out)

    def test_long_rule_is_not_truncated(self):
        long_rule = "A rule that must be followed: " + "detail " * 400 + "(END-MARKER)"
        out = hook.render_preference_summary([f"# Spec\n\n- {long_rule}\n"])
        self.assertIn("END-MARKER", out)
        self.assertNotIn("truncated", out.lower())

    def test_heading_and_preamble_are_not_rendered_as_rules(self):
        """A preamble is documentation. Rendering it as a bullet makes the model
        treat an explanation of the file format as an instruction."""
        doc = (
            "# Spec\n\n"
            "Rules and constraints that apply to every project in this namespace.\n"
            "Project-specific specs live in `spec/<repo>.md`.\n\n"
            "- the real rule\n"
        )
        out = hook.render_preference_summary([doc])
        lines = rendered_rule_lines(out)
        self.assertEqual(len(lines), 1)
        self.assertIn("the real rule", lines[0])
        self.assertNotIn("Project-specific specs live", out)

    def test_multiple_roots_are_merged_and_deduplicated(self):
        global_doc = "# Spec\n\n- shared rule\n"
        project_doc = "# Spec — dozo\n\npreamble\n\n- dozo rule\n- shared rule\n"
        out = hook.render_preference_summary([global_doc, project_doc])
        self.assertEqual(out.count("shared rule"), 1)
        self.assertIn("dozo rule", out)

    def test_continuation_lines_join_the_preceding_rule(self):
        doc = (
            "# Spec\n\n"
            "- All design docs go to the docs/ directory.\n\n"
            "  Why: keeps them out of project dirs.\n"
            "  How to apply: create with upsert-doc.\n"
        )
        out = hook.render_preference_summary([doc])
        lines = rendered_rule_lines(out)
        self.assertEqual(len(lines), 1)
        self.assertIn("keeps them out", lines[0])
        self.assertIn("upsert-doc", lines[0])

    def test_empty_and_preamble_only_docs_render_nothing(self):
        self.assertIsNone(hook.render_preference_summary([]))
        self.assertIsNone(hook.render_preference_summary(["# Spec\n\njust a preamble\n"]))

    def test_section_explains_these_are_constraints(self):
        out = hook.render_preference_summary(["# Spec\n\n- a rule\n"])
        self.assertIn("Active spec", out)
        self.assertIn("constraints", out.lower())


if __name__ == "__main__":
    unittest.main()
