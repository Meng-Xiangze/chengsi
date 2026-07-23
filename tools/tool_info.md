---
name: tool_info
description: Look up full documentation for any registered tool by name (parameters, examples, usage notes).
parameters:
  tool_name:
    type: string
    description: The name of the tool to look up.
examples:
  - action: tool_info
    arguments:
      tool_name: "python_executor"
usage_notes:
  - Use this before calling a tool you are unfamiliar with.
  - Returns the full .md documentation for the requested tool.
  - If the tool has no .md file, returns a basic summary from the registry.
---

# tool_info

Returns the full documentation for any registered tool. Use this when you need details about parameters, examples, or usage notes before making a tool call.

## Parameters

| Name | Type | Description |
|------|------|-------------|
| `tool_name` | string | Name of the tool to look up |
