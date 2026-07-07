import json
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


class MemoryWebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory_root = base / "memories"
        ns_root = self.memory_root / "main"
        (ns_root / "docs").mkdir(parents=True)
        (ns_root / "log").mkdir()
        (ns_root / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (ns_root / "PREFERENCES.md").write_text("# Preferences\n", encoding="utf-8")
        (ns_root / "docs" / "index.json").write_text(json.dumps([]), encoding="utf-8")
        self.config_path = base / "config.yaml"
        self.config_path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "remote": {
                        "endpoint": "http://127.0.0.1:8765",
                        "token": "secret-token",
                    },
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
                    "defaults": {
                        "read_today": True,
                        "read_yesterday": True,
                        "load_docs_on_demand": True,
                    },
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

    def test_api_v1_requires_bearer_token_for_non_local_clients(self):
        headers = {"host": "memory.example.test"}

        missing = self.client.get("/api/v1/health", headers=headers)
        wrong = self.client.get(
            "/api/v1/health",
            headers={**headers, "authorization": "Bearer wrong"},
        )
        ok = self.client.get(
            "/api/v1/health",
            headers={**headers, "authorization": "Bearer secret-token"},
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["ok"], True)

    def test_api_v1_exempts_loopback_clients(self):
        resp = self.client.get("/api/v1/health", headers={"host": "127.0.0.1:8765"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["ok"], True)


if __name__ == "__main__":
    unittest.main()
