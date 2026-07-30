# -*- coding: utf-8 -*-
"""Execute a shell command and return stdout/stderr."""
import os
import shutil
import subprocess
from typing import Any

from core.process_utils import child_environment, decode_output, prepare_shell_command
from tools.base import BaseTool


class Bash(BaseTool):
    @property
    def tool_name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command in the project's configured child environment "
            "(cmd.exe on Windows, bash on Linux/Mac). Python commands use this project's .venv. "
            "Returns stdout and stderr. PREFERRED for: file ops (ls, cp, mv, rm, mkdir, find), "
            "git (status, diff, log, commit), package installs (python -m pip), system info. "
            "Single-line commands are fastest — use bash for 1-shot terminal tasks. "
            "For multi-step logic, data processing, or complex scripting, use python_executor. "
            "For commands that may run longer than one minute, use job so they continue in the background. "
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

    def run(self, arguments: dict[str, Any]) -> str | dict[str, Any]:
        command = str(arguments.get("command", "")).strip()
        if not command:
            return "Error: command is required."

        try:
            shell = os.environ.get("COMSPEC", "cmd.exe") if os.name == "nt" else "/bin/bash"
            result = subprocess.run(
                prepare_shell_command(command),
                shell=True,
                executable=shell,
                capture_output=True,
                timeout=60,
                cwd=None,
                env=child_environment(),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "content": "Command timed out after 60s.",
                "error_code": "timeout",
            }
        except Exception as e:
            return {
                "ok": False,
                "content": str(e),
                "error_code": "tool_error",
            }

        parts = []
        stdout = decode_output(result.stdout)
        stderr = decode_output(result.stderr)
        if stdout:
            parts.append(stdout.rstrip())
        if stderr:
            parts.append(f"[stderr]\n{stderr.rstrip()}")
        if result.returncode != 0:
            parts.append(f"[exit code: {result.returncode}]")

        content = "\n".join(parts) if parts else "(no output)"
        return {
            "ok": result.returncode == 0,
            "content": content,
            "error_code": "ok" if result.returncode == 0 else "nonzero_exit",
            "exit_code": result.returncode,
        }