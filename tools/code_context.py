# -*- coding: utf-8 -*-
import os
import re
from typing import Any, Dict, List

from tools._hashline import anchor
from tools.base import BaseTool

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv",
    "node_modules", "assets", "sessions",
}
_TEXT_EXTS = {
    ".py", ".json", ".md", ".txt", ".yaml", ".yml", ".toml", ".cfg",
    ".ini", ".bat", ".sh", ".html", ".css", ".js", ".ts", ".tsx", ".jsx",
}


def _find_function_name(lines: List[str], lineno: int) -> str:
    """Find the nearest enclosing-looking function or class declaration."""
    for i in range(lineno, max(lineno - 100, -1), -1):
        match = re.match(r"^\s*(async\s+def|def|class)\s+([A-Za-z_]\w*)", lines[i])
        if match:
            return f"{match.group(1)} {match.group(2)}"
    return "-"


def _normalise_extension(value: Any) -> str:
    ext = str(value or "").strip().lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return ext


class CodeContext(BaseTool):
    """Search project text files and return matching lines with context."""

    @property
    def tool_name(self) -> str:
        return "code_context"

    @property
    def description(self) -> str:
        return (
            "Search project files for a keyword or regular expression. Returns matching "
            "lines with file paths, line numbers, and surrounding context."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "query": {"type": "string", "description": "Required keyword or regex."},
            "ext": {"type": "string", "description": "Optional extension, e.g. py or .py."},
            "max_results": {"type": "integer", "description": "Maximum matches, default 20."},
        }

    def run(self, arguments: Dict[str, Any]) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return "Error: query is required."

        try:
            pattern = re.compile(query, re.IGNORECASE)
            query_mode = "regex"
        except re.error as exc:
            # A typo in a regex should not make the tool unusable; search it literally.
            pattern = re.compile(re.escape(query), re.IGNORECASE)
            query_mode = f"literal fallback ({exc})"

        try:
            max_results = max(1, min(int(arguments.get("max_results", 20)), 200))
        except (TypeError, ValueError):
            max_results = 20
        ext_filter = _normalise_extension(arguments.get("ext"))
        results: List[str] = []
        total_matches = 0

        for root, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [
                d for d in dirs
                if d not in _SKIP_DIRS and not d.startswith("self-agent_backup_")
            ]
            for fname in sorted(files, key=str.lower):
                if ext_filter and not fname.lower().endswith(ext_filter):
                    continue
                suffix = os.path.splitext(fname)[1].lower()
                if suffix and suffix not in _TEXT_EXTS:
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as handle:
                        file_lines = handle.readlines()
                except (OSError, UnicodeError):
                    continue

                for idx, line in enumerate(file_lines):
                    if not pattern.search(line):
                        continue
                    total_matches += 1
                    if len(results) < max_results:
                        start = max(idx - 3, 0)
                        end = min(idx + 4, len(file_lines))
                        context = "".join(
                            f"  {'>' if row == idx else ' '} {anchor(row + 1, file_lines[row].rstrip(chr(10)).rstrip(chr(13)))}|"
                            f"{file_lines[row].rstrip()}\n"
                            for row in range(start, end)
                        )
                        rel = os.path.relpath(fpath, PROJECT_ROOT)
                        results.append(
                            f"--- {rel}:{idx + 1} ({_find_function_name(file_lines, idx)}) ---\n"
                            f"{context}"
                        )

        if not results:
            return f"No matches found for '{query}'."

        note = f"; regex: {query_mode}" if query_mode != "regex" else ""
        truncated = " (showing first %d)" % max_results if total_matches > max_results else ""
        return f"Found {total_matches} match(es){truncated} for '{query}'{note}:\n\n" + "\n".join(results)
