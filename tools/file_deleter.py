# -*- coding: utf-8 -*-
from tools.base import BaseTool
import os
import shutil
from pathlib import Path
import json


class FileDeleter(BaseTool):
    """
    Safe file/directory deletion with explicit path specification.
    Prevents accidental recursive deletion of parent directories.
    """

    @property
    def tool_name(self) -> str:
        return "file_deleter"

    @property
    def description(self) -> str:
        return "Delete a specific file or directory (can be non-empty). Requires explicit path, no wildcards."

    def is_mutating(self, arguments: dict) -> bool:
        return bool((arguments or {}).get("confirm", False))

    @property
    def parameters(self) -> dict:
        return {
            "path": {
                "type": "string",
                "description": "Exact path to delete (file or directory). No wildcards, no '..' allowed."
            },
            "confirm": {
                "type": "boolean",
                "description": "Must be true to actually delete. Safety confirmation."
            }
        }

    def run(self, arguments: dict) -> str:
        path_str = arguments.get("path", "").strip()
        confirm = arguments.get("confirm", False)

        if not path_str:
            return json.dumps({"error": "path is required"}, ensure_ascii=False)

        if not confirm:
            return json.dumps({
                "error": "confirm must be true to delete",
                "hint": "Set confirm=true to proceed"
            }, ensure_ascii=False, indent=2)

        # Security checks
        if ".." in path_str:
            return json.dumps({
                "error": "'..' not allowed in path (prevents accidental parent deletion)"
            }, ensure_ascii=False)

        if "*" in path_str or "?" in path_str:
            return json.dumps({
                "error": "Wildcards not allowed. Specify exact path."
            }, ensure_ascii=False)

        # Resolve path
        try:
            target = Path(path_str).resolve()
        except Exception as e:
            return json.dumps({"error": f"Invalid path: {e}"}, ensure_ascii=False)

        # Must be relative to project root (prevent deleting system files)
        project_root = Path.cwd().resolve()
        try:
            target.relative_to(project_root)
        except ValueError:
            return json.dumps({
                "error": f"Path must be within project directory: {project_root}"
            }, ensure_ascii=False, indent=2)

        # Check if exists
        if not target.exists():
            return json.dumps({
                "error": f"Path does not exist: {path_str}"
            }, ensure_ascii=False)

        # Protected paths (prevent deleting core system)
        protected = ["core", "main.py", ".git", ".venv", "venv"]
        if target.name in protected or any(p in target.parts for p in ["core"]):
            return json.dumps({
                "error": f"Protected path cannot be deleted: {target.name}"
            }, ensure_ascii=False)

        # Perform deletion
        try:
            if target.is_file():
                target.unlink()
                return json.dumps({
                    "success": True,
                    "action": "deleted file",
                    "path": str(target)
                }, ensure_ascii=False, indent=2)
            elif target.is_dir():
                # Count items for reporting
                items = list(target.rglob("*"))
                item_count = len(items)

                shutil.rmtree(target)
                return json.dumps({
                    "success": True,
                    "action": "deleted directory",
                    "path": str(target),
                    "items_removed": item_count
                }, ensure_ascii=False, indent=2)
            else:
                return json.dumps({
                    "error": f"Unknown path type: {target}"
                }, ensure_ascii=False)
        except PermissionError as e:
            return json.dumps({
                "error": f"Permission denied: {e}"
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({
                "error": f"Deletion failed: {e}"
            }, ensure_ascii=False)