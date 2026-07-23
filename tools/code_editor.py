import os
import re
import shutil
import tempfile
from typing import Any, Dict

from tools.base import BaseTool

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules"}


class CodeEditor(BaseTool):
    """Small, predictable file editor designed for local models.

    Keep the public API intentionally small: read, write, edit, search.
    Common aliases are accepted, but the model only needs to learn four actions.
    """

    @property
    def tool_name(self) -> str:
        return "code_editor"

    @property
    def description(self) -> str:
        return (
            "Read or safely modify project files. Three actions: read (view file contents), "
            "write (replace entire file), edit (targeted find-and-replace of one exact match). "
            "Use this for ALL file operations. Do NOT use python_executor to read or write files."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        # Flat, short descriptions and useful defaults are easier for small models.
        return {
            "action": {
                "type": "string",
                "description": "read, write, or edit (default: read). Use read before edit.",
            },
            "path": {
                "type": "string",
                "description": "Relative file path in the project.",
            },
            "content": {
                "type": "string",
                "description": "Complete file content for write. Empty content is allowed.",
            },
            "old": {
                "type": "string",
                "description": "Exact text to replace; edit changes the first match only.",
            },
            "new": {
                "type": "string",
                "description": "Replacement text for edit.",
            },
            "backup": {
                "type": "boolean",
                "description": "Create path.bak before modifying. Default: false.",
            },
            "encoding": {
                "type": "string",
                "description": "File encoding. Default: utf-8.",
            },
            "changes": {
                "type": "array",
                "description": "Optional batch edit list: [{old: '...', new: '...'}]. Uses first-match for each.",
            },
        }

    def run(self, arguments: dict) -> str:
        args = arguments or {}
        action = str(args.get("action", "read")).strip().lower()
        action = {"grep": "search", "replace": "edit", "replace_all": "edit"}.get(action, action)

        # An omitted optional `changes` field may arrive as an empty list from
        # the tool layer. Treat only a non-empty list as a batch edit; otherwise
        # dispatch to the requested action normally.
        if action == "edit" and isinstance(args.get("changes"), list) and args["changes"]:
            return self._batch_edit(args)
        if action == "read":
            return self._read(args)
        if action == "write":
            return self._write(args)
        if action == "edit":
            return self._edit(args)
        if action == "search":
            return self._search(args)
        return "Error: action must be read, write, edit, or search."

    def _resolve(self, raw: str, write: bool = False) -> str:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("path is required")
        candidate = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(PROJECT_ROOT, raw))
        try:
            if os.path.commonpath([PROJECT_ROOT, candidate]) != PROJECT_ROOT:
                raise ValueError("path must stay inside the project")
            if write:
                protected = os.path.join(PROJECT_ROOT, "core")
                if os.path.commonpath([protected, candidate]) == protected:
                    raise PermissionError("core is a read-only protected directory")
        except ValueError:
            raise ValueError("path must stay inside the project")
        return candidate

    @staticmethod
    def _encoding(args: dict) -> str:
        return str(args.get("encoding") or "utf-8")

    def _read_text(self, path: str, encoding: str) -> str:
        with open(path, "r", encoding=encoding) as f:
            return f.read()

    def _atomic_write(self, path: str, content: str, encoding: str, backup: bool) -> None:
        if backup and os.path.isfile(path):
            shutil.copy2(path, path + ".bak")
        directory = os.path.dirname(path) or PROJECT_ROOT
        fd, tmp = tempfile.mkstemp(prefix=".code_editor_", dir=directory, text=True)
        try:
            with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _read(self, args: dict) -> str:
        try:
            path = self._resolve(args.get("path", ""))
            if not os.path.isfile(path):
                return "Error: file not found."
            text = self._read_text(path, self._encoding(args))
            lines = text.splitlines()
            # Numbered lines help the model make precise follow-up edits.
            return "\n".join(f"{i}: {line}" for i, line in enumerate(lines, 1)) or "(empty file)"
        except Exception as e:
            return f"Error: cannot read file: {e}"

    def _write(self, args: dict) -> str:
        if "content" not in args:
            return "Error: content is required for write."
        try:
            path = self._resolve(args.get("path", ""), write=True)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._atomic_write(path, str(args.get("content", "")), self._encoding(args), bool(args.get("backup", False)))
            return f"OK: wrote {os.path.relpath(path, PROJECT_ROOT)}"
        except Exception as e:
            return f"Error: cannot write file: {e}"

    def _edit(self, args: dict) -> str:
        if not args.get("old"):
            return "Error: old is required for edit."
        try:
            path = self._resolve(args.get("path", ""), write=True)
            if not os.path.isfile(path):
                return "Error: file not found."
            encoding = self._encoding(args)
            text = self._read_text(path, encoding)
            old, new = str(args["old"]), str(args.get("new", ""))
            count = text.count(old)
            if count == 0:
                return "Error: exact old text not found; file unchanged."
            updated = text.replace(old, new, 1)
            self._atomic_write(path, updated, encoding, bool(args.get("backup", False)))
            note = f" ({count} matches; changed first)" if count > 1 else ""
            return f"OK: edited {os.path.relpath(path, PROJECT_ROOT)}{note}"
        except Exception as e:
            return f"Error: cannot edit file: {e}"

    def _batch_edit(self, args: dict) -> str:
        changes = args.get("changes")
        if not changes:
            return "Error: changes must contain at least one {old, new} item."
        try:
            path = self._resolve(args.get("path", ""), write=True)
            encoding = self._encoding(args)
            text = self._read_text(path, encoding)
            updated = text
            for i, change in enumerate(changes, 1):
                if not isinstance(change, dict) or not change.get("old"):
                    return f"Error: changes[{i}] needs old; file unchanged."
                old, new = str(change["old"]), str(change.get("new", ""))
                if old not in updated:
                    return f"Error: changes[{i}] old text not found; file unchanged."
                updated = updated.replace(old, new, 1)
            self._atomic_write(path, updated, encoding, bool(args.get("backup", False)))
            return f"OK: applied {len(changes)} edits to {os.path.relpath(path, PROJECT_ROOT)}"
        except Exception as e:
            return f"Error: batch edit failed; file unchanged when possible: {e}"

    def _search(self, args: dict) -> str:
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            return "Error: pattern is required for search."
        wanted = str(args.get("glob") or "*")
        try:
            regex = re.compile(pattern, re.IGNORECASE if not args.get("case_sensitive", False) else 0)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE if not args.get("case_sensitive", False) else 0)
        results = []
        for base, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for name in files:
                if not __import__("fnmatch").fnmatch(name, wanted):
                    continue
                path = os.path.join(base, name)
                try:
                    with open(path, "r", encoding=self._encoding(args)) as f:
                        for line_no, line in enumerate(f, 1):
                            if regex.search(line):
                                rel = os.path.relpath(path, PROJECT_ROOT)
                                results.append(f"{rel}:{line_no}: {line.rstrip()}")
                                if len(results) >= int(args.get("max_results", 50)):
                                    return "\n".join(results) + "\n(truncated)"
                except (OSError, UnicodeError):
                    continue
        return "\n".join(results) if results else "No matches."
