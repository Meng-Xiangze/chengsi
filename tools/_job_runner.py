"""Detached command runner used by the job tool."""
import argparse
import json
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from core.process_utils import child_environment, prepare_shell_command

os.environ.update(child_environment())
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _write_metadata(path: Path, updates: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.update(updates)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return data


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata")
    args = parser.parse_args()
    metadata_path = Path(args.metadata).resolve()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    log_path = Path(metadata["log_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        with log_path.open("a", encoding="utf-8", errors="replace", buffering=1) as log:
            process = subprocess.Popen(
                prepare_shell_command(metadata["command"]),
                shell=True,
                cwd=metadata["cwd"],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                env=child_environment(),
            )
            _write_metadata(metadata_path, {
                "status": "running",
                "runner_pid": os.getpid(),
                "command_pid": process.pid,
                "started_at": _now(),
                "last_activity_at": _now(),
            })
            log_bytes_prev = 0
            while True:
                rc = process.poll()
                if rc is not None:
                    return_code = rc
                    break
                try:
                    cur = log_path.stat().st_size
                    if cur != log_bytes_prev:
                        log_bytes_prev = cur
                        _write_metadata(metadata_path, {
                            "last_activity_at": _now(),
                            "log_bytes": cur,
                        })
                except OSError:
                    pass
                time.sleep(5)
        _write_metadata(metadata_path, {
            "status": "completed" if return_code == 0 else "failed",
            "exit_code": return_code,
            "error": "" if return_code == 0 else f"Command exited with code {return_code}.",
            "finished_at": _now(),
            "last_activity_at": _now(),
        })
        return return_code
    except BaseException as error:
        _write_metadata(metadata_path, {
            "status": "failed",
            "error": str(error),
            "finished_at": _now(),
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())