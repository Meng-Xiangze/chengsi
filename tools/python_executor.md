---
name: python_executor
description: Execute Python code for system operations, calculations, diagnostics, and controlled file management.
parameters:
  code:
    type: string
    description: Required Python code to execute.
    required: true
examples:
  - action: python_executor
    arguments:
      code: "import platform; print(platform.platform())"
usage_notes:
  - Use for OS commands, calculations, package installation, diagnostics, and file operations such as create, copy, move, rename, and packaging.
  - Direct deletion is blocked; use system_cleaner for controlled cleanup and deletion.
  - The core and knowledge directories are permanently protected.
  - Prefer code_editor or code_context for routine project source reads, edits, and searches.
  - stdout and stderr are returned separately.
---
