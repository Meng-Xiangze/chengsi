import hashlib
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from tools.base import BaseTool


PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "node_modules"}


class SystemCleanerTool(BaseTool):
    @property
    def tool_name(self) -> str:
        return "system_cleaner"

    @property
    def description(self) -> str:
        return (
            "Clean system junk: temporary files, caches, Python __pycache__, recycle bin. "
            "Supports filters for age, size, and extensions. Preview mode by default (dry_run=true). "
            "This tool is for bulk cleanup of system-generated garbage, not for deleting specific project files."
        )

    def is_mutating(self, arguments: Dict[str, Any]) -> bool:
        return not bool((arguments or {}).get("dry_run", True))

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "target_types": {
                "type": "array",
                "description": "Cleanup categories: temp (system temp), cache (browser/app cache), python_cache (__pycache__), recycle_bin (Windows recycle bin).",
                "items": {"type": "string", "enum": ["temp", "cache", "python_cache", "recycle_bin"]},
            },
            "target_type": {
                "type": "string",
                "description": "Single category (backward compatibility). Use target_types for multiple.",
                "enum": ["temp", "cache", "python_cache", "recycle_bin"],
            },
            "path": {
                "type": "string",
                "description": "Optional override: scan a specific directory instead of default system locations.",
            },
            "extensions": {
                "type": "array",
                "description": "Optional filename extensions, such as ['.tmp', '.log']; only matching files are selected.",
                "items": {"type": "string"},
            },
            "older_than_days": {
                "type": "number",
                "description": "Optional minimum age in days. Only items not modified within this period are selected.",
                "minimum": 0,
            },
            "min_size_mb": {
                "type": "number",
                "description": "Optional minimum file size in MB. Directories are included when they contain matching files.",
                "minimum": 0,
            },
            "dry_run": {
                "type": "boolean",
                "description": "Preview mode (true, default) or actually delete (false).",
                "default": True,
            },
            "force": {
                "type": "boolean",
                "description": "Continue after locked or inaccessible items; default false.",
                "default": False,
            },
        }

    def run(self, arguments: Dict[str, Any]) -> str:
        args = arguments or {}
        target_types = args.get("target_types")
        if not isinstance(target_types, list):
            target_types = [args.get("target_type", "")]
        target_types = [str(value).strip().lower() for value in target_types if str(value).strip()]
        valid = {"temp", "cache", "python_cache", "recycle_bin"}
        invalid = [value for value in target_types if value not in valid]
        if invalid:
            return "Error: unsupported target type(s): {}. Use temp, cache, python_cache, or recycle_bin.".format(", ".join(invalid))
        if not target_types:
            return "Error: specify target_type or target_types."

        raw_path = str(args.get("path") or "").strip()
        if "custom" in target_types:
            return "Error: 'custom' category removed. Use file_deleter tool for specific file/directory deletions."
        raw_path = self._expand_path(raw_path)
        root = Path(raw_path).expanduser().resolve() if raw_path else PROJECT_ROOT
        if raw_path and not root.is_dir():
            return f"Error: scan path does not exist or is not a directory: {root}"
        protected = tuple((PROJECT_ROOT / name).resolve() for name in ("core", "knowledge"))
        if any(root == path for path in protected):
            return "Error: core and knowledge are permanently protected and cannot be cleanup targets."

        extensions = self._extensions(args.get("extensions"))
        older_than = self._number(args.get("older_than_days"))
        min_size = self._number(args.get("min_size_mb"))
        cutoff = time.time() - older_than * 86400 if older_than is not None else None
        recycle_result = ""
        if "recycle_bin" in target_types:
            if not self._is_windows():
                return "Error: recycle_bin cleanup is currently supported on Windows only."
            try:
                item_count, total_bytes = self._query_recycle_bin()
            except OSError as exc:
                return f"Error: unable to inspect Windows Recycle Bin: {exc}"
            if item_count == 0:
                recycle_result = "Windows Recycle Bin is empty."
            elif self._is_dry_run(args):
                recycle_result = "DRY RUN: Windows Recycle Bin contains {} item(s), {:.2f} MB. Nothing was deleted.".format(item_count, total_bytes / 1024 / 1024)
            else:
                recycle_result = self._empty_recycle_bin(item_count, total_bytes)
            target_types = [value for value in target_types if value != "recycle_bin"]
            if not target_types:
                return recycle_result

        candidates: List[Path] = []
        for target_type in target_types:
            candidates.extend(self._find_target(target_type, root))
        selected = [
            item for item in self._unique(candidates)
            if not self._is_protected(item) and self._matches(item, extensions, cutoff, min_size)
        ]

        if not self._is_dry_run(args):
            deleted = errors = skipped_non_empty = 0
            for item in selected:
                try:
                    if item.is_dir():
                        # Safety: recursive deletion is allowed only inside AppData\\Local\\Temp.
                        # The Temp root itself is never deleted; all other non-empty directories are skipped.
                        if self._is_temp_subdirectory(item):
                            shutil.rmtree(item)
                        elif any(item.iterdir()):
                            skipped_non_empty += 1
                            continue
                        else:
                            item.rmdir()
                    else:
                        item.unlink()
                    deleted += 1
                except OSError:
                    errors += 1
                    if not bool(args.get("force", False)):
                        continue
            directory_result = (
                "Deleted {} items for [{}]; errors: {}; skipped {} non-empty directories. "
                "Some items may not be removable because they are currently in use or locked, "
                "including active chat/session files. Non-empty directories are never deleted outside "
                "AppData\\Local\\Temp."
            ).format(deleted, ", ".join(target_types), errors, skipped_non_empty)
            return f"{recycle_result}\n{directory_result}" if recycle_result else directory_result

        total_bytes = sum(self._size(item) for item in selected)
        directory_result = self._preview(target_types, selected, total_bytes)
        return f"{recycle_result}\n{directory_result}" if recycle_result else directory_result

    @staticmethod
    def _fingerprint(target_types: List[str], selected: List[Path]) -> str:
        payload = "\n".join(sorted(target_types) + sorted(str(item.resolve()) for item in selected))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _preview(self, target_types: List[str], selected: List[Path], total_bytes: int) -> str:
        preview = "\n".join(f"- {item}" for item in selected[:20])
        if len(selected) > 20:
            preview += f"\n- ... and {len(selected) - 20} more"
        return (
            "DRY RUN: selected {} items ({:.2f} MB) for [{}]. Nothing was deleted.\n{}\n"
        ).format(len(selected), total_bytes / 1024 / 1024, ", ".join(target_types), preview)

    @staticmethod
    def _expand_path(raw_path: str) -> str:
        if not raw_path:
            return raw_path
        # Expand native Windows %NAME% syntax as well as POSIX-style variables.
        expanded = os.path.expandvars(raw_path)
        # os.path.expandvars does not expand Windows syntax when tests run on POSIX.
        expanded = re.sub(
            r"%([^%]+)%",
            lambda match: os.environ.get(match.group(1), match.group(0)),
            expanded,
        )
        return os.path.expanduser(expanded)

    @staticmethod
    def _is_dry_run(args: Dict[str, Any]) -> bool:
        value = args.get("dry_run", False)
        if isinstance(value, str):
            return value.lower() not in {"false", "0", "no"}
        return bool(value)

    @staticmethod
    def _is_windows() -> bool:
        return os.name == "nt"

    @staticmethod
    def _query_recycle_bin() -> tuple[int, int]:
        import ctypes
        from ctypes import wintypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong),
            ]

        shell32 = ctypes.windll.shell32
        shell32.SHQueryRecycleBinW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SHQUERYRBINFO)]
        shell32.SHQueryRecycleBinW.restype = wintypes.HRESULT
        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
        result = shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if result != 0:
            raise OSError(f"SHQueryRecycleBinW failed (HRESULT 0x{result & 0xffffffff:08X})")
        return max(0, int(info.i64NumItems)), max(0, int(info.i64Size))

    @staticmethod
    def _empty_recycle_bin(item_count: int, total_bytes: int) -> str:
        try:
            import ctypes
            from ctypes import wintypes

            shell32 = ctypes.windll.shell32
            shell32.SHEmptyRecycleBinW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.DWORD]
            shell32.SHEmptyRecycleBinW.restype = wintypes.HRESULT
            flags = 0x00000001 | 0x00000002 | 0x00000004
            result = shell32.SHEmptyRecycleBinW(None, None, flags)
            if result != 0:
                return f"Error: Windows could not empty the Recycle Bin (HRESULT 0x{result & 0xffffffff:08X})."
            return f"Windows Recycle Bin emptied successfully: removed {item_count} item(s), {total_bytes / 1024 / 1024:.2f} MB."
        except (AttributeError, OSError) as exc:
            return f"Error: unable to empty Windows Recycle Bin: {exc}"

    def _find_target(self, target_type: str, root: Path) -> Iterable[Path]:
        if target_type == "temp":
            temp_root = Path(tempfile.gettempdir()).resolve()
            try:
                return list(temp_root.iterdir())
            except OSError:
                return []
        if target_type == "cache":
            candidates = [Path.home() / ".cache", Path(os.environ.get("LOCALAPPDATA", "")) / "Cache"]
            return [path for path in candidates if str(path) and path.is_dir()]
        if target_type == "logs":
            return []  # logs cleanup disabled
        if target_type == "recycle_bin":
            return []
        scan_root = root
        found = []
        for current, dir_names, file_names in os.walk(scan_root, topdown=True, followlinks=False):
            dir_names[:] = [name for name in dir_names if name not in _SKIP_DIRS]
            current_path = Path(current)
            if current_path.name == "__pycache__":
                found.append(current_path)
                dir_names[:] = []
            elif target_type == "python_cache":
                found.extend(current_path / name for name in file_names if Path(name).suffix.lower() in {".pyc", ".pyo"})
        return found

    @staticmethod
    def _is_temp_root(item: Path) -> bool:
        try:
            return item.resolve() == Path(tempfile.gettempdir()).resolve()
        except (OSError, RuntimeError, ValueError):
            return False


    @staticmethod
    def _is_temp_subdirectory(item: Path) -> bool:
        """Return true only for a directory below the system AppData Local Temp root."""
        try:
            temp_root = Path(tempfile.gettempdir()).resolve()
            candidate = item.resolve()
            return candidate != temp_root and temp_root in candidate.parents
        except (OSError, RuntimeError, ValueError):
            return False


    @staticmethod
    def _extensions(value: Any) -> set[str] | None:
        if not isinstance(value, list) or not value:
            return None
        return {str(item).lower() if str(item).startswith(".") else "." + str(item).lower() for item in value}

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return None if value is None or value == "" else max(0.0, float(value))
        except (TypeError, ValueError):
            return None

    def _matches(self, item: Path, extensions: set[str] | None, cutoff: float | None, min_size: float | None) -> bool:
        try:
            stat = item.stat()
            if cutoff is not None and stat.st_mtime > cutoff:
                return False
            if item.is_file():
                if extensions and item.suffix.lower() not in extensions:
                    return False
                return min_size is None or stat.st_size >= min_size * 1024 * 1024
            return any(self._matches(child, extensions, cutoff, min_size) for child in item.iterdir())
        except OSError:
            return False

    @staticmethod
    def _is_protected(item: Path) -> bool:
        resolved = item.resolve()
        protected = tuple((PROJECT_ROOT / name).resolve() for name in ("core", "knowledge"))
        return any(resolved == root or root in resolved.parents for root in protected)

    @staticmethod
    def _unique(items: Iterable[Path]) -> List[Path]:
        result = []
        seen = set()
        for item in items:
            key = str(item)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    @staticmethod
    def _size(item: Path) -> int:
        try:
            if item.is_file():
                return item.stat().st_size
            return sum(child.stat().st_size for child in item.rglob("*") if child.is_file())
        except OSError:
            return 0
