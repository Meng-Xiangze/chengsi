# -*- coding: utf-8 -*-
"""Execute a shell command and return stdout/stderr."""
import subprocess
from typing import Any

from tools.base import BaseTool


class Bash(BaseTool):
    @property
    def tool_name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command (cmd on Windows, bash on Linux/Mac). "
            "Returns stdout and stderr. PREFERRED for: file ops (ls, cp, mv, rm, mkdir, find), "
            "git (status, diff, log, commit), package installs (pip install), system info. "
            "Single-line commands are fastest — use bash for 1-shot terminal tasks. "
            "For multi-step logic, data processing, or complex scripting, use python_executor. "
            "Timeout: 60s."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "command": {
                "type": "string",
                "description": "Shell command to execute.",
            }
        }

    def run(self, arguments: dict[str, Any]) -> str:
        command = str(arguments.get("command", "")).strip()
        if not command:
            return "Error: command is required."

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                cwd=None,  # runs in the current working directory
            )
        except subprocess.TimeoutExpired:
            return "Error: command timed out after 60s."
        except Exception as e:
            return f"Error: {e}"

        parts = []
        if result.stdout:
            parts.append(result.stdout.rstrip())
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr.rstrip()}")
        if result.returncode != 0:
            parts.append(f"[exit code: {result.returncode}]")

        return "\n".join(parts) if parts else "(no output)"
