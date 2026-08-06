import ast
import base64
import os
import re
import subprocess
import sys
import warnings
from typing import Any, Dict
from core.process_utils import child_environment, decode_output
from tools.base import BaseTool

# Suppress all warnings to prevent polluting Agent output with non-critical logs
warnings.filterwarnings("ignore")

# Only block the famous "删库跑路" meme patterns where the *target* is
# root, home, or a system drive.  Regular batch deletion (rm *.tmp,
# rm -rf ./build, del *.pyc, etc.) is always allowed.
_DANGEROUS_SHELL_PATTERNS = [
    # rm -rf /   rm -rf /*   rm -rf ~   rm -rf $HOME
    r"rm\s+-[rRf]+\s+(?:/|/\*|~|\$HOME)\b",
    # sudo rm (any sudo rm is suspicious in scripts)
    r"\bsudo\s+rm\s+",
    # rm -rf C:\  (MSYS / Cygwin / Git Bash on Windows)
    r"rm\s+-[rRf]+\s+[A-Za-z]:[\\/]",
    # del /F /S /Q C:\*  (recursive force from drive root)
    r"\bdel\s+/[Ff]\s+/[Ss]\s+(?:/[Qq]\s+)?[A-Za-z]:[\\/]\*",
    # format C: / format D: (not rm but same energy)
    r"\bformat\s+[A-Za-z]:",
]
_DANGEROUS_SHELL_RE = re.compile("|".join(_DANGEROUS_SHELL_PATTERNS), re.IGNORECASE)


class PythonExecutor(BaseTool):
    # shutil.rmtree is allowed but checked for dangerous target paths below.
    # os.remove / os.unlink / os.rmdir / os.removedirs are always allowed.

    @classmethod
    def _destructive_operation(cls, code: str) -> str | None:
        """Block only famous meme-level dangerous deletions (root/home/system)."""
        try:
            tree = ast.parse(code)
        except SyntaxError as error:
            return f"Error: invalid Python code: {error}"

        # Paths that are never OK to pass to a deletion function.
        DANGEROUS_PATHS = re.compile(
            r"['\"]\s*(?:/|/\*|~|\$HOME|[A-Za-z]:[\\/])\s*['\"]",
            re.IGNORECASE,
        )

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                name = function.attr if isinstance(function, ast.Attribute) else function.id if isinstance(function, ast.Name) else ""

                # Check subprocess calls for meme shell patterns
                if name in {"system", "popen", "run", "call", "check_call", "check_output"}:
                    source = ast.get_source_segment(code, node) or ""
                    if _DANGEROUS_SHELL_RE.search(source):
                        return "Error: dangerous deletion targeting root/home/system blocked. Use targeted paths."

                # shutil.rmtree('/') / rmtree('C:\\') etc. — only block when the
                # literal argument is root/home/system.  rmtree('./build') is fine.
                if name == "rmtree" and node.args:
                    source = ast.get_source_segment(code, node.args[0]) or ""
                    if DANGEROUS_PATHS.search(source):
                        return "Error: shutil.rmtree targeting root/home/system blocked."
        return None

    @property
    def tool_name(self) -> str:
        return "python_executor"

    @property
    def description(self) -> str:
        return ("Run Python code in an isolated child process. PREFERRED for: multi-step logic, "
                "data processing (JSON, CSV, text), calculations, API calls, string/encoding work, "
                "or anything needing loops, conditionals, or libraries. "
                "Stdout/stderr returned; stdin closed. "
                "Batch deletion is allowed; only meme-level dangers (rm -rf /, format C:) are blocked. "
                "Use bash for command-line programs; use read, write, and edit for files.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "code": {
                "type": "string",
                "description": "The Python code to be executed."
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum execution time in seconds. Default 300, maximum 1800.",
            },
        }

    def run(self, arguments: Dict[str, Any]) -> str:
        code = arguments.get("code", "")
        if not code:
            return "Error: No code provided."

        code = str(code)
        blocked = self._destructive_operation(code)
        if blocked:
            return blocked

        try:
            timeout = max(5, min(int(arguments.get("timeout", 300)), 1800))
        except (TypeError, ValueError):
            return {"ok": False, "content": "timeout must be an integer between 5 and 1800 seconds.", "error_code": "invalid_arguments"}

        # Run user code outside the WebView process. This prevents child
        # processes started by the code from inheriting Chengsi's console.
        runner = (
            "import base64, sys, traceback\n"
            "source = base64.b64decode(sys.argv[1]).decode('utf-8')\n"
            "try:\n"
            "    exec(source, {'__name__': '__main__'})\n"
            "except BaseException:\n"
            "    traceback.print_exc(file=sys.stderr)\n"
            "    raise SystemExit(1)\n"
        )
        encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        try:
            completed = subprocess.run(
                [sys.executable, "-c", runner, encoded],
                cwd=project_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                env=child_environment(),
            )
        except subprocess.TimeoutExpired as error:
            stdout_res = decode_output(error.stdout)
            stderr_res = decode_output(error.stderr)
            return {"ok": False, "content": self._format_result(stdout_res, stderr_res, f"Execution timed out after {timeout} seconds."), "error_code": "timeout"}
        except OSError as error:
            return {"ok": False, "content": f"Error: could not start isolated Python process: {error}", "error_code": "tool_error"}

        stdout_res = decode_output(completed.stdout)
        stderr_res = decode_output(completed.stderr)
        if completed.returncode:
            stderr_res = stderr_res or f"Execution failed with exit code {completed.returncode}."
        content = self._format_result(stdout_res, stderr_res)
        return {
            "ok": completed.returncode == 0,
            "content": content,
            "error_code": "ok" if completed.returncode == 0 else "python_error",
            "exit_code": completed.returncode,
        }

    @staticmethod
    def _format_result(stdout_res: str, stderr_res: str, extra_error: str = "") -> str:
        result = []
        if stdout_res:
            result.append(f"--- STDOUT ---\n{stdout_res}")
        if stderr_res:
            result.append(f"--- STDERR ---\n{stderr_res}")
        if extra_error:
            result.append(extra_error)
        return "\n".join(result) if result else "Code executed successfully (no output)."

if __name__ == "__main__":
    # Manual testing
    executor = PythonExecutor()
    print(f"Testing {executor.tool_name}...")
    print(executor.run({"code": "print('Hello from Class-based tool!'); print(123 * 456)"}))
