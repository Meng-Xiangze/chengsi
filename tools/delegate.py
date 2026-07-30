"""Delegate sub-agent tasks that run autonomously in the background.

Sub-agents have full tool access, run independently, and report results
back to the parent session as read-only conversation logs.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.base import BaseTool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _delegate_root() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "Chengsi" / "delegates"
    else:
        root = Path.home() / ".chengsi" / "delegates"
    root.mkdir(parents=True, exist_ok=True)
    return root


class Delegate(BaseTool):
    @property
    def tool_name(self) -> str:
        return "delegate"

    @property
    def description(self) -> str:
        return (
            "Delegate a complex or long-running task to a sub-agent that runs autonomously "
            "in the background. The sub-agent has FULL tool access (bash, read, write, edit, "
            "web_searcher, python_executor, etc.) and works independently. Use this when a "
            "task is large enough that it would benefit from being broken out (research, "
            "data processing, multi-step file generation, code audits). "
            "You (the main agent) remain free to handle other user requests or wait for "
            "the result. Check status with action=status or action=list."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "enum": ["start", "status", "list", "cancel", "export"],
                "required": True,
            },
            "prompt": {
                "type": "string",
                "description": "The task for the sub-agent to perform. Be specific about what to produce. Required for action=start.",
            },
            "delegate_id": {
                "type": "string",
                "description": "Identifier for a specific delegate. Required for action=status/cancel/export.",
            },
            "format": {
                "type": "string",
                "enum": ["html", "markdown"],
                "description": "Export format for action=export. Default: html.",
            },
        }

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action", "")).strip().lower()
        session_id = str(arguments.get("_session_id", ""))

        if action == "start":
            return self._start(arguments, session_id)
        elif action == "status":
            return self._status(str(arguments.get("delegate_id", "")).strip(), session_id)
        elif action == "list":
            return self._list(session_id)
        elif action == "cancel":
            return self._cancel(str(arguments.get("delegate_id", "")).strip(), session_id)
        elif action == "export":
            return self._export(
                str(arguments.get("delegate_id", "")).strip(),
                str(arguments.get("format", "html")).strip().lower() or "html",
                session_id,
            )
        else:
            return {"ok": False, "content": "action must be start, status, list, cancel, or export.", "error_code": "invalid_arguments"}

    def _start(self, arguments: dict[str, Any], session_id: str) -> dict:
        prompt = str(arguments.get("prompt", "")).strip()
        if not prompt:
            return {"ok": False, "content": "prompt is required for action=start.", "error_code": "invalid_arguments"}

        delegate_id = uuid.uuid4().hex[:12]
        session_dir = _delegate_root() / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = session_dir / f"{delegate_id}.json"

        # Capture the active provider/model NOW so the sub-agent uses
        # the same backend the user was on when they issued the command.
        from main import _provider_name, _provider_model, _current_provider_cfg
        metadata = {
            "delegate_id": delegate_id,
            "session_id": session_id,
            "prompt": prompt,
            "status": "queued",
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "error": "",
            "summary": "",
            "messages": [],
            "tool_call_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            # Provider snapshot — frozen at creation time
            "__provider": _provider_name,
            "__model": _provider_model,
            "__provider_cfg": dict(_current_provider_cfg) if _current_provider_cfg else {},
            "__provider_type": _current_provider_cfg.get("type", "ollama") if _current_provider_cfg else "ollama",
        }

        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "ok": True,
            "content": (
                f"Sub-agent started: {delegate_id}\n"
                f"Status: queued (will begin shortly)\n"
                f"Task: {prompt[:200]}\n"
                f"Use delegate(action='status', delegate_id='{delegate_id}') to check progress."
            ),
            "delegate_id": delegate_id,
        }

    def _status(self, delegate_id: str, session_id: str) -> dict:
        if not delegate_id:
            return {"ok": False, "content": "delegate_id is required.", "error_code": "invalid_arguments"}

        metadata = self._find_metadata(delegate_id, session_id)
        if metadata is None:
            return {"ok": False, "content": f"Delegate not found: {delegate_id}", "error_code": "not_found"}

        status = metadata.get("status", "unknown")
        summary = metadata.get("summary", "")
        tool_calls = metadata.get("tool_call_count", 0)
        
        lines = [
            f"Delegate: {delegate_id}",
            f"Status: {status}",
            f"Task: {metadata.get('prompt', '')[:200]}",
        ]
        
        if metadata.get("started_at"):
            lines.append(f"Started: {metadata['started_at']}")
        if metadata.get("finished_at"):
            lines.append(f"Finished: {metadata['finished_at']}")
        if tool_calls:
            lines.append(f"Tool calls made: {tool_calls}")
        if summary:
            lines.append(f"Summary: {summary[:500]}")
        if status == "running":
            # Count how many messages so far
            msg_count = len(metadata.get("messages", []))
            lines.append(f"Messages so far: {msg_count}")
        if metadata.get("error"):
            lines.append(f"Error: {metadata['error'][:300]}")

        return {"ok": True, "content": "\n".join(lines), "status": status, "delegate_id": delegate_id}

    def _list(self, session_id: str) -> dict:
        session_dir = _delegate_root() / session_id
        if not session_dir.exists():
            return {"ok": True, "content": "No delegates for this session.", "delegates": []}

        delegates = []
        for path in sorted(session_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
                delegates.append({
                    "delegate_id": meta.get("delegate_id", path.stem),
                    "status": meta.get("status", "unknown"),
                    "prompt": meta.get("prompt", "")[:120],
                    "created_at": meta.get("created_at", ""),
                    "finished_at": meta.get("finished_at", ""),
                    "tool_call_count": meta.get("tool_call_count", 0),
                })
            except (OSError, json.JSONDecodeError):
                continue

        if not delegates:
            return {"ok": True, "content": "No delegates for this session.", "delegates": []}

        lines = [f"Delegates for this session ({len(delegates)}):"]
        for d in delegates:
            icon = {"running": "⏳", "completed": "✅", "failed": "❌", "queued": "📋", "cancelled": "🚫"}.get(d["status"], "❓")
            lines.append(f"  {icon} {d['delegate_id']} [{d['status']}] - {d['prompt'][:100]}")
        return {"ok": True, "content": "\n".join(lines), "delegates": delegates}

    def _cancel(self, delegate_id: str, session_id: str) -> dict:
        if not delegate_id:
            return {"ok": False, "content": "delegate_id is required.", "error_code": "invalid_arguments"}

        metadata_path = self._find_path(delegate_id, session_id)
        if metadata_path is None:
            return {"ok": False, "content": f"Delegate not found: {delegate_id}", "error_code": "not_found"}

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("status") in ("completed", "failed", "cancelled"):
                return {"ok": True, "content": f"Delegate {delegate_id} is already {metadata['status']}."}
            metadata["status"] = "cancelled"
            metadata["finished_at"] = _now()
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": True, "content": f"Delegate {delegate_id} cancelled."}
        except OSError as e:
            return {"ok": False, "content": f"Failed to cancel: {e}", "error_code": "io_error"}

    def _export(self, delegate_id: str, fmt: str, session_id: str) -> dict:
        if not delegate_id:
            return {"ok": False, "content": "delegate_id is required.", "error_code": "invalid_arguments"}

        metadata = self._find_metadata(delegate_id, session_id)
        if metadata is None:
            return {"ok": False, "content": f"Delegate not found: {delegate_id}", "error_code": "not_found"}

        messages = metadata.get("messages", [])
        if not messages:
            return {"ok": False, "content": "No messages to export yet.", "error_code": "empty"}

        out_dir = _delegate_root() / session_id
        out_dir.mkdir(parents=True, exist_ok=True)

        if fmt == "markdown":
            content = self._to_markdown(delegate_id, metadata, messages)
            ext = "md"
        else:
            content = self._to_html(delegate_id, metadata, messages)
            ext = "html"

        out_path = out_dir / f"{delegate_id}_export.{ext}"
        out_path.write_text(content, encoding="utf-8")
        return {"ok": True, "content": f"Exported to {out_path}", "export_path": str(out_path)}

    def _to_markdown(self, delegate_id: str, metadata: dict, messages: list) -> str:
        lines = [
            f"# Sub-agent: {delegate_id}",
            f"**Status**: {metadata.get('status', 'unknown')}",
            f"**Task**: {metadata.get('prompt', '')}",
            f"**Created**: {metadata.get('created_at', '')}",
            f"**Finished**: {metadata.get('finished_at', '')}",
            f"**Tool calls**: {metadata.get('tool_call_count', 0)}",
            "",
            "---",
            "",
        ]
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(str(c.get("text", "")) for c in content if c.get("text"))
            lines.append(f"### {role}")
            lines.append("")
            lines.append(str(content))
            lines.append("")
        return "\n".join(lines)

    def _to_html(self, delegate_id: str, metadata: dict, messages: list) -> str:
        parts = [
            "<!DOCTYPE html><html><head><meta charset='utf-8'>",
            "<title>Chengsi Sub-agent Export</title>",
            "<style>",
            "body { font-family: -apple-system, sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; line-height: 1.6; color: #333; }",
            "h1 { border-bottom: 2px solid #4a90d9; padding-bottom: .3em; }",
            ".meta { background: #f5f7fa; padding: 1em; border-radius: 8px; margin: 1em 0; }",
            ".meta dt { font-weight: bold; }",
            ".msg { margin: 1em 0; padding: .8em; border-radius: 8px; }",
            ".assistant { background: #e8f4e8; }",
            ".user { background: #e8eaf4; }",
            ".tool { background: #fef9e7; font-family: monospace; font-size: .9em; white-space: pre-wrap; }",
            ".system { background: #f0f0f0; font-size: .85em; }",
            ".role { font-weight: bold; text-transform: uppercase; font-size: .75em; margin-bottom: .3em; color: #666; }",
            "</style></head><body>",
            f"<h1>Sub-agent: {delegate_id}</h1>",
            "<dl class='meta'>",
            f"<dt>Status</dt><dd>{metadata.get('status', 'unknown')}</dd>",
            f"<dt>Task</dt><dd>{metadata.get('prompt', '')}</dd>",
            f"<dt>Created</dt><dd>{metadata.get('created_at', '')}</dd>",
            f"<dt>Finished</dt><dd>{metadata.get('finished_at', '')}</dd>",
            f"<dt>Tool calls</dt><dd>{metadata.get('tool_call_count', 0)}</dd>",
            "</dl>",
        ]
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "<br>".join(f"{c.get('text', '')}" for c in content if c.get("text"))
            content = str(content).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            parts.append(f"<div class='msg {role}'>")
            parts.append(f"<div class='role'>{role}</div>")
            parts.append(f"<div>{content}</div>")
            parts.append("</div>")
        parts.append("</body></html>")
        return "\n".join(parts)

    def _find_metadata(self, delegate_id: str, session_id: str) -> dict | None:
        path = self._find_path(delegate_id, session_id)
        if path is None:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _find_path(self, delegate_id: str, session_id: str) -> Path | None:
        session_dir = _delegate_root() / session_id
        path = session_dir / f"{delegate_id}.json"
        if path.exists():
            return path
        # Try direct path (in case delegate_id already has full path)
        direct = _delegate_root() / f"{delegate_id}.json"
        if direct.exists():
            return direct
        # Search all session dirs
        for d in _delegate_root().iterdir():
            if d.is_dir():
                candidate = d / f"{delegate_id}.json"
                if candidate.exists():
                    return candidate
        return None
