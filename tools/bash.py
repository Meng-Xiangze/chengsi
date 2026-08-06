# -*- coding: utf-8 -*-
"""Execute a shell command and return stdout/stderr."""
import os
import signal
import subprocess
import threading
import time
from typing import Any

from core.process_utils import child_environment, decode_output, decode_output_lines, normalize_path, prepare_shell_command
from tools.base import BaseTool


def _read_stream(stream, buffer: list[str], lock: threading.Lock, on_output=None):
    """Read a binary stream line by line, decoding each line tolerantly."""
    try:
        for raw_line in iter(stream.readline, b""):
            line = decode_output_lines(raw_line)
            with lock:
                buffer.append(line)
            if callable(on_output):
                on_output(line)
    except (ValueError, OSError):
        pass


class Bash(BaseTool):
    @property
    def tool_name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command in the project's configured child environment "
            "(cmd.exe on Windows, bash on Linux/Mac). Python commands use this project's .venv. "
            "Returns stdout and stderr. PREFERRED for quick command-line programs: git status/diff/log, rg, fd, "
            "small tests, version checks, and system utilities. For pip install/download, package or software "
            "installers, curl/wget/Invoke-WebRequest downloads, git clone, dependency setup, large archive extraction, "
            "or builds likely to exceed about 30 seconds, use job(action='start') instead. "
            "Use read, write, and edit for normal file work. Use python_executor for calculations, "
            "structured data processing, or direct Python library APIs. "
            "For commands that may run longer than 5 minutes, use job so they continue in the background. "
            "The model should set an appropriate timeout based on the command: fast ops 5-15s, moderate 30-60s. "
            "Default timeout: 30s. Max: 600s (10 min). Partial output is returned on timeout."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "command": {
                "type": "string",
                "description": "Shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait for a quick foreground command. Default 30. Use 5-15 for fast ops and 30-60 for moderate ops. Route pip install/download, installers, downloads, clones, and long builds to job instead.",
            },
            "cwd": {
                "type": "string",
                "description": "Optional working directory. Defaults to the Chengsi project root.",
            },
        }

    def run(self, arguments: dict[str, Any]) -> str | dict[str, Any]:
        command = str(arguments.get("command", "")).strip()
        if not command:
            return "Error: command is required."

        try:
            timeout = max(5, min(int(arguments.get("timeout", 30)), 600))
        except (TypeError, ValueError):
            return {"ok": False, "content": "timeout must be an integer between 5 and 600 seconds.", "error_code": "invalid_arguments"}
        progress = arguments.get("_progress")
        progress_lock = threading.Lock()
        pending_progress: list[str] = []
        pending_chars = 0
        last_progress_at = 0.0

        def report_progress(chunk: str, force: bool = False) -> None:
            nonlocal pending_chars, last_progress_at
            if not callable(progress):
                return
            with progress_lock:
                pending_progress.append(chunk)
                pending_chars += len(chunk)
                now = time.monotonic()
                if not force and pending_chars < 4096 and now - last_progress_at < 0.25:
                    return
                text = "".join(pending_progress)
                pending_progress.clear()
                pending_chars = 0
                last_progress_at = now
            progress(text)

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        raw_cwd = normalize_path(str(arguments.get("cwd", "")))
        cwd = os.path.abspath(os.path.expanduser(raw_cwd)) if raw_cwd else project_root
        if not os.path.isdir(cwd):
            return {"ok": False, "content": f"Working directory does not exist: {cwd}", "error_code": "invalid_arguments"}

        creationflags = 0
        popen_kwargs: dict[str, Any] = {}
        if os.name == "nt":
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        else:
            popen_kwargs["start_new_session"] = True
        shell = os.environ.get("COMSPEC", "cmd.exe") if os.name == "nt" else "/bin/bash"

        try:
            proc = subprocess.Popen(
                prepare_shell_command(command),
                shell=True,
                executable=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=child_environment(),
                creationflags=creationflags,
                **popen_kwargs,
            )
        except OSError as e:
            return {"ok": False, "content": f"Could not start command: {e}", "error_code": "tool_error"}

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        lock = threading.Lock()
        t_out = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_lines, lock, report_progress), daemon=True)
        t_err = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_lines, lock, report_progress), daemon=True)
        t_out.start()
        t_err.start()

        def kill_tree() -> None:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        capture_output=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        timeout=5,
                    )
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                try:
                    proc.kill()
                except OSError:
                    pass

        timed_out = False
        cancelled = False
        cancel_event = arguments.get("_cancel_event")
        deadline = time.monotonic() + timeout
        # Poll instead of blocking proc.wait(): Stop must interrupt a stuck
        # command within ~100ms, not after its (up to 600s) timeout expires.
        while True:
            if proc.poll() is not None:
                break
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                kill_tree()
                break
            if time.monotonic() >= deadline:
                timed_out = True
                kill_tree()
                break
            time.sleep(0.1)

        t_out.join(timeout=1)
        t_err.join(timeout=1)
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except (AttributeError, OSError):
                pass
        report_progress("", force=True)

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        return_code = proc.poll()

        if cancelled:
            parts = []
            if stdout.strip():
                parts.append(stdout.rstrip())
            if stderr.strip():
                parts.append(f"[stderr]\n{stderr.rstrip()}")
            parts.append("[CANCELLED by user — partial output above; do not retry this command unchanged]")
            return {"ok": False, "content": "\n".join(parts), "error_code": "user_cancelled", "exit_code": return_code}

        if timed_out:
            if stdout.strip() or stderr.strip():
                # Show partial output captured before timeout
                parts = []
                if stdout.strip():
                    parts.append(stdout.rstrip())
                if stderr.strip():
                    parts.append(f"[stderr]\n{stderr.rstrip()}")
                parts.append(f"[TIMEOUT after {timeout}s — partial output above; use job for long-running commands]")
                return {"ok": False, "content": "\n".join(parts), "error_code": "timeout", "exit_code": return_code}
            return {"ok": False, "content": f"Command timed out after {timeout}s with no output.", "error_code": "timeout"}

        parts = []
        if stdout:
            parts.append(stdout.rstrip())
        if stderr:
            parts.append(f"[stderr]\n{stderr.rstrip()}")
        if return_code != 0:
            parts.append(f"[exit code: {return_code}]")

        content = "\n".join(parts) if parts else "(no output)"
        return {
            "ok": return_code == 0,
            "content": f"[cwd: {cwd}]\n{content}",
            "error_code": "ok" if return_code == 0 else "nonzero_exit",
            "exit_code": return_code,
            "cwd": cwd,
        }