import ast
import sys
import io
import contextlib
import warnings
from typing import Any, Dict
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
        return ("Execute Python code on the host machine for system operations, calculations, package installs, "
                "diagnostics, and file management such as creating, copying, moving, renaming, or packaging files. "
                "Direct deletion is blocked; use system_cleaner. Use code_editor or code_context for routine project "
                "source reads, edits, and searches. Manage knowledge-base records only through knowledge_base.")

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

        blocked = self._destructive_operation(str(code))
        if blocked:
            return blocked

        output_buffer = io.StringIO()
        error_buffer = io.StringIO()
        
        with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(error_buffer):
            try:
                exec_globals = {}
                exec(code, exec_globals)
            except Exception as e:
                # We print to stderr so it gets captured by error_buffer
                print(f"Execution Error: {e}", file=sys.stderr)

        stdout_res = output_buffer.getvalue()
        stderr_res = error_buffer.getvalue()
        
        result = []
        if stdout_res:
            result.append(f"--- STDOUT ---\n{stdout_res}")
        if stderr_res:
            result.append(f"--- STDERR ---\n{stderr_res}")
        
        return "\n".join(result) if result else "Code executed successfully (no output)."

if __name__ == "__main__":
    # Manual testing
    executor = PythonExecutor()
    print(f"Testing {executor.tool_name}...")
    print(executor.run({"code": "print('Hello from Class-based tool!'); print(123 * 456)"}))
