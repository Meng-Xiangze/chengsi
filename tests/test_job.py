import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.process_utils import child_environment, normalize_python_commands
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
            active_result = self.job.run({"action": "list"})
            result = self.job.run({"action": "list", "include_history": True})

        self.assertTrue(active_result["ok"])
        self.assertEqual(active_result["jobs"], [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["jobs"][0]["job_id"], "job_test")
        self.assertEqual(result["jobs"][0]["status"], "completed")
        self.assertEqual(result["jobs"][0]["elapsed_seconds"], 2)
        self.assertFalse(result["jobs"][0]["command_alive"])

    def test_list_keeps_failed_jobs_without_history_flag(self):
        metadata = {
            "job_id": "job_failed",
            "command": "broken command",
            "cwd": str(self.root),
            "status": "failed",
            "created_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-01T00:00:01+00:00",
            "runner_pid": 0,
            "command_pid": 0,
            "log_path": str(self.root / "job_failed.log"),
            "error": "failed",
        }
        (self.root / "job_failed.json").write_text(json.dumps(metadata), encoding="utf-8")
        with patch("tools.job._job_root", return_value=self.root):
            result = self.job.run({"action": "list"})
        self.assertEqual(result["jobs"][0]["status"], "failed")
        self.assertEqual(result["attention"][0]["job_id"], "job_failed")

    def test_archive_hides_failed_job_but_keeps_history_record(self):
        metadata = {
            "job_id": "job_archive",
            "command": "broken command",
            "cwd": str(self.root),
            "status": "failed",
            "created_at": "2026-01-01T00:00:00+00:00",
            "runner_pid": 0,
            "command_pid": 0,
            "log_path": str(self.root / "job_archive.log"),
        }
        path = self.root / "job_archive.json"
        path.write_text(json.dumps(metadata), encoding="utf-8")
        with patch("tools.job._job_root", return_value=self.root):
            result = self.job.run({"action": "archive", "job_id": "job_archive"})
            listing = self.job.run({"action": "list"})
            history = self.job.run({"action": "list", "include_history": True})
        self.assertTrue(result["ok"])
        self.assertEqual(listing["jobs"], [])
        self.assertEqual(history["jobs"][0]["job_id"], "job_archive")

    def test_failed_status_exposes_exit_code_and_error(self):
        metadata = {
            "job_id": "job_failed_detail",
            "command": "exit 7",
            "cwd": str(self.root),
            "status": "failed",
            "exit_code": 7,
            "error": "Command exited with code 7.",
            "created_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-01T00:00:01+00:00",
            "runner_pid": 0,
            "command_pid": 0,
            "log_path": str(self.root / "job_failed_detail.log"),
        }
        (self.root / "job_failed_detail.json").write_text(json.dumps(metadata), encoding="utf-8")
        with patch("tools.job._job_root", return_value=self.root):
            result = self.job.run({"action": "status", "job_id": "job_failed_detail"})
        self.assertTrue(result["ok"])
        self.assertIn("status: failed", result["content"])
        self.assertIn("exit_code: 7", result["content"])
        self.assertIn("Command exited with code 7", result["content"])

    def test_child_environment_is_utf8_and_uses_active_virtualenv(self):
        environment = child_environment()
        self.assertEqual(environment["PYTHONUTF8"], "1")
        self.assertEqual(environment["PYTHONIOENCODING"], "utf-8")
        self.assertTrue(environment["CHENGSI_ROOT"].endswith("chengsi"))

    def test_schedule_always_returns_current_time(self):
        from tools.schedule import Schedule
        result = Schedule().run({"action": "list"})
        self.assertTrue(result["current_time"])
        self.assertTrue(result["content"].startswith("current_time: "))

    def test_schedule_rejects_intervals_shorter_than_one_minute(self):
        from tools.schedule import Schedule
        result = Schedule().run({
            "action": "create",
            "prompt": "check news",
            "run_at": "2099-01-01T00:00:00",
            "interval_seconds": 30,
        })
        self.assertFalse(result["ok"])
        self.assertIn("at least 60", result["content"])

    def test_job_start_metadata_preserves_auto_followup_decision(self):
        from tools.job import Job
        from unittest.mock import patch
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("tools.job._job_root", return_value=root), patch("tools.job.subprocess.Popen"):
                result = Job()._start({
                    "command": "echo done",
                    "cwd": str(root),
                    "session_id": "session-1",
                    "auto_followup": True,
                })
                self.assertTrue(result["ok"])
                metadata = next(root.glob("*.json")).read_text(encoding="utf-8")
                self.assertIn('"auto_followup": true', metadata)

    def test_python_and_pip_commands_bind_to_active_interpreter(self):
        command = normalize_python_commands("pip install demo && python -m pip --version && python3 script.py")
        executable = f'"{__import__("sys").executable}"'
        self.assertIn(f"{executable} -m pip install demo", command)
        self.assertIn(f"{executable} -m pip --version", command)
        self.assertIn(f"{executable} script.py", command)

    def test_elapsed_seconds_uses_finished_time(self):
        metadata = {
            "started_at": "2026-01-01T00:00:01+00:00",
            "finished_at": "2026-01-01T00:01:01+00:00",
        }
        self.assertEqual(_elapsed_seconds(metadata), 60)


if __name__ == "__main__":
    unittest.main()
