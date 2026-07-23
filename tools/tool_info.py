import os
from typing import Any, Dict
from tools.base import BaseTool


class ToolInfo(BaseTool):
    @property
    def tool_name(self) -> str:
        return "tool_info"

    @property
    def description(self) -> str:
        return "Look up full documentation for any registered tool by name."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "tool_name": {
                "type": "string",
                "description": "The name of the tool to look up."
            }
        }

    def run(self, arguments: Dict[str, Any]) -> str:
        tool_name = arguments.get("tool_name", "").strip()
        if not tool_name:
            return "Error: No tool_name provided."

        tools_dir = os.path.abspath(os.path.dirname(__file__))
        md_path = os.path.join(tools_dir, f"{tool_name}.md")

        if os.path.isfile(md_path):
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    body = parts[2].strip()
                    return f"Documentation for `{tool_name}`:\n\n{body}"
            return f"Documentation for `{tool_name}`:\n\n{content}"

        return (
            f"No documentation file found for '{tool_name}'. "
            f"The tool may not have a .md file yet. "
            f"Check the available tools list or call the tool directly."
        )
