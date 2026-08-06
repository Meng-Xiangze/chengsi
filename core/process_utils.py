"""Shared child-process environment and Windows-safe output decoding."""

from __future__ import annotations

import json
import locale
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def optional_import(module: str, package: str | None = None):
    """Import an optional module; auto-install it when the user opted in.

    Returns the imported module or raises ``ImportError`` when the package
    is unavailable and *auto_install_dependencies* is disabled in config.json.
    """
    try:
        return __import__(module)
    except ImportError as original:
        if package is None:
            package = module
        config_path = Path(__file__).resolve().parent.parent / "config.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            config = {}
        if not config.get("auto_install_dependencies", False):
            raise original
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "install", package],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-1000:]
            raise ImportError(
                f"Automatic installation of {package} failed: {detail}"
            ) from original
        return __import__(module)


def pythonw_executable() -> str:
    """Return the path to pythonw.exe on Windows, python on other platforms.

    pythonw.exe runs without a console window — use for background jobs,
    delegates, and scheduled tasks to avoid popping up a black cmd window.
    """
    if os.name == "nt":
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.isfile(pythonw):
            return pythonw
    return sys.executable


def normalize_path(raw: str) -> str:
    """Normalize a user-supplied path for Windows robustness.

    Only does two things beyond what ``os.path.normpath`` already handles:
    1. Strips surrounding quotes (model sometimes wraps paths in '"..."').
    2. Strips leading/trailing whitespace.

    Everything else — slash conversion, separator collapsing, UNC preservation,
    ``.`` / ``..`` resolution — is delegated to ``os.path.normpath`` which has
    been battle-tested across Windows releases for decades.
    """
    if not raw:
        return ""
    s = raw.strip()
    # Strip surrounding matching quotes (model sometimes wraps paths)
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1].strip()
    # Let the OS handle the rest: / → \, \\ → \, . / .., UNC
    return os.path.normpath(s)


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
    command = _normalize_shell_paths(command)
    command = _translate_unix_command(command)
    if os.name == "nt":
        return f"chcp 65001 >nul 2>&1 & {command}"
    return command


def _normalize_shell_paths(command: str) -> str:
    """Convert Windows backslash paths to forward slashes inside shell commands.

    cmd.exe accepts ``C:/Users/MengX/file.txt`` just fine, and forward slashes
    don't get mangled by JSON escaping or Python string handling.
    """
    if os.name != "nt":
        return command
    # 1) Collapse JSON double-escape artifacts (C:\\\\Users → C:\\Users)
    #    Only inside what looks like a path, not regex escapes like \\d.
    #    Drive-letter head: C:\\U → C:\U
    command = re.sub(
        r'([a-zA-Z]):\\\\([a-zA-Z])',
        r'\1:\\\2',
        command,
    )
    #    Mid-path double slashes: Users\\\MengX → Users\MengX
    command = re.sub(
        r'(?<=[a-zA-Z0-9_])\\\\(?=[a-zA-Z0-9_.])',
        r'\\',
        command,
    )
    # 2) Convert drive-letter backslash paths to forward slash
    command = re.sub(
        r'(?<![a-zA-Z])([a-zA-Z]):\\',
        r'\1:/',
        command,
    )
    # 3) Replace remaining backslash path separators, but only between
    #    alphanumeric chars (leaves regex escapes like \d, \s, \\. alone).
    command = re.sub(r'(?<=[a-zA-Z0-9_])\\(?=[a-zA-Z0-9_.])', '/', command)
    return command


def _translate_unix_command(command: str) -> str:
    """Translate common Unix commands to native Windows equivalents.

    Only rewrites commands whose Unix form is missing or unreliable on the
    current Windows install (e.g. wmic is deprecated, head/grep from Git
    bash can choke on encoding or path separators).
    """
    if os.name != "nt":
        return command

    stripped = command.strip()
    first, rest = _split_first_word(stripped)

    # ── head ──────────────────────────────────────────────────────
    if first == "head":
        return _translate_head(rest)

    # ── grep ──────────────────────────────────────────────────────
    if first == "grep":
        return _translate_grep(rest)

    # ── wmic (removed from Windows 10 21H2+) ──────────────────────
    if first == "wmic":
        return _translate_wmic(rest)

    # ── rg / ripgrep — available; leave unchanged ─────────────────

    return command


