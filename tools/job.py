"""Start and manage persistent background shell jobs."""
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.process_utils import child_environment
from tools.base import BaseTool

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_root() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "Chengsi" / "jobs"
    else:
        root = Path.home() / ".chengsi" / "jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _process_tree_alive(metadata: dict) -> bool:
    """Check the runner and command process separately for orphan detection."""
    return _process_exists(int(metadata.get("runner_pid") or 0)) or _process_exists(int(metadata.get("command_pid") or 0))


def _normalize_windows_delay(command: str) -> str:
    """Translate the common Unix sleep-and-continue form for Windows shells."""
    if os.name != "nt":
        return command
    match = re.match(r"^\s*sleep\s+(\d+)\s*&&\s*(.+)$", command, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return command
    seconds, remainder = match.groups()
    return f"timeout /t {seconds} /nobreak >nul && {remainder.strip()}"


def _elapsed_seconds(metadata: dict) -> int | None:
    started = metadata.get("started_at") or metadata.get("created_at")
    if not started:
        return None
    try:
        end = metadata.get("finished_at")
        end_time = datetime.fromisoformat(end).timestamp() if end else time.time()
        return max(0, int(end_time - datetime.fromisoformat(started).timestamp()))
    except (TypeError, ValueError, OverflowError):
        return None


class Job(BaseTool):
    @property
    def tool_name(self) -> str:
        return "job"

    @property
    def description(self) -> str:
        return (
            "Manage detached shell jobs for commands that may run for minutes or hours. "
            "Start returns immediately with a job_id; use status, logs, list, or cancel later."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "enum": ["start", "status", "logs", "list", "cancel", "archive"],
                "description": "Job operation.",
                "required": True,
            },
            "command": {
                "type": "string",
                "description": "Shell command for action=start.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for action=start. Defaults to the current directory.",
            },
            "job_id": {
                "type": "string",
                "description": "Job identifier for status, logs, or cancel.",
            },
            "tail_lines": {
                "type": "integer",
                "description": "Number of trailing log lines to return. Default 100, maximum 1000.",
            },
            "include_history": {
                "type": "boolean",
                "description": "Include completed jobs in action=list. Failed, interrupted, and cancelled jobs are always included.",
            },
            "visible": {
                "type": "boolean",
                "description": "Show this job in the WebUI job panel. Defaults to false for agent-internal jobs.",
            },
            "auto_followup": {
                "type": "boolean",
                "description": "After the job finishes, automatically let Chengsi inspect the result and continue only when the user's request explicitly asked for that follow-up. Default false.",
            },
            "_visible_only": {
                "type": "boolean",
                "description": "Internal WebUI filter; do not set this in normal agent requests.",
            },
        }

    @staticmethod
    def _metadata_path(job_id: str) -> Path:
        safe_id = "".join(character for character in job_id if character.isalnum() or character in "-_")
        if not safe_id or safe_id != job_id:
            raise ValueError("Invalid job_id.")
        return _job_root() / f"{safe_id}.json"

    def _load(self, job_id: str) -> tuple[Path, dict]:
        path = self._metadata_path(job_id)
        if not path.is_file():
            raise FileNotFoundError(f"Job not found: {job_id}")
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata.get("status") in ("starting", "running"):
            runner_pid = int(metadata.get("runner_pid") or 0)
            command_pid = int(metadata.get("command_pid") or 0)
            created_at = metadata.get("created_at", "")
            started_at = metadata.get("started_at", "")
            try:
                created = datetime.fromisoformat(created_at).timestamp()
            except (TypeError, ValueError):
                created = 0
            try:
                started = datetime.fromisoformat(started_at).timestamp()
            except (TypeError, ValueError):
                started = 0
            startup_grace = metadata.get("status") == "starting" and time.time() - created < 10
            completion_grace = metadata.get("status") == "running" and time.time() - started < 10
            if not startup_grace and not completion_grace and not _process_tree_alive(metadata):
                metadata["status"] = "interrupted"
                metadata["finished_at"] = metadata.get("finished_at") or _now()
                metadata["error"] = metadata.get("error") or "Job process is no longer running; exit code is unavailable."
                path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return path, metadata

    def _start(self, arguments: dict[str, Any]) -> dict[str, Any]:
        requested_command = str(arguments.get("command", "")).strip()
        if not requested_command:
            return {"ok": False, "content": "command is required for action=start.", "error_code": "invalid_arguments"}
        command = _normalize_windows_delay(requested_command)
        cwd = Path(str(arguments.get("cwd") or os.getcwd())).expanduser().resolve()
        if not cwd.is_dir():
            return {"ok": False, "content": f"Working directory not found: {cwd}", "error_code": "not_found"}
        job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        root = _job_root()
        metadata_path = root / f"{job_id}.json"
        log_path = root / f"{job_id}.log"
        metadata = {
            "job_id": job_id,
            "command": command,
            "requested_command": requested_command,
            "cwd": str(cwd),
            "status": "starting",
            "created_at": _now(),
            "session_id": str(arguments.get("_session_id") or ""),
            "visible": bool(arguments.get("visible", True)),
            "auto_followup": bool(arguments.get("auto_followup", False)),
            "origin": "agent",
            "runner_pid": None,
            "command_pid": None,
            "exit_code": None,
            "log_path": str(log_path),
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        runner = Path(__file__).with_name("_job_runner.py")
        creationflags = 0
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen(
                [sys.executable, str(runner), str(metadata_path)],
                cwd=str(cwd), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, creationflags=creationflags,
                env=child_environment(), **kwargs,
            )
            return {
                "ok": True,
                "content": (
                    f"Background job accepted and started; it is NOT finished yet.\n"
                    f"job_id: {job_id}\nstatus: starting\nauto_followup: {str(metadata['auto_followup']).lower()}\nvisible: {str(metadata['visible']).lower()}\nlog: {log_path}"
                ),
                "error_code": "ok",
                "job_id": job_id,
            }
        except OSError as error:
            metadata.update({"status": "failed", "error": str(error), "finished_at": _now()})
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": False, "content": f"Could not start job: {error}", "error_code": "start_failed"}

    def _status(self, job_id: str) -> dict[str, Any]:
        _, metadata = self._load(job_id)
        runner_alive = _process_exists(int(metadata.get("runner_pid") or 0))
        command_alive = _process_exists(int(metadata.get("command_pid") or 0))
        fields = [
            f"job_id: {metadata['job_id']}", f"status: {metadata['status']}",
            f"command: {metadata['command']}", f"cwd: {metadata['cwd']}",
            f"created_at: {metadata.get('created_at', '')}",
            f"elapsed_seconds: {_elapsed_seconds(metadata)}",
            f"runner_alive: {str(runner_alive).lower()}",
            f"command_alive: {str(command_alive).lower()}",
        ]
        if metadata.get("started_at"):
            fields.append(f"started_at: {metadata['started_at']}")
        if metadata.get("finished_at"):
            fields.append(f"finished_at: {metadata['finished_at']}")
        if metadata.get("exit_code") is not None:
            fields.append(f"exit_code: {metadata['exit_code']}")
        if metadata.get("error"):
            fields.append(f"error: {metadata['error']}")
        fields.append(f"log: {metadata['log_path']}")
        return {"ok": True, "content": "\n".join(fields), "error_code": "ok"}

    def _logs(self, job_id: str, tail_lines: int) -> dict[str, Any]:
        _, metadata = self._load(job_id)
        log_path = Path(metadata["log_path"])
        if not log_path.is_file():
            content = "(no log output yet)"
        else:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            content = "\n".join(lines[-tail_lines:]) or "(no log output yet)"
        return {"ok": True, "content": f"job_id: {job_id}\nstatus: {metadata['status']}\n--- log tail ---\n{content}", "error_code": "ok"}

    def _list(self, include_history: bool = False, visible_only: bool = False) -> dict[str, Any]:
        entries = []
        visible_statuses = {"starting", "running", "failed", "interrupted", "cancelled", "timed_out"}
        for path in sorted(_job_root().glob("*.json"), reverse=True)[:100]:
            try:
                _, metadata = self._load(path.stem)
                if not include_history and metadata.get("archived_at"):
                    continue
                if visible_only and not metadata.get("visible", False):
                    continue
                if not include_history and metadata.get("status") not in visible_statuses:
                    continue
                elapsed = _elapsed_seconds(metadata)
                entries.append({
                    "job_id": metadata["job_id"],
                    "status": metadata["status"],
                    "command": metadata["command"],
                    "cwd": metadata["cwd"],
                    "created_at": metadata.get("created_at", ""),
                    "started_at": metadata.get("started_at", ""),
                    "finished_at": metadata.get("finished_at", ""),
                    "exit_code": metadata.get("exit_code"),
                    "elapsed_seconds": elapsed,
                    "runner_alive": _process_exists(int(metadata.get("runner_pid") or 0)),
                    "command_alive": _process_exists(int(metadata.get("command_pid") or 0)),
                    "log_path": metadata.get("log_path", ""),
                    "error": metadata.get("error", ""),
                    "session_id": metadata.get("session_id", ""),
                    "visible": bool(metadata.get("visible", False)),
                    "origin": metadata.get("origin", "agent"),
                    "agent_received_at": metadata.get("agent_received_at", ""),
                })
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return {
            "ok": True,
            "content": json.dumps(entries, ensure_ascii=False),
            "jobs": entries,
            "active": [entry for entry in entries if entry["status"] in {"starting", "running"}],
            "attention": [entry for entry in entries if entry["status"] in {"failed", "interrupted", "cancelled", "timed_out"}],
            "error_code": "ok",
        }

    def _archive(self, job_id: str) -> dict[str, Any]:
        path, metadata = self._load(job_id)
        if metadata.get("status") in {"starting", "running"}:
            return {"ok": False, "content": "Running jobs cannot be archived; cancel them first.", "error_code": "still_running"}
        metadata["visible"] = False
        metadata["archived_at"] = _now()
        path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "content": f"Archived background job: {job_id}", "error_code": "ok"}

    def _cancel(self, job_id: str) -> dict[str, Any]:
        path, metadata = self._load(job_id)
        if metadata["status"] not in ("starting", "running"):
            return {"ok": False, "content": f"Job is not running (status: {metadata['status']}).", "error_code": "not_running"}
        pid = int(metadata.get("runner_pid") or metadata.get("command_pid") or 0)
        if pid <= 0:
            return {"ok": False, "content": "Job is still starting; retry cancellation shortly.", "error_code": "starting"}
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                os.killpg(pid, signal.SIGTERM)
            metadata.update({"status": "cancelled", "finished_at": _now()})
            path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": True, "content": f"Cancelled background job: {job_id}", "error_code": "ok"}
        except OSError as error:
            return {"ok": False, "content": f"Could not cancel job: {error}", "error_code": "cancel_failed"}

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action", "")).strip().lower()
        try:
            if action == "start":
                return self._start(arguments)
            if action == "list":
                return self._list(
                    bool(arguments.get("include_history", False)),
                    visible_only=bool(arguments.get("_visible_only", False)),
                )
            job_id = str(arguments.get("job_id", "")).strip()
            if not job_id:
                return {"ok": False, "content": "job_id is required for this action.", "error_code": "invalid_arguments"}
            if action == "status":
                return self._status(job_id)
            if action == "logs":
                tail_lines = max(1, min(int(arguments.get("tail_lines", 100)), 1000))
                return self._logs(job_id, tail_lines)
            if action == "cancel":
                return self._cancel(job_id)
            if action == "archive":
                return self._archive(job_id)
            return {"ok": False, "content": "action must be start, status, logs, list, cancel, or archive.", "error_code": "invalid_arguments"}
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return {"ok": False, "content": str(error), "error_code": "job_error"}