import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.job import Job, _elapsed_seconds


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.job = Job()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_list_returns_structured_persistent_jobs(self):
        metadata = {
            "job_id": "job_test",
            "command": "echo ready",
            "cwd": str(self.root),
            "status": "completed",
            "created_at": "2026-01-01T00:00:00+00:00",
            "started_at": "2026-01-01T00:00:01+00:00",
            "finished_at": "2026-01-01T00:00:03+00:00",
            "runner_pid": 0,
            "command_pid": 0,
            "log_path": str(self.root / "job_test.log"),
        }
        (self.root / "job_test.json").write_text(json.dumps(metadata), encoding="utf-8")

        with patch("tools.job._job_root", return_value=self.root):
            result = self.job.run({"action": "list"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["jobs"][0]["job_id"], "job_test")
        self.assertEqual(result["jobs"][0]["status"], "completed")
        self.assertEqual(result["jobs"][0]["elapsed_seconds"], 2)
        self.assertFalse(result["jobs"][0]["command_alive"])

    def test_elapsed_seconds_uses_finished_time(self):
        metadata = {
            "started_at": "2026-01-01T00:00:01+00:00",
            "finished_at": "2026-01-01T00:01:01+00:00",
        }
        self.assertEqual(_elapsed_seconds(metadata), 60)


if __name__ == "__main__":
    unittest.main()
