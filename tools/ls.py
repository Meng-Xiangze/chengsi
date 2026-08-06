# -*- coding: utf-8 -*-
"""ls tool — list directory contents with sizes and types."""

import os
from pathlib import Path
from typing import Any

from tools.base import BaseTool
from core.process_utils import normalize_path


class Ls(BaseTool):
    """List directory contents."""

    @property
    def tool_name(self) -> str:
        return "ls"

    @property
    def description(self) -> str:
        return (
            "List files and directories. Shows name, size, and type. "
            "Use to explore project structure before reading or editing files."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "description": "Directory path to list. Default: current working directory.",
            },
        }

    def run(self, arguments: dict[str, Any]) -> str:
        args = arguments or {}
        raw = normalize_path(str(args.get("path", "")))
        target = Path(raw).resolve() if raw else Path.cwd()

        if not target.exists():
            return f"Error: path not found: {target}"
        if target.is_file():
            return self._format_one(target)

        items: list[str] = []
        try:
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return f"Error: permission denied: {target}"

        dirs: list[str] = []
        files: list[str] = []

        for entry in entries:
            if entry.name.startswith("."):
                continue
            line = self._format_one(entry)
            if entry.is_dir():
                dirs.append(line)
            else:
                files.append(line)

        result = f"📂 {target}\n"
        if dirs:
            result += "\n".join(dirs) + "\n"
        if files:
            if dirs:
                result += "\n"
            result += "\n".join(files)
        if not entries:
            result += "(empty)"

        return result

    @staticmethod
    def _format_one(p: Path) -> str:
        name = p.name
        if p.is_dir():
            # Count children
            try:
                count = sum(1 for _ in p.iterdir())
                return f"  📁 {name}/  ({count} items)"
            except PermissionError:
                return f"  📁 {name}/  (🔒)"
        else:
            size = p.stat().st_size
            ext = p.suffix.lower()
            icon = Ls._icon(ext)
            return f"  {icon} {name}  ({Ls._size_fmt(size)})"

    @staticmethod
    def _icon(ext: str) -> str:
        return {
            ".py": "🐍", ".js": "📜", ".ts": "📘", ".json": "📋",
            ".md": "📝", ".txt": "📄", ".html": "🌐", ".css": "🎨",
            ".png": "🖼️", ".jpg": "🖼️", ".gif": "🖼️", ".svg": "🖼️",
            ".pdf": "📕", ".docx": "📘", ".zip": "📦",
            ".yaml": "⚙️", ".yml": "⚙️", ".toml": "⚙️",
            ".gitignore": "🙈", ".env": "🔑",
        }.get(ext, "📄")

    @staticmethod
    def _size_fmt(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:,.0f} {unit}"
            size /= 1024
        return f"{size:,.1f} TB"
