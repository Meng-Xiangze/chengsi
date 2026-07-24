import os
import re
import shutil
import tempfile
from typing import Any, Dict

from tools._hashline import (
    format_lines,
    join_text,
    replacement_lines,
    revision,
    split_text,
    validate_anchor,
)
from tools.base import BaseTool

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules"}
_VALID_OPS = {"replace", "delete", "insert_before", "insert_after", "prepend", "append"}
_OP_ALIASES = {"add_before": "insert_before", "add_after": "insert_after", "remove": "delete"}


class CodeEditor(BaseTool):
    """Safe project editor using content-verified line anchors."""

    @property
    def tool_name(self) -> str:
        return "code_editor"

    @property
    def description(self) -> str:
        return (
            "Read and safely modify project files using hash-anchored line operations. "
            "Supports replace, delete, insert_before, insert_after, prepend, append. "
            "Aliases: remove=delete, add_before=insert_before, add_after=insert_after. "
            "Multiple inserts at same anchor execute in order; all edits are atomic."
        )

    def is_mutating(self, arguments: Dict[str, Any]) -> bool:
        action = str((arguments or {}).get("action", "read")).strip().lower()
        return action in {"write", "edit", "patch"}

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "description": "read, write, edit, or search. Default: read. Read before edit.",
            },
            "path": {"type": "string", "description": "Relative project file path."},
            "content": {"type": "string", "description": "Complete content for write."},
            "revision": {
                "type": "string",
                "description": "Optional file revision copied from read; rejects any stale snapshot.",
            },
            "operations": {
                "type": "array",
                "description": (
                    "Hash-anchored edits. Copy start/end anchors from read or search. "
                    "end is only for replace/delete ranges. prepend/append do not use start. "
                    "Operations: replace, delete, insert_before, insert_after, prepend, append."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string", "enum": sorted(_VALID_OPS)},
                        "start": {"type": "string", "description": "Starting LINE:HASH anchor."},
                        "end": {"type": "string", "description": "Optional ending LINE:HASH anchor."},
                        "content": {"type": "string", "description": "Replacement or inserted text."},
                    },
                    "required": ["op"],
                },
            },
            "offset": {"type": "integer", "description": "First line for read; default 1."},
            "limit": {"type": "integer", "description": "Maximum read lines; default 400, maximum 2000."},
            "backup": {"type": "boolean", "description": "Create path.bak before modifying. Default false."},
            "encoding": {"type": "string", "description": "File encoding. Default utf-8."},
            "pattern": {"type": "string", "description": "Regex or text for search."},
            "glob": {"type": "string", "description": "Filename glob for search; default *."},
            "max_results": {"type": "integer", "description": "Maximum search matches; default 50."},
        }

    def run(self, arguments: dict) -> str:
        args = arguments or {}
        action = str(args.get("action", "read")).strip().lower()
        action = {"grep": "search", "patch": "edit"}.get(action, action)
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
                protected_paths = [os.path.join(PROJECT_ROOT, "core"), os.path.join(PROJECT_ROOT, "main.py")]
                for protected in protected_paths:
                    if candidate == protected or (
                        os.path.isdir(protected) and os.path.commonpath([protected, candidate]) == protected
                    ):
                        raise PermissionError("the running core directory and main.py are read-only")
        except ValueError:
            raise ValueError("path must stay inside the project")
        return candidate

    @staticmethod
    def _encoding(args: dict) -> str:
        return str(args.get("encoding") or "utf-8")

    @staticmethod
    def _read_text(path: str, encoding: str) -> str:
        with open(path, "r", encoding=encoding, newline="") as handle:
            return handle.read()

    def _atomic_write(self, path: str, content: str, encoding: str, backup: bool) -> None:
        if backup and os.path.isfile(path):
            shutil.copy2(path, path + ".bak")
        directory = os.path.dirname(path) or PROJECT_ROOT
        fd, temporary = tempfile.mkstemp(prefix=".code_editor_", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _bounded_integer(value: object, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(int(value), maximum))
        except (TypeError, ValueError):
            return default

    def _read(self, args: dict) -> str:
        try:
            path = self._resolve(args.get("path", ""))
            if not os.path.isfile(path):
                return "Error: file not found."
            text = self._read_text(path, self._encoding(args))
            offset = self._bounded_integer(args.get("offset", 1), 1, 1, 10_000_000)
            limit = self._bounded_integer(args.get("limit", 400), 400, 1, 2000)
            return format_lines(text, os.path.relpath(path, PROJECT_ROOT), offset, limit)
        except Exception as error:
            return f"Error: cannot read file: {error}"

    def _write(self, args: dict) -> str:
        if "content" not in args:
            return "Error: content is required for write."
        try:
            path = self._resolve(args.get("path", ""), write=True)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            current = self._read_text(path, self._encoding(args)) if os.path.isfile(path) else ""
            expected = str(args.get("revision") or "").strip()
            if expected and revision(current) != expected:
                return f"Error: stale revision; current revision is {revision(current)}. Re-read the file."
            content = str(args.get("content", ""))
            self._atomic_write(path, content, self._encoding(args), bool(args.get("backup", False)))
            return f"OK: wrote {os.path.relpath(path, PROJECT_ROOT)} rev={revision(content)}"
        except Exception as error:
            return f"Error: cannot write file: {error}"

    def _edit(self, args: dict) -> str:
        operations = args.get("operations")
        if not isinstance(operations, list) or not operations:
            return "Error: operations must contain at least one hash-anchored edit. Read the file first."
        try:
            path = self._resolve(args.get("path", ""), write=True)
            if not os.path.isfile(path):
                return "Error: file not found."
            encoding = self._encoding(args)
            text = self._read_text(path, encoding)
            expected = str(args.get("revision") or "").strip()
            current_revision = revision(text)
            if expected and current_revision != expected:
                return f"Error: stale revision {expected}; current revision is {current_revision}. Re-read the file."
            layout = split_text(text)
            validated = []
            occupied_ranges = []
            for index, operation in enumerate(operations, 1):
                if not isinstance(operation, dict):
                    return f"Error: operations[{index}] must be an object; file unchanged."
                op = str(operation.get("op", "")).strip().lower()
                op = _OP_ALIASES.get(op, op)
                if op not in _VALID_OPS:
                    return f"Error: operations[{index}] has invalid op {op!r}; file unchanged."
                start = None
                end = None
                if op in {"prepend", "append"}:
                    if operation.get("start"):
                        return f"Error: operations[{index}] {op!r} does not use start anchor; file unchanged."
                    start = -1 if op == "prepend" else len(layout.lines)
                    end = start
                else:
                    start = validate_anchor(layout.lines, operation.get("start"))
                    end = start
                if operation.get("end"):
                    if op not in {"replace", "delete"}:
                        return f"Error: operations[{index}] end is only valid for replace/delete; file unchanged."
                    end = validate_anchor(layout.lines, operation.get("end"))
                if end < start:
                    return f"Error: operations[{index}] end precedes start; file unchanged."
                insert_point = None
                if op == "insert_before":
                    insert_point = (start, "before")
                elif op == "insert_after":
                    insert_point = (start, "after")
                elif op in {"prepend", "append"}:
                    insert_point = None
                else:
                    target_start = start
                    target_end = end
                    for previous_start, previous_end in occupied_ranges:
                        if not (target_end < previous_start or target_start > previous_end):
                            return f"Error: operations[{index}] overlaps another edit; file unchanged."
                    occupied_ranges.append((target_start, target_end))
                content = [] if op == "delete" else replacement_lines(operation.get("content", ""))
                if op in {"replace", "insert_before", "insert_after", "prepend", "append"} and "content" not in operation:
                    return f"Error: operations[{index}] requires content; file unchanged."
                validated.append((start, end, op, content, insert_point))

            updated_lines = list(layout.lines)
            prepend_content = []
            append_content = []
            operations_by_position = {}

            for seq_num, (start, end, op, content, insert_point) in enumerate(validated):
                if op == "prepend":
                    prepend_content.extend(content)
                elif op == "append":
                    append_content.extend(content)
                elif op == "insert_before":
                    key = (start, "insert_before")
                    if key not in operations_by_position:
                        operations_by_position[key] = []
                    operations_by_position[key].append((seq_num, content))
                elif op == "insert_after":
                    key = (start, "insert_after")
                    if key not in operations_by_position:
                        operations_by_position[key] = []
                    operations_by_position[key].append((seq_num, content))
                elif op in {"replace", "delete"}:
                    key = (start, "replace_delete")
                    operations_by_position[key] = [(seq_num, (end, content))]

            # Build final operation list with merged inserts
            operations_to_apply = []
            for (idx, op_type), items in operations_by_position.items():
                if op_type in {"insert_before", "insert_after"}:
                    # Merge multiple inserts at same position, preserving order
                    merged_content = []
                    for seq, content in sorted(items, key=lambda x: x[0]):
                        merged_content.extend(content)
                    operations_to_apply.append((idx, op_type, merged_content, min(x[0] for x in items)))
                else:
                    # replace_delete: only one per position
                    seq, data = items[0]
                    operations_to_apply.append((idx, op_type, data, seq))

            # Sort by: 1) index descending, 2) op type priority, 3) original sequence ascending
            def sort_key(item):
                idx, op_type, _, seq = item
                priority = {"replace_delete": 0, "insert_before": 1, "insert_after": 2}
                return (-idx, priority.get(op_type, 0), seq)

            for idx, op_type, data, _ in sorted(operations_to_apply, key=sort_key):
                if op_type == "replace_delete":
                    end, content = data
                    updated_lines[idx:end + 1] = content
                elif op_type == "insert_before":
                    updated_lines[idx:idx] = data
                elif op_type == "insert_after":
                    updated_lines[idx + 1:idx + 1] = data

            if prepend_content:
                updated_lines[0:0] = prepend_content
            if append_content:
                updated_lines.extend(append_content)
            updated = join_text(updated_lines, layout.newline, layout.final_newline)
            self._atomic_write(path, updated, encoding, bool(args.get("backup", False)))
            return (
                f"OK: applied {len(validated)} hash edit(s) to {os.path.relpath(path, PROJECT_ROOT)} "
                f"rev={revision(updated)} lines={len(updated_lines)}"
            )
        except Exception as error:
            return f"Error: hash edit failed; file unchanged: {error}"

    def _search(self, args: dict) -> str:
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            return "Error: pattern is required for search."
        wanted = str(args.get("glob") or "*")
        try:
            regex = re.compile(pattern, re.IGNORECASE if not args.get("case_sensitive", False) else 0)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE if not args.get("case_sensitive", False) else 0)
        max_results = self._bounded_integer(args.get("max_results", 50), 50, 1, 200)
        results = []
        for base, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [directory for directory in dirs if directory not in _SKIP_DIRS]
            for name in files:
                if not __import__("fnmatch").fnmatch(name, wanted):
                    continue
                path = os.path.join(base, name)
                try:
                    text = self._read_text(path, self._encoding(args))
                    layout = split_text(text)
                    for line_number, line in enumerate(layout.lines, 1):
                        if regex.search(line):
                            from tools._hashline import anchor
                            rel = os.path.relpath(path, PROJECT_ROOT)
                            results.append(f"{rel}:{anchor(line_number, line)}|{line}")
                            if len(results) >= max_results:
                                return "\n".join(results) + "\n[truncated]"
                except (OSError, UnicodeError):
                    continue
        return "\n".join(results) if results else "No matches."
