# -*- coding: utf-8 -*-
import os
import sys
import re
from typing import Any, Dict

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.base import BaseTool

TOOLS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))


class ToolCreator(BaseTool):
    TEMPLATE = '''# -*- coding: utf-8 -*-
from tools.base import BaseTool


class MyTool(BaseTool):
    @property
    def tool_name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "What this tool does in one sentence."

    @property
    def parameters(self) -> dict:
        return {
            "arg_name": {
                "type": "string",
                "description": "What this argument does."
            }
        }

    def run(self, arguments: dict) -> str:
        arg = arguments.get("arg_name", "")
        # Your logic here
        return f"Result: {arg}"
'''

    @property
    def tool_name(self) -> str:
        return "tool_creator"

    @property
    def description(self) -> str:
        return "Create, update, or delete tools in the tools/ directory."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "description": "One of: 'create', 'delete', 'template'."
            },
            "tool_name": {
                "type": "string",
                "description": "The tool name (no .py suffix)."
            },
            "code": {
                "type": "string",
                "description": "[create] Full Python source for the tool class."
            },
            "description": {
                "type": "string",
                "description": "[create] One-line description for the TOC catalog."
            }
        }

    def run(self, arguments: dict) -> str:
        action = arguments.get("action", "create").strip().lower()
        tool_name = arguments.get("tool_name", "").strip()

        if action == "template":
            return self.TEMPLATE

        if not tool_name:
            return "Error: 'tool_name' is required."

        safe_name = "".join(c for c in tool_name if c.isalnum() or c in ("_", "-"))
        if not safe_name:
            return "Error: Invalid tool name."

        if action == "delete":
            return self._delete_tool(safe_name)
        elif action == "create":
            return self._create_tool(safe_name, arguments)
        else:
            return f"Error: Unknown action '{action}'. Use 'create', 'delete', or 'template'."

    def _create_tool(self, name: str, arguments: dict) -> str:
        code = arguments.get("code", "").strip()
        one_liner = arguments.get("description", "").strip()

        if not code:
            return "Error: 'code' is required for create."

        # Validate structure
        errors = []
        if "BaseTool" not in code:
            errors.append("Class must inherit from BaseTool")
        if "def tool_name" not in code:
            errors.append("Must implement 'tool_name' property")
        if "def description" not in code:
            errors.append("Must implement 'description' property")
        if "def parameters" not in code:
            errors.append("Must implement 'parameters' property")
        if "def run" not in code:
            errors.append("Must implement 'run(self, arguments)' method")
        if errors:
            return "Validation failed:\n- " + "\n- ".join(errors) + "\n\nCall action='template' to see a working skeleton."

        # 1. Write .py file (always UTF-8, including Chinese comments/docstrings)
        py_path = os.path.join(TOOLS_DIR, f"{name}.py")
        try:
            if not code.startswith("# -*- coding: utf-8 -*-"):
                code = "# -*- coding: utf-8 -*-\n" + code
            with open(py_path, "w", encoding="utf-8", newline="") as f:
                f.write(code)
        except Exception as e:
            return f"Error writing {name}.py: {e}"

        # 2. Auto-generate .md doc file with safe YAML front matter
        md_path = os.path.join(TOOLS_DIR, f"{name}.md")
        desc_line = one_liner or f"Custom tool: {name}"

        # --- 关键修改：安全转义描述，避免 YAML 解析错误 ---
        # 将描述中的双引号转义为 \" ，并用双引号整体包裹
        escaped_desc = desc_line.replace('\\', '\\\\').replace('"', '\\"')
        # 如果描述含换行，转成 \n 以便单行显示（可选）
        escaped_desc = escaped_desc.replace('\n', '\\n')

        try:
            with open(md_path, "w", encoding="utf-8", newline="") as f:
                # 写入 YAML front matter，其中 description 用双引号包裹
                f.write(f"---\n")
                f.write(f"name: {name}\n")
                f.write(f"description: \"{escaped_desc}\"\n")
                f.write(f"parameters: {{}}\n")
                f.write(f"examples: []\n")
                f.write(f"usage_notes: []\n")
                f.write(f"---\n\n")
                f.write(f"# {name}\n\n{desc_line}\n\n")
                f.write("(Auto-generated. Edit this file to add parameters, examples, and usage notes.)\n")
        except Exception as e:
            # 即使文档生成失败，也不影响工具创建，只记录警告
            print(f"Warning: Could not write doc file: {e}")

        # 3. Incrementally append to TOC.md
        try:
            from core.tool_manager import _ToolRegistry
            registry = _ToolRegistry(TOOLS_DIR)
            registry.add_tool_entry(name, desc_line)
        except Exception:
            pass

        return (
            f"Successfully created tool: {name}.py\n"
            f"Documentation: {name}.md\n"
            f"The tool is now available after reload."
        )

    def _delete_tool(self, name: str) -> str:
        results = []

        # 1. Remove .py file
        py_path = os.path.join(TOOLS_DIR, f"{name}.py")
        if os.path.isfile(py_path):
            os.remove(py_path)
            results.append(f"Removed {name}.py")
        else:
            results.append(f"Note: {name}.py not found")

        # 2. Remove .md file
        md_path = os.path.join(TOOLS_DIR, f"{name}.md")
        if os.path.isfile(md_path):
            os.remove(md_path)
            results.append(f"Removed {name}.md")
        else:
            results.append(f"Note: {name}.md not found")

        # 3. Remove from TOC.md (incremental)
        try:
            from core.tool_manager import _ToolRegistry
            registry = _ToolRegistry(TOOLS_DIR)
            registry.remove_tool_entry(name)
            results.append(f"Removed {name} from TOC.md")
        except Exception:
            results.append("Note: Could not update TOC.md")

        return "\n".join(results) + f"\nTool '{name}' deleted. Reload to take effect."