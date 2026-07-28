"""Detached command runner used by the job tool."""
import argparse
import json
import os
import subprocess
import sys
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
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0

    try:
        with log_path.open("a", encoding="utf-8", errors="replace", buffering=1) as log:
            process = subprocess.Popen(
                metadata["command"],
                shell=True,
                cwd=metadata["cwd"],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
            )
            _write_metadata(metadata_path, {
                "status": "running",
                "runner_pid": os.getpid(),
                "command_pid": process.pid,
                "started_at": _now(),
            })
            return_code = process.wait()
        _write_metadata(metadata_path, {
            "status": "completed" if return_code == 0 else "failed",
            "exit_code": return_code,
            "finished_at": _now(),
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