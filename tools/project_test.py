# -*- coding: utf-8 -*-
import os
import sys
import subprocess
from typing import Any, Dict, List

from tools.base import BaseTool

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules", "assets", "sessions"}


class ProjectTest(BaseTool):
    """Run quick sanity checks: syntax, imports, config, optional test runner."""

    @property
    def tool_name(self) -> str:
        return "project_test"

    @property
    def description(self) -> str:
        return (
            "Run Python syntax checks (py_compile), import checks, and config file "
            "validation on the project. Optionally discover and run a test suite."
        )

    def is_verification(self, arguments: Dict[str, Any]) -> bool:
        return True

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "scope": {
                "type": "string",
                "description": "One of: syntax, imports, config, tests, all (default: all).",
            },
        }

    def run(self, arguments: Dict[str, Any]) -> str:
        scope = str(arguments.get("scope", "all")).strip().lower()
        valid_scopes = {"syntax", "imports", "config", "tests", "all"}
        if scope not in valid_scopes:
            return f"Error: scope must be one of: {', '.join(sorted(valid_scopes))}."
        results: List[str] = []

        if scope in ("syntax", "all"):
            results.append(self._check_syntax())
        if scope in ("imports", "all"):
            results.append(self._check_imports())
        if scope in ("config", "all"):
            results.append(self._check_config())
        if scope in ("tests", "all"):
            results.append(self._run_tests())

        return "\n\n".join(results) if results else "No checks selected."

    # ------------------------------------------------------------------
    def _check_syntax(self) -> str:
        """Compile every Python source file without executing it.

        Using compile() on the source avoids importing modules or creating .pyc
        files, while formatting SyntaxError with traceback matches Python's
        normal command-line error style.
        """
        lines = ["[syntax] Checking all .py files (compile only; no execution)..."]
        errors = 0
        ok = 0
        for root, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, PROJECT_ROOT)
                try:
                    with open(fpath, "rb") as source_file:
                        source = source_file.read()
                    compile(source, fpath, "exec")
                    ok += 1
                except SyntaxError as e:
                    errors += 1
                    lines.append(f"  FAIL {rel}:\n{self._format_syntax_traceback(e)}")
                except (OSError, UnicodeError) as e:
                    errors += 1
                    lines.append(f"  FAIL {rel}: could not read source: {e}")
        lines.append(f"  {ok} passed, {errors} failed.")
        return "\n".join(lines)

    @staticmethod
    def _format_syntax_traceback(error: SyntaxError) -> str:
        """Return the standard-looking traceback for a compile-time error."""
        import traceback

        return "".join(traceback.format_exception_only(type(error), error)).rstrip()

    def _check_imports(self) -> str:
        lines = ["[imports] Checking import of main modules..."]
        errors = 0
        modules = []
        for root, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fname in files:
                if fname.endswith(".py") and fname != "__init__.py":
                    rel = os.path.relpath(os.path.join(root, fname), PROJECT_ROOT)
                    mod = rel.replace(os.sep, ".").removesuffix(".py")
                    modules.append((mod, os.path.join(root, fname)))

        sys.path.insert(0, PROJECT_ROOT)
        for mod, fpath in modules:
            try:
                subprocess.run(
                    [sys.executable, "-c", f"import {mod}"],
                    capture_output=True, text=True, timeout=10,
                    cwd=PROJECT_ROOT,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                errors += 1
                err = e.stderr.strip().split("\n")[-1] if e.stderr else str(e)
                lines.append(f"  FAIL {mod}: {err}")
            except subprocess.TimeoutExpired as e:
                errors += 1
                lines.append(f"  FAIL {mod}: timeout")

        sys.path.pop(0)
        total = len(modules)
        lines.append(f"  {total - errors}/{total} imports passed, {errors} failed.")
        return "\n".join(lines)

    def _run_tests(self) -> str:
        """Run the repository's deterministic unittest suite in a subprocess."""
        tests_dir = os.path.join(PROJECT_ROOT, "tests")
        if not os.path.isdir(tests_dir):
            return "[tests] SKIP tests/ (not found)."
        lines = ["[tests] Running unittest discovery..."]
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "[tests] FAIL: test runner timed out after 120 seconds."
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        if completed.returncode:
            lines.append(f"  FAIL: unittest exited with code {completed.returncode}.")
        else:
            lines.append("  OK: unittest exited with code 0.")
        if output:
            lines.append(output)
        return "\n".join(lines)

    def _check_config(self) -> str:
        lines = ["[config] Checking config files..."]
        config_path = os.path.join(PROJECT_ROOT, "config.json")
        if os.path.isfile(config_path):
            import json
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    json.load(f)
                lines.append(f"  OK  config.json (valid JSON)")
            except json.JSONDecodeError as e:
                lines.append(f"  FAIL config.json: {e}")
        else:
            lines.append("  SKIP config.json (not found)")

        example_path = os.path.join(PROJECT_ROOT, "config.example.json")
        if os.path.isfile(example_path):
            import json
            try:
                with open(example_path, "r", encoding="utf-8") as f:
                    json.load(f)
                lines.append(f"  OK  config.example.json (valid JSON)")
            except json.JSONDecodeError as e:
                lines.append(f"  FAIL config.example.json: {e}")

        toc_path = os.path.join(PROJECT_ROOT, "tools", "TOC.md")
        if os.path.isfile(toc_path):
            lines.append(f"  OK  tools/TOC.md (found)")
        else:
            lines.append("  WARN tools/TOC.md (not found)")

        return "\n".join(lines)