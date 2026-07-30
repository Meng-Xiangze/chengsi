import ast
import base64
import os
import subprocess
import sys
import warnings
from typing import Any, Dict
from core.process_utils import child_environment, decode_output
from tools.base import BaseTool

# Suppress all warnings to prevent polluting Agent output with non-critical logs
warnings.filterwarnings("ignore")

class PythonExecutor(BaseTool):
    _BLOCKED_CALLS = {
        "remove", "unlink", "rmtree", "rmdir", "removedirs",
    }

    @classmethod
    def _destructive_operation(cls, code: str) -> str | None:
        """Reject deletion; project protection is enforced by dedicated file tools."""
        try:
            tree = ast.parse(code)
        except SyntaxError as error:
            return f"Error: invalid Python code: {error}"
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                name = function.attr if isinstance(function, ast.Attribute) else function.id if isinstance(function, ast.Name) else ""
                if name in cls._BLOCKED_CALLS:
                    return f"Error: deletion operation '{name}' is blocked in python_executor. Use system_cleaner for controlled deletion."
                if name in {"system", "popen", "run", "call", "check_call", "check_output"}:
                    source = ast.get_source_segment(code, node) or ""
                    if any(token in source.lower() for token in (" os.remove", " del ", "rm -", "rmdir", "unlink")):
                        return "Error: destructive shell/file operation is blocked in python_executor."
        return None

    @property
    def tool_name(self) -> str:
        return "python_executor"

    @property
    def description(self) -> str:
        return ("Run Python code in an isolated child process. PREFERRED for: multi-step logic, "
                "data processing (JSON, CSV, text), calculations, API calls, string/encoding work, "
                "or anything needing loops, conditionals, or libraries. "
                "Stdout/stderr returned; stdin closed. Deletion blocked (use bash rm). "
                "For one-shot file ops, git, or shell commands, use bash instead.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "code": {
                "type": "string",
                "description": "The Python code to be executed."
            }
        }

    def run(self, arguments: Dict[str, Any]) -> str:
        code = arguments.get("code", "")
        if not code:
            return "Error: No code provided."

        code = str(code)
        blocked = self._destructive_operation(code)
        if blocked:
            return blocked

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
                timeout=300,
                check=False,
                env=child_environment(),
            )
        except subprocess.TimeoutExpired as error:
            stdout_res = decode_output(error.stdout)
            stderr_res = decode_output(error.stderr)
            return self._format_result(stdout_res, stderr_res, "Execution timed out after 300 seconds.")
        except OSError as error:
            return f"Error: could not start isolated Python process: {error}"

        stdout_res = decode_output(completed.stdout)
        stderr_res = decode_output(completed.stderr)
        if completed.returncode:
            stderr_res = stderr_res or f"Execution failed with exit code {completed.returncode}."
        return self._format_result(stdout_res, stderr_res)

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