def _split_first_word(s: str) -> tuple[str, str]:
    """Split 'cmd arg1 arg2' into ('cmd', 'arg1 arg2')."""
    s = s.strip()
    if not s:
        return "", ""
    # Respect double-quoted first word
    if s.startswith('"'):
        end = s.find('"', 1)
        if end != -1:
            return s[1:end], s[end + 1:].strip()
    parts = s.split(None, 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _translate_head(rest: str) -> str:
    """head -n N file  →  powershell Get-Content -First N"""
    import re
    m = re.match(r"^-n\s+(\d+)\s+(.+)", rest)
    if m:
        n, f = m.group(1), m.group(2).strip()
        return f'powershell -NoProfile -Command "Get-Content -LiteralPath \\"{f}\\" -First {n}"'
    # head file (default 10 lines)
    if rest.strip():
        f = rest.strip()
        return f'powershell -NoProfile -Command "Get-Content -LiteralPath \\"{f}\\" -First 10"'
    return "powershell -NoProfile -Command 'Get-Content -First 10'"


def _translate_grep(rest: str) -> str:
    """grep → findstr for simple cases, Select-String for complex.

    findstr supports basic regex; Select-String supports full .NET regex.
    We default to findstr (always present) for simple patterns and fall
    back to PowerShell for recursive or case-insensitive searches.
    """
    import re

    # Extract flags and pattern + files
    ignore_case = False
    recursive = False
    work = rest

    # Parse simple flags
    flag_re = re.match(r"^(-[a-zA-Z]+)\s+(.*)", work)
    if flag_re:
        flags = flag_re.group(1)
        work = flag_re.group(2)
        if "i" in flags:
            ignore_case = True
        if "r" in flags or "R" in flags:
            recursive = True

    # Extract pattern (first non-flag arg) and file(s)
    if work.startswith('"'):
        end = work.find('"', 1)
        pattern = work[1:end] if end != -1 else work[1:]
        files = work[end + 1:].strip() if end != -1 else ""
    elif work.startswith("'"):
        end = work.find("'", 1)
        pattern = work[1:end] if end != -1 else work[1:]
        files = work[end + 1:].strip() if end != -1 else ""
    else:
        parts = work.split(None, 1)
        pattern = parts[0] if parts else ""
        files = parts[1] if len(parts) > 1 else ""

    if not pattern:
        return "echo grep: missing pattern"

    # Build findstr command
    flags_str = ""
    if ignore_case:
        flags_str += " /I"
    if recursive:
        # findstr /S for recursive; append \* to file path if it's a directory
        flags_str += " /S"
        if files and not files.endswith("\\*") and not files.endswith("/*"):
            files = files.rstrip("\\").rstrip("/") + "\\*"

    if not files:
        files = "*"

    return f"findstr{flags_str} {pattern} {files}"


def _translate_wmic(rest: str) -> str:
    """wmic → PowerShell Get-CimInstance / Get-WmiObject.

    wmic was removed from Windows 10 21H2+ and Windows 11.
    Common patterns:
      wmic os get ...    →  Get-CimInstance Win32_OperatingSystem
      wmic cpu get ...   →  Get-CimInstance Win32_Processor
      wmic memorychip    →  Get-CimInstance Win32_PhysicalMemory
    """
    parts = rest.split()
    if not parts:
        return "echo wmic: missing arguments"

    class_map = {
        "os": "Win32_OperatingSystem",
        "cpu": "Win32_Processor",
        "memorychip": "Win32_PhysicalMemory",
        "diskdrive": "Win32_DiskDrive",
        "logicaldisk": "Win32_LogicalDisk",
        "bios": "Win32_BIOS",
        "baseboard": "Win32_BaseBoard",
        "computersystem": "Win32_ComputerSystem",
        "nic": "Win32_NetworkAdapter",
        "netadapter": "Win32_NetworkAdapter",
        "process": "Win32_Process",
        "service": "Win32_Service",
    }

    alias = parts[0].lower().rstrip("s")  # "os", "cpus" → "os", "cpu"
    wmi_class = class_map.get(alias)
    if not wmi_class:
        # Try original form
        wmi_class = class_map.get(parts[0].lower())
    if not wmi_class:
        return f'powershell -NoProfile -Command "Get-CimInstance {parts[0]}"'

    # Check if there's a 'get' clause
    get_idx = next((i for i, p in enumerate(parts) if p.lower() == "get"), -1)
    if get_idx != -1:
        props = ",".join(parts[get_idx + 1:])
        return f'powershell -NoProfile -Command "Get-CimInstance {wmi_class} | Select-Object {props} | Format-Table -AutoSize"'

    return f'powershell -NoProfile -Command "Get-CimInstance {wmi_class} | Format-Table -AutoSize"'


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


def decode_output_lines(value: bytes | str | None) -> str:
    """Decode possibly mixed-encoding output one line at a time.

    Windows children may emit UTF-8 (chcp 65001) for most lines while legacy
    cmd/PowerShell errors stay in GBK. Splitting on b'\n' is safe: neither
    UTF-8 nor GBK trail bytes contain 0x0A.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    parts = value.split(b"\n")
    return "\n".join(decode_output(part) for part in parts)
