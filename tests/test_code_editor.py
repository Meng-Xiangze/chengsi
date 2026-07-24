import os
import tempfile
import unittest
from unittest.mock import patch

from tools._hashline import anchor, revision
from tools.code_editor import CodeEditor


class CodeEditorHashlineTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = self.tempdir.name
        self.editor = CodeEditor()
        self.project_patch = patch("tools.code_editor.PROJECT_ROOT", self.root)
        self.project_patch.start()

    def tearDown(self):
        self.project_patch.stop()
        self.tempdir.cleanup()

    def write_bytes(self, name: str, content: bytes) -> str:
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def test_read_returns_revision_and_line_anchors(self):
        self.write_bytes("sample.py", b"first\nsecond\n")
        result = self.editor.run({"action": "read", "path": "sample.py"})
        self.assertIn(f"rev: {revision('first\nsecond\n')}", result)
        self.assertIn(f"{anchor(1, 'first')}|first", result)
        self.assertIn(f"{anchor(2, 'second')}|second", result)

    def test_edit_replaces_range_and_preserves_crlf(self):
        path = self.write_bytes("sample.py", b"one\r\ntwo\r\nthree\r\n")
        text = "one\r\ntwo\r\nthree\r\n"
        result = self.editor.run({
            "action": "edit",
            "path": "sample.py",
            "revision": revision(text),
            "operations": [{
                "op": "replace",
                "start": anchor(2, "two"),
                "end": anchor(3, "three"),
                "content": "new\nlines",
            }],
        })
        self.assertTrue(result.startswith("OK:"), result)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"one\r\nnew\r\nlines\r\n")

    def test_stale_anchor_rejects_without_writing(self):
        path = self.write_bytes("sample.py", b"changed\n")
        result = self.editor.run({
            "action": "edit",
            "path": "sample.py",
            "operations": [{"op": "replace", "start": anchor(1, "old"), "content": "new"}],
        })
        self.assertIn("stale anchor", result)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"changed\n")

    def test_overlapping_batch_is_rejected_atomically(self):
        path = self.write_bytes("sample.py", b"one\ntwo\nthree\n")
        result = self.editor.run({
            "action": "edit",
            "path": "sample.py",
            "operations": [
                {"op": "replace", "start": anchor(1, "one"), "end": anchor(2, "two"), "content": "x"},
                {"op": "delete", "start": anchor(2, "two")},
            ],
        })
        self.assertIn("overlaps", result)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"one\ntwo\nthree\n")

    def test_multiple_edits_apply_bottom_up(self):
        path = self.write_bytes("sample.py", b"one\ntwo\nthree\n")
        result = self.editor.run({
            "action": "edit",
            "path": "sample.py",
            "operations": [
                {"op": "insert_after", "start": anchor(1, "one"), "content": "middle"},
                {"op": "replace", "start": anchor(3, "three"), "content": "last"},
            ],
        })
        self.assertTrue(result.startswith("OK:"), result)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"one\nmiddle\ntwo\nlast\n")

    def test_read_pagination(self):
        self.write_bytes("sample.py", b"one\ntwo\nthree\n")
        result = self.editor.run({"action": "read", "path": "sample.py", "offset": 2, "limit": 1})
        self.assertIn("showing: 2-2", result)
        self.assertIn(f"{anchor(2, 'two')}|two", result)
        self.assertIn("offset=3", result)


if __name__ == "__main__":
    unittest.main()
