"""Create persistent scheduled agent tasks."""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.base import BaseTool


def _schedule_root() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "Chengsi" / "schedules"
    else:
        root = Path.home() / ".chengsi" / "schedules"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _now() -> datetime:
    return datetime.now().astimezone()


def _parse_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    result = datetime.fromisoformat(text)
    if result.tzinfo is None:
        result = result.replace(tzinfo=_now().tzinfo)
    return result.astimezone()


class Schedule(BaseTool):
    @property
    def tool_name(self) -> str:
        return "schedule"

    @property
    def description(self) -> str:
        return (
            "Create and manage persistent scheduled agent tasks. At the scheduled time Chengsi "
            "starts a normal agent turn, so it can call web_searcher and other tools. Supports one-time "
            "and repeating interval tasks; use explicit local ISO time."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "action": {"type": "string", "enum": ["create", "list", "cancel"], "required": True},
            "prompt": {"type": "string", "description": "The work to perform when triggered. Required for create."},
            "run_at": {"type": "string", "description": "Local ISO datetime, for example 2026-08-01T09:30:00. Required for create."},
            "interval_seconds": {"type": "integer", "description": "Repeat interval in seconds. Omit for a one-time task."},
            "schedule_id": {"type": "string", "description": "Schedule identifier for cancel."},
        }

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        current_time = _now()
        action = str(arguments.get("action", "")).strip().lower()
        if action == "create":
            result = self._create(arguments, current_time)
        elif action == "list":
            result = self._list(arguments.get("_session_id", ""))
        elif action == "cancel":
            result = self._cancel(str(arguments.get("schedule_id", "")).strip(), arguments.get("_session_id", ""))
        else:
            result = {"ok": False, "content": "action must be create, list, or cancel.", "error_code": "invalid_arguments"}
        # Always return the authoritative local time so relative scheduling decisions
        # are based on the machine clock rather than the model's internal clock.
        result["current_time"] = current_time.isoformat()
        result["content"] = f"current_time: {current_time.isoformat()}\n{result.get('content', '')}"
        return result

    def _create(self, arguments: dict[str, Any], current_time: datetime | None = None) -> dict[str, Any]:
        current_time = current_time or _now()
        prompt = str(arguments.get("prompt", "")).strip()
        if not prompt:
            return {"ok": False, "content": "prompt is required for action=create.", "error_code": "invalid_arguments"}
        try:
            run_at = _parse_time(str(arguments.get("run_at", "")))
        except (TypeError, ValueError) as error:
            return {"ok": False, "content": f"run_at must be an ISO datetime: {error}", "error_code": "invalid_arguments"}
        if run_at <= current_time:
            return {"ok": False, "content": "run_at must be in the future.", "error_code": "invalid_arguments"}
        interval = arguments.get("interval_seconds")
        try:
            interval = int(interval) if interval is not None else None
        except (TypeError, ValueError):
            return {"ok": False, "content": "interval_seconds must be an integer.", "error_code": "invalid_arguments"}
        if interval is not None and interval < 60:
            return {"ok": False, "content": "interval_seconds must be at least 60.", "error_code": "invalid_arguments"}
        schedule_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        metadata = {
            "schedule_id": schedule_id,
            "session_id": str(arguments.get("_session_id") or ""),
            "prompt": prompt,
            "run_at": run_at.isoformat(),
            "interval_seconds": interval,
            "status": "scheduled",
            "created_at": _now().isoformat(),
            "last_run_at": "",
        }
        path = _schedule_root() / f"{schedule_id}.json"
        path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        repeat = f", repeats every {interval} seconds" if interval else ""
        return {"ok": True, "content": f"Scheduled task created.\nschedule_id: {schedule_id}\nrun_at: {metadata['run_at']}{repeat}", "error_code": "ok", "schedule_id": schedule_id}

    def _list(self, session_id: str) -> dict[str, Any]:
        entries = []
        for path in sorted(_schedule_root().glob("*.json"), reverse=True):
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))
                if session_id and metadata.get("session_id") != session_id:
                    continue
                entries.append(metadata)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return {"ok": True, "content": json.dumps(entries, ensure_ascii=False), "schedules": entries, "error_code": "ok"}

    def _cancel(self, schedule_id: str, session_id: str) -> dict[str, Any]:
        if not schedule_id:
            return {"ok": False, "content": "schedule_id is required for action=cancel.", "error_code": "invalid_arguments"}
        path = _schedule_root() / f"{schedule_id}.json"
        if not path.is_file():
            return {"ok": False, "content": f"Schedule not found: {schedule_id}", "error_code": "not_found"}
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if session_id and metadata.get("session_id") != session_id:
            return {"ok": False, "content": "Schedule belongs to another session.", "error_code": "not_found"}
        metadata["status"] = "cancelled"
        metadata["cancelled_at"] = _now().isoformat()
        path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "content": f"Cancelled scheduled task: {schedule_id}", "error_code": "ok"}
