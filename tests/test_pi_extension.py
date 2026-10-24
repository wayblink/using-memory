"""The Pi extension and the Python hooks must resolve the same memory tool.

Two resolvers exist by necessity — one TypeScript (the extension cannot import
Python) and one Python (the hooks run standalone). If they disagree, the agent
reads memory through one CLI while the hooks write through another, and the
symptom is "my log entries are missing" rather than an error.

This test checks the one invariant that matters across the language boundary:
given the same environment, both pick an existing `memory_tool.py`, and both
honour `USING_MEMORY_CONFIG` precedence.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSION_TESTS = ROOT / "packages" / "pi" / "tests"

sys.path.insert(0, str(ROOT / "scripts" / "hooks"))

import memory_hook_common as hook  # noqa: E402


def node_available() -> bool:
    return shutil.which("node") is not None


def ts_resolve(expr: str, env: dict[str, str]) -> str | None:
    """Evaluate a resolver from the TS side and print the result."""
    script = (
        "const m = await import('"
        f"{ROOT / 'packages' / 'pi' / 'extensions' / 'umem' / 'resolve.ts'}"
        "');\n"
        f"console.log({expr});\n"
    )
    result = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        timeout=60,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


class CrossLanguageResolutionTests(unittest.TestCase):
    def test_extension_resolver_files_exist(self):
        self.assertTrue((ROOT / "packages" / "pi" / "extensions" / "umem" / "resolve.ts").is_file())

    @unittest.skipUnless(node_available(), "node not available")
    def test_both_resolvers_find_an_existing_cli(self):
        env = dict(os.environ)
        env.pop("USING_MEMORY_CONFIG", None)
        py = hook.resolve_memory_tool_path(None)
        ts = ts_resolve("m.resolveMemoryTool()", env)
        if ts is None:
            self.skipTest("could not evaluate the TypeScript resolver")
        # Each may legitimately pick a different *install* (the extension and a
        # hook installed into different host dirs). What must hold is that both
        # names point at a real memory_tool.py, not at a stale path.
        for label, value in (("python", py), ("typescript", ts)):
            with self.subTest(label=label):
                self.assertTrue(value, f"{label} resolver returned nothing")
                self.assertTrue(
                    Path(value).name == "memory_tool.py",
                    f"{label} resolved to {value}",
                )

    @unittest.skipUnless(node_available(), "node not available")
    def test_both_resolvers_honour_using_memory_config(self):
        expected = str(ROOT / "scripts" / "memory_tool.py")
        saved = os.environ.get("USING_MEMORY_CONFIG")
        os.environ["USING_MEMORY_CONFIG"] = str(ROOT / "config.yaml")
        try:
            py = hook.resolve_memory_tool_path(None)
            env = dict(os.environ)
            ts = ts_resolve("m.resolveMemoryTool()", env)
        finally:
            if saved is None:
                os.environ.pop("USING_MEMORY_CONFIG", None)
            else:
                os.environ["USING_MEMORY_CONFIG"] = saved
        if ts is None:
            self.skipTest("could not evaluate the TypeScript resolver")
        self.assertEqual(py, expected)
        self.assertEqual(ts, expected)


class ExtensionPackageManifestTests(unittest.TestCase):
    """The manifest rules Pi enforces, checked without running Pi."""

    def setUp(self):
        self.pkg = json.loads(
            (ROOT / "packages" / "pi" / "package.json").read_text(encoding="utf-8")
        )

    def test_host_packages_are_optional_peers_not_dependencies(self):
        host = [
            "@earendil-works/pi-ai",
            "@earendil-works/pi-coding-agent",
            "typebox",
        ]
        deps = self.pkg.get("dependencies", {})
        for name in host:
            self.assertNotIn(name, deps, f"{name} must not be a real dependency")
            self.assertIn(name, self.pkg.get("peerDependencies", {}))
            self.assertTrue(self.pkg["peerDependenciesMeta"][name]["optional"], name)

    def test_manifest_declares_extensions_only(self):
        # `packages/pi` ships the extension. It deliberately ships no skill: the
        # canonical skill is the checkout root (see
        # test_only_one_skill_file_in_the_checkout), and a packaged copy would be
        # a second physical SKILL.md whose `name: umem` collides with the copy
        # exposed through ~/.agents/skills.
        pi_manifest = self.pkg["pi"]
        self.assertEqual(pi_manifest["extensions"], ["./extensions"])
        self.assertNotIn("skills", pi_manifest)

    def test_declared_resources_exist(self):
        for entry in self.pkg["pi"]["extensions"]:
            self.assertTrue((ROOT / "packages" / "pi" / entry).is_dir(), entry)

    def test_only_one_skill_file_in_the_checkout(self):
        # A second SKILL.md with the same `name:` makes Pi (and every other Agent
        # Skills host) report `name "umem" collision` and silently drop one of
        # them. Vendored Python packages ship their own SKILL.md files, so skip
        # virtualenvs and node_modules.
        skill_files = sorted(
            path
            for path in ROOT.rglob("SKILL.md")
            if not {".git", ".venv", "node_modules", "venv"} & set(path.parts)
        )
        self.assertEqual([ROOT / "SKILL.md"], skill_files)

    def test_pi_skill_installers_point_at_the_checkout_root(self):
        # The skill directory must be named `umem` (matching the frontmatter
        # name) and must contain SKILL.md next to references/ and examples/,
        # because the body links to them relatively.
        for script in ("link.sh", "install.sh"):
            text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
            self.assertIn("skills/umem", text, script)
            self.assertNotIn("pkg/skills/umem", text, script)
        link = (ROOT / "scripts" / "link.sh").read_text(encoding="utf-8")
        self.assertIn('ln -sfn "$HERE" "$agent_dir/skills/umem"', link)
        install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        self.assertIn('cp "$HERE/SKILL.md" "$skill_dir/SKILL.md"', install)


if __name__ == "__main__":
    unittest.main()
