# -*- coding: utf-8 -*-
"""Preview and clean system temp files, caches, and recycle bin."""
import os, shutil, tempfile, time
from pathlib import Path
from typing import Any

from tools.base import BaseTool

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class SystemCleanerTool(BaseTool):
    @property
    def tool_name(self) -> str:
        return "system_cleaner"

    @property
    def description(self) -> str:
        return (
            "Clean system junk: temp files, Python __pycache__, Windows recycle bin. "
            "Default is dry_run=true (preview only). Set dry_run=false to actually delete."
        )

    def is_mutating(self, arguments: dict[str, Any]) -> bool:
        return not bool((arguments or {}).get("dry_run", True))

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "target_type": {
                "type": "string",
                "description": "One of: temp, python_cache, recycle_bin, or all (default).",
                "enum": ["temp", "python_cache", "recycle_bin", "all"],
            },
            "dry_run": {
                "type": "boolean",
                "description": "Preview only (true, default) or actually delete (false).",
            },
        }

    # ------------------------------------------------------------------ #
    #  entry
    # ------------------------------------------------------------------ #

    def run(self, arguments: dict[str, Any]) -> str:
        args = arguments or {}
        target = str(args.get("target_type", "all")).strip().lower()
        dry_run = args.get("dry_run", True)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() not in {"false", "0", "no"}

        valid = {"temp", "python_cache", "recycle_bin", "all"}
        if target not in valid:
            return f"Error: target_type must be one of: {', '.join(sorted(valid))}."

        results: list[str] = []

        if target in ("temp", "all"):
            results.append(self._clean_temp(dry_run))
        if target in ("python_cache", "all"):
            results.append(self._clean_pycache(dry_run))
        if target in ("recycle_bin", "all"):
            results.append(self._clean_recycle(dry_run))

        return "\n\n".join(results)

    # ------------------------------------------------------------------ #
    #  cleaners
    # ------------------------------------------------------------------ #

    def _clean_temp(self, dry_run: bool) -> str:
        root = Path(tempfile.gettempdir())
        items = []
        try:
            for child in root.iterdir():
                try:
                    items.append((child, child.stat().st_size if child.is_file() else 0))
                except OSError:
                    pass
        except OSError:
            return "Error: cannot access system temp directory."

        total_size = sum(s for _, s in items)
        if dry_run:
            return (
                f"[temp] DRY RUN: {len(items)} items ({total_size / 1024 / 1024:.1f} MB) "
                f"in {root}. Nothing deleted."
            )

        deleted = errors = 0
        for child, _ in items:
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                deleted += 1
            except OSError:
                errors += 1
        return f"[temp] Deleted {deleted} items ({errors} locked/skipped)."

    def _clean_pycache(self, dry_run: bool) -> str:
        dirs: list[Path] = []
        for root, dirnames, _ in os.walk(PROJECT_ROOT):
            dirnames[:] = [d for d in dirnames if d not in {".git", ".venv", "venv", "node_modules"}]
            if "__pycache__" in dirnames:
                dirs.append(Path(root) / "__pycache__")
                dirnames.remove("__pycache__")

        if dry_run:
            return (
                f"[python_cache] DRY RUN: {len(dirs)} __pycache__ dirs. Nothing deleted."
            )

        deleted = 0
        for d in dirs:
            try:
                shutil.rmtree(d)
                deleted += 1
            except OSError:
                pass
        return f"[python_cache] Deleted {deleted}/{len(dirs)} __pycache__ dirs."

    @staticmethod
    def _clean_recycle(dry_run: bool) -> str:
        if os.name != "nt":
            return "[recycle_bin] Supported on Windows only."

        import ctypes
        from ctypes import wintypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong),
            ]

        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
        shell32 = ctypes.windll.shell32
        hr = shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if hr != 0:
            return f"[recycle_bin] Error: SHQueryRecycleBinW failed (0x{hr & 0xffffffff:08X})."

        count = max(0, int(info.i64NumItems))
        size_mb = max(0, info.i64Size) / 1024 / 1024

        if count == 0:
            return "[recycle_bin] Empty."

        if dry_run:
            return f"[recycle_bin] DRY RUN: {count} items ({size_mb:.1f} MB). Nothing deleted."

        flags = 0x00000001 | 0x00000002 | 0x00000004  # no confirm, no sound, no progress
        hr = shell32.SHEmptyRecycleBinW(None, None, flags)
        if hr != 0:
            return f"[recycle_bin] Error: SHEmptyRecycleBinW failed (0x{hr & 0xffffffff:08X})."
        return f"[recycle_bin] Emptied: {count} items ({size_mb:.1f} MB)."
