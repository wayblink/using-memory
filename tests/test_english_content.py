import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EnglishContentTests(unittest.TestCase):
    def test_project_text_files_do_not_contain_han_characters(self):
        suffixes = {".md", ".json", ".py", ".yaml", ".sh"}
        paths = [
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and path.suffix in suffixes
            and "__pycache__" not in path.parts
        ]

        offenders = []
        for path in paths:
            text = path.read_text(encoding="utf-8")
            if re.search(r"[\u4e00-\u9fff]", text):
                offenders.append(path.relative_to(ROOT).as_posix())

        self.assertEqual(offenders, [])
