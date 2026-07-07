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


if __name__ == "__main__":
    unittest.main()
