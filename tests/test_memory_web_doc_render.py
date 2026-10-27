"""Doc page must hand the markdown to the browser byte-for-byte.

The markdown source travels inside ``<script id="doc-source">`` — a raw-text
element that never decodes character references. If the template lets Jinja
autoescape run over it, ``=> 'db.docs'`` arrives at marked as
``=&gt; &#39;db.docs&#39;`` and code blocks render those entities literally
(marked re-escapes ``&`` inside code spans). So the payload is JSON-encoded
and must round-trip exactly.
"""

import json
import re
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


MARKDOWN_BODY = """# Render probe

Prose with an ampersand & a <placeholder> and "quotes".

```
CALL prod.system.build_vector_index(
  table   => 'db.docs',
  column  => 'embedding',
  options => map('rabitq-bits', '1'),
  guard   => 128 < 256 && true);
```

| call | description |
|---|---|
| `list_indexes(table=>'db.t')` | list indexes |

A literal closing tag must not end the payload: </script>
"""


class MemoryWebDocRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.memory_root = base / "memories"
        ns_root = self.memory_root / "main"
        (ns_root / "docs").mkdir(parents=True)
        (ns_root / "log").mkdir()
        (ns_root / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (ns_root / "docs" / "index.json").write_text(
            '{"version":1,"documents":[]}\n', encoding="utf-8"
        )
        (ns_root / "docs" / "render-probe.md").write_text(MARKDOWN_BODY, encoding="utf-8")

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

    def _doc_html(self) -> str:
        resp = self.client.get("/docs/render-probe.md")
        self.assertEqual(resp.status_code, 200)
        return resp.text

    def test_markdown_payload_round_trips_through_script_tag(self) -> None:
        html = self._doc_html()

        match = re.search(
            r'<script id="doc-source" type="application/json">(.*?)</script>',
            html,
            re.S,
        )
        self.assertIsNotNone(match, "doc-source must be a JSON payload, not HTML-escaped text")
        payload = json.loads(match.group(1))
        self.assertEqual(payload, MARKDOWN_BODY)

    def test_payload_is_not_html_escaped(self) -> None:
        html = self._doc_html()

        # The classic breakage: entities sitting where markdown should be.
        self.assertNotIn("=&gt;", html)
        self.assertNotIn("&#39;db.docs&#39;", html)
        self.assertNotIn("&lt;placeholder&gt;", html)

    def test_embedded_closing_script_tag_does_not_truncate_page(self) -> None:
        html = self._doc_html()

        # `</script>` from the document body must survive only as an escaped
        # JSON sequence, otherwise the payload (and the rest of the page) ends
        # early and the doc renders half-empty.
        self.assertIn("\\u003c/script>", html)
        self.assertIn('id="doc-body"', html)


if __name__ == "__main__":
    unittest.main()
