import subprocess
import unittest
from unittest.mock import patch

from tools.project_test import ProjectTest


class ProjectTestTests(unittest.TestCase):
    def setUp(self):
        self.tool = ProjectTest()

    def test_rejects_unknown_scope(self):
        result = self.tool.run({"scope": "unknown"})

        self.assertTrue(result.startswith("Error:"))

    @patch("tools.project_test.os.path.isdir", return_value=True)
    @patch("tools.project_test.subprocess.run")
    def test_tests_scope_runs_unittest_discovery(self, run, _isdir):
        run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="Ran 12 tests\n\nOK")

        result = self.tool.run({"scope": "tests"})

        command = run.call_args.args[0]
        self.assertEqual(command[1:], ["-m", "unittest", "discover", "-s", "tests", "-v"])
        self.assertIn("OK: unittest exited with code 0", result)
        self.assertIn("Ran 12 tests", result)

    @patch("tools.project_test.os.path.isdir", return_value=True)
    @patch("tools.project_test.subprocess.run")
    def test_tests_scope_reports_nonzero_exit(self, run, _isdir):
        run.return_value = subprocess.CompletedProcess([], 1, stdout="", stderr="FAILED (failures=1)")

        result = self.tool.run({"scope": "tests"})

        self.assertIn("FAIL: unittest exited with code 1", result)
        self.assertIn("FAILED (failures=1)", result)

    @patch("tools.project_test.os.path.isdir", return_value=True)
    @patch("tools.project_test.subprocess.run", side_effect=subprocess.TimeoutExpired("unittest", 120))
    def test_tests_scope_reports_timeout(self, _run, _isdir):
        result = self.tool.run({"scope": "tests"})

        self.assertIn("FAIL", result)
        self.assertIn("timed out", result)


if __name__ == "__main__":
    unittest.main()
