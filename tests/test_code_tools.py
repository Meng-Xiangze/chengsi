import tempfile
import unittest
from pathlib import Path

from tools._hashline import anchor, revision
from tools.edit import Edit
from tools.read import Read


SOURCE = """class Example:\n    def first(self):\n        return 1\n\n    def second(self):\n        return 2\n"""


class CodeToolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "example.py"
        self.path.write_text(SOURCE, encoding="utf-8", newline="")
        self.edit = Edit()
        self.read = Read()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_read_outline_and_qualified_symbol(self):
        outline = self.read.run({"path": str(self.path), "mode": "outline"})
        self.assertIn(f"rev: {revision(SOURCE)}", outline)
        self.assertIn("class Example lines 1-6", outline)
        self.assertIn("function Example.second lines 5-6", outline)

        symbol = self.read.run({
            "path": str(self.path),
            "mode": "symbol",
            "symbol": "Example.second",
        })
        self.assertIn("[python symbol: Example.second]", symbol)
        self.assertIn(f"5:{anchor(5, '    def second(self):').split(':')[1]}|", symbol)
        self.assertNotIn("def first", symbol)

    def test_replace_range_uses_inclusive_hash_anchors(self):
        result = self.edit.run({
            "path": str(self.path),
            "revision": revision(SOURCE),
            "edits": [{
                "op": "replace_range",
                "start": anchor(2, "    def first(self):"),
                "end": anchor(3, "        return 1"),
                "newText": "    def first(self):\n        return 10\n",
            }],
        })
        self.assertIn("Edited", result)
        self.assertIn("return 10", self.path.read_text(encoding="utf-8"))
        self.assertNotIn("return 1\n", self.path.read_text(encoding="utf-8"))

    def test_stale_anchor_and_revision_do_not_write(self):
        stale_revision = revision(SOURCE + "# changed")
        result = self.edit.run({
            "path": str(self.path),
            "revision": stale_revision,
            "edits": [{"op": "delete_symbol", "symbol": "Example.first"}],
        })
        self.assertIn("stale revision", result)
        self.assertEqual(self.path.read_text(encoding="utf-8"), SOURCE)

        result = self.edit.run({
            "path": str(self.path),
            "edits": [{
                "op": "delete_range",
                "start": "2:0000000000000000",
                "end": anchor(3, "        return 1"),
            }],
        })
        self.assertIn("stale anchor", result)
        self.assertEqual(self.path.read_text(encoding="utf-8"), SOURCE)

    def test_duplicate_symbol_is_rejected(self):
        duplicate = "def value():\n    return 1\n\ndef value():\n    return 2\n"
        self.path.write_text(duplicate, encoding="utf-8", newline="")
        result = self.edit.run({
            "path": str(self.path),
            "edits": [{"op": "delete_symbol", "symbol": "value"}],
        })
        self.assertIn("matched 2 definitions", result)
        self.assertEqual(self.path.read_text(encoding="utf-8"), duplicate)

    def test_replace_symbol_includes_decorator_and_rejects_invalid_python(self):
        decorated = "@staticmethod\ndef value():\n    return 1\n"
        self.path.write_text(decorated, encoding="utf-8", newline="")
        result = self.edit.run({
            "path": str(self.path),
            "edits": [{
                "op": "replace_symbol",
                "symbol": "value",
                "newText": "def value():\n    return 2\n",
            }],
        })
        self.assertIn("Edited", result)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "def value():\n    return 2\n")

        before = self.path.read_bytes()
        result = self.edit.run({
            "path": str(self.path),
            "edits": [{
                "op": "replace_symbol",
                "symbol": "value",
                "newText": "def value(:\n",
            }],
        })
        self.assertIn("invalid Python", result)
        self.assertEqual(self.path.read_bytes(), before)

    def test_preserves_utf8_bom_and_crlf(self):
        source = SOURCE.replace("\n", "\r\n")
        self.path.write_bytes(b"\xef\xbb\xbf" + source.encode("utf-8"))
        symbol = self.read.run({
            "path": str(self.path), "mode": "symbol", "symbol": "Example.first"
        })
        self.assertIn(f"rev: {revision(source)}", symbol)

        result = self.edit.run({
            "path": str(self.path),
            "revision": revision(source),
            "edits": [{
                "op": "replace_symbol",
                "symbol": "Example.first",
                "newText": "    def first(self):\n        return 10\n",
            }],
        })
        self.assertIn("Edited", result)
        raw = self.path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertIn(b"return 10\r\n", raw)


if __name__ == "__main__":
    unittest.main()
