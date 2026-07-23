---
name: code_context
description: Search project files by keyword or regex and show matching lines with context.
parameters:
  query:
    type: string
    description: Required keyword or regular expression.
    required: true
  ext:
    type: string
    description: Optional extension filter such as .py.
  max_results:
    type: integer
    description: Maximum matches; default 20.
    default: 20
examples:
  - action: code_context
    arguments:
      query: "ToolManager"
      ext: ".py"
usage_notes:
  - Use a plain keyword when possible; regex is supported.
  - This searches project files, not the whole computer.
---
