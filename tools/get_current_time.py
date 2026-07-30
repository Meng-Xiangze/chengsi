# -*- coding: utf-8 -*-
"""Get current date and time without calling shell commands."""
from datetime import datetime, timezone
from typing import Any

from tools.base import BaseTool


class GetCurrentTime(BaseTool):
    @property
    def tool_name(self) -> str:
        return "get_current_time"

    @property
    def description(self) -> str:
        return (
            "Get the current date and time in various formats. "
            "Use this instead of 'bash date' (which hangs on Windows). "
            "Returns ISO 8601 timestamp by default. "
            "Supports: iso, datetime, date, time, unix formats. "
            "Can return local or UTC time."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "format": {
                "type": "string",
                "description": (
                    "Output format: 'iso' (default, e.g., 2026-07-30T17:25:30+08:00), "
                    "'datetime' (e.g., 2026-07-30 17:25:30), "
                    "'date' (e.g., 2026-07-30), "
                    "'time' (e.g., 17:25:30), "
                    "'unix' (seconds since epoch)"
                ),
                "enum": ["iso", "datetime", "date", "time", "unix"],
                "default": "iso"
            },
            "timezone_name": {
                "type": "string",
                "description": "Timezone: 'local' (default) or 'utc'",
                "enum": ["local", "utc"],
                "default": "local"
            }
        }

    def run(self, arguments: dict[str, Any]) -> str | dict[str, Any]:
        format_type = arguments.get("format", "iso")
        timezone_name = arguments.get("timezone_name", "local")
        
        if timezone_name == "utc":
            now = datetime.now(timezone.utc)
        else:
            now = datetime.now().astimezone()
        
        if format_type == "iso":
            result = now.isoformat()
        elif format_type == "datetime":
            result = now.strftime("%Y-%m-%d %H:%M:%S")
        elif format_type == "date":
            result = now.strftime("%Y-%m-%d")
        elif format_type == "time":
            result = now.strftime("%H:%M:%S")
        elif format_type == "unix":
            result = str(int(now.timestamp()))
        else:
            result = now.isoformat()
        
        return {
            "current_time": result,
            "format": format_type,
            "timezone": "UTC" if timezone_name == "utc" else "Local"
        }
