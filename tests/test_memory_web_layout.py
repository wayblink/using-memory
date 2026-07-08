import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = ROOT / "web" / "src"
if str(WEB_SRC) not in sys.path:
    sys.path.insert(0, str(WEB_SRC))

from memory_web.app import create_app


class MemoryWebLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory_root = base / "memories"
        ns_root = self.memory_root / "main"
        (ns_root / "docs").mkdir(parents=True)
        (ns_root / "log").mkdir()
        (ns_root / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (ns_root / "PREFERENCES.md").write_text("# Preferences\n", encoding="utf-8")
        (ns_root / "docs" / "index.json").write_text('{"version":1,"documents":[]}\n', encoding="utf-8")

        self.config_path = base / "config.yaml"
        self.config_path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "memory_roots": [
                        {
                            "path": str(self.memory_root),
                            "role": "primary",
                            "writable": True,
                            "namespace": "main",
                            "machine_id": "test-main",
                            "priority": 100,
                        }
                    ],
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        self.client = TestClient(create_app(config_path=str(self.config_path)))

    def tearDown(self) -> None:
        self.client.close()
        self.tmp.cleanup()

    def test_mobile_css_prevents_fixed_sidebar_overflow(self):
        resp = self.client.get("/static/style.css")
        self.assertEqual(resp.status_code, 200)
        css = resp.text

        self.assertIn("@media (max-width: 720px)", css)
        self.assertIn(".layout {", css)
        self.assertIn("grid-template-columns: 1fr;", css)
        self.assertIn("height: auto;", css)
        self.assertIn(".entry-form label { min-width: 0; }", css)
        self.assertIn(".bar-row { grid-template-columns: minmax(0, 1fr) 72px 36px; }", css)

    def test_memory_and_preferences_add_forms_are_dialogs(self):
        memory_resp = self.client.get("/memory")
        self.assertEqual(memory_resp.status_code, 200)
        self.assertIn('data-open-modal="memory-add-dialog"', memory_resp.text)
        self.assertIn('<dialog class="entry-modal" id="memory-add-dialog"', memory_resp.text)
        self.assertNotIn('<section class="card">', memory_resp.text)

        pref_resp = self.client.get("/preferences")
        self.assertEqual(pref_resp.status_code, 200)
        self.assertIn('data-open-modal="preference-add-dialog"', pref_resp.text)
        self.assertIn('<dialog class="entry-modal" id="preference-add-dialog"', pref_resp.text)
        self.assertNotIn('<section class="card">', pref_resp.text)

    def test_docs_page_hides_indexed_filter_control(self):
        resp = self.client.get("/docs")
        self.assertEqual(resp.status_code, 200)

        self.assertNotIn('name="indexed"', resp.text)
        self.assertNotIn(">Indexed\n", resp.text)

    def test_sidebar_version_reads_repo_version_file(self):
        expected = (ROOT / "version.txt").read_text(encoding="utf-8").strip()

        self.assertEqual(self.client.app.state.skill_version, expected)

    def test_theme_switcher_exposes_brand_themes(self):
        resp = self.client.get("/search")
        self.assertEqual(resp.status_code, 200)

        self.assertIn('<details class="theme-picker">', resp.text)
        self.assertIn('<span class="theme-switcher-label footer-control-label">Theme</span>', resp.text)
        self.assertIn('<summary class="theme-picker-trigger"', resp.text)
        self.assertIn('<span class="theme-current-label">Spotify</span>', resp.text)
        self.assertIn('<div class="theme-picker-menu" role="listbox">', resp.text)
        self.assertNotIn("theme-picker-arrow", resp.text)
        self.assertIn('<span class="width-switcher-label footer-control-label">Width</span>', resp.text)
        self.assertIn('<span class="lang-switcher-label footer-control-label">Language</span>', resp.text)
        expected_titles = {
            "spotify": "Spotify — immersive dark, green accents",
            "supabase": "Supabase — light canvas, emerald accents",
            "apple": "Apple — premium white space, action blue",
            "notion": "Notion — warm workspace, purple accents",
            "vercel": "Vercel — black and white precision",
            "airbnb": "Airbnb — warm marketplace, Rausch accents",
        }
        for theme, title in expected_titles.items():
            self.assertIn(f'data-theme-mode="{theme}"', resp.text)
            self.assertIn(title, resp.text)

        self.assertIn("['spotify', 'supabase', 'apple', 'notion', 'vercel', 'airbnb']", resp.text)
        self.assertIn("document.querySelector('.theme-current-label')", resp.text)
        self.assertIn("picker.removeAttribute('open')", resp.text)

    def test_theme_css_defines_brand_tokens(self):
        resp = self.client.get("/static/style.css")
        self.assertEqual(resp.status_code, 200)
        css = resp.text

        expected_tokens = {
            'html[data-theme="apple"]': "#0066cc",
            'html[data-theme="notion"]': "#5645d4",
            'html[data-theme="vercel"]': "#171717",
            'html[data-theme="airbnb"]': "#ff385c",
            ".theme-swatch-apple": "#0066cc",
            ".theme-swatch-notion": "#5645d4",
            ".theme-swatch-vercel": "#171717",
            ".theme-swatch-airbnb": "#ff385c",
        }
        for selector, color in expected_tokens.items():
            self.assertIn(selector, css)
            self.assertIn(color, css)

    def test_theme_css_covers_shared_surfaces(self):
        resp = self.client.get("/static/style.css")
        self.assertEqual(resp.status_code, 200)
        css = resp.text

        expected_rules = {
            ".maintenance-card": "background: var(--surface);",
            ".tag.status-error": "background: var(--neg-bg); color: var(--neg-text);",
            ".tag.level-summary": "background: var(--summary-bg); color: var(--summary-text);",
            ".tag.tag-ext-html": "background: var(--ext-html-bg); color: var(--ext-html-text);",
            ".dot-memory": "background: var(--memory-text);",
            ".bar-fill.alt": "background: var(--chart-secondary);",
            ".ns-picker-details > .ns-picker-trigger": "background: var(--ns-bg);",
            ".ns-picker-trigger .ns-picker-name": "color: var(--ns-fg);",
            ".theme-picker-trigger": "background: var(--surface-hover);",
            ".footer-control": "grid-template-columns: 62px minmax(0, 1fr);",
            ".footer-control-label": "color: var(--text-muted);",
            ".footer-control-options": "justify-content: flex-start;",
            ".theme-picker-menu": "background: var(--surface);",
            ".theme-picker-menu button.active": "background: var(--surface-active);",
            ".docs-list li:hover": "background: var(--surface-hover);",
            ".card": "background: var(--surface);",
            ".modal-close": "background: var(--surface-hover);",
            ".editor-tabs .tab.active": "background: var(--surface);",
            "a.bar-row:hover": "background: var(--surface-hover);",
        }
        for selector, token_rule in expected_rules.items():
            self.assertIn(selector, css)
            self.assertIn(token_rule, css)

        for stale_rule in (
            ".tag.level-summary { background: var(--warn-bg); color: var(--warn-text); }",
            ".tag.tag-ext-html { background: var(--warn-bg); color: var(--warn-text);",
            ".dot-memory { background: var(--warn-text); }",
            ".bar-fill.alt {\n  background: var(--warn-text);",
            "--ns-bg: #171717;",
            "--ns-bg: #1d1d1f;",
            "--ns-bg: #222222;",
            ".theme-picker-trigger {\n  list-style: none;\n  width: 100%;\n  background: var(--surface-hover);\n  border: 1px",
            "border: 1px solid var(--border);\n  border-radius: var(--radius-lg);\n  box-shadow: var(--shadow-lg);",
        ):
            self.assertNotIn(stale_rule, css)

        self.assertGreaterEqual(css.count("--ns-bg: var(--accent);"), 6)
        self.assertGreaterEqual(css.count("--ns-fg: var(--on-accent);"), 6)

    def test_templates_do_not_pin_old_theme_colors_inline(self):
        templates = [
            ROOT / "web" / "src" / "memory_web" / "templates" / "base.html",
            ROOT / "web" / "src" / "memory_web" / "templates" / "dashboard.html",
            ROOT / "web" / "src" / "memory_web" / "templates" / "docs_index.html",
            ROOT / "web" / "src" / "memory_web" / "templates" / "doc.html",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in templates)

        forbidden = [
            "background:#fdecec",
            "color:#a92626",
            "background: white",
            "var(--code-bg, #f7f7f8)",
        ]
        for needle in forbidden:
            self.assertNotIn(needle, combined)

    def test_favicon_uses_theme_colors(self):
        base = (ROOT / "web" / "src" / "memory_web" / "templates" / "base.html").read_text(encoding="utf-8")
        favicon = (ROOT / "web" / "src" / "memory_web" / "static" / "favicon.svg").read_text(encoding="utf-8")

        self.assertIn("function updateThemeFavicon()", base)
        self.assertIn("styles.getPropertyValue('--accent')", base)
        self.assertIn("styles.getPropertyValue('--on-accent')", base)
        self.assertNotIn("#2383e2", favicon)
        self.assertNotIn('stroke="white"', favicon)


if __name__ == "__main__":
    unittest.main()
