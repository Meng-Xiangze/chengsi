"""Shared child-process environment and Windows-safe output decoding."""

from __future__ import annotations

import locale
import os
import re
import sys


def child_environment() -> dict[str, str]:
    """Return one consistent environment for all Chengsi child processes."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["CHENGSI_ROOT"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if sys.prefix and sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        scripts = os.path.join(sys.prefix, "Scripts" if os.name == "nt" else "bin")
        current_path = env.get("PATH", "")
        if scripts not in current_path.split(os.pathsep):
            env["PATH"] = scripts + os.pathsep + current_path
        env["VIRTUAL_ENV"] = sys.prefix
    return env


def normalize_python_commands(command: str) -> str:
    """Bind common Python/pip command forms to Chengsi's active interpreter."""
    executable = f'"{sys.executable}"'
    patterns = [
        (r"(?i)(^|&&\s*|\|\|\s*|;\s*)pip3?(?=\s|$)", lambda match: match.group(1) + executable + " -m pip"),
        (r"(?i)(^|&&\s*|\|\|\s*|;\s*)python3?(?:\.\d+)?(?=\s|$)", lambda match: match.group(1) + executable),
    ]
    result = command
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)
    return result


def prepare_shell_command(command: str) -> str:
    """Run commands with the active interpreter and UTF-8 Windows code page."""
    command = normalize_python_commands(command)
    if os.name == "nt":
        return f"chcp 65001 >nul 2>&1 & {command}"
    return command


def decode_output(value: bytes | str | None) -> str:
    """Decode subprocess bytes without turning Chinese output into mojibake."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    for encoding in ("utf-8-sig", locale.getpreferredencoding(False), "gb18030"):
        try:
            return value.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return value.decode("utf-8", errors="replace")
