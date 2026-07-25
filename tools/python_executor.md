---
name: python_executor
description: "Run Python code. Preferred for: multi-step logic, data processing (JSON, CSV), calculations, loops/conditionals. Deletion blocked — use bash rm. Returns stdout+stderr."
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
  - Code runs in an isolated child Python process. Child stdout and stderr are captured and returned to the WebUI; they must not be used as a hidden terminal channel.
  - Child stdin is closed. Interactive commands such as `gh auth login`, `git push` credential prompts, editors, and confirmation prompts fail or exit instead of waiting for input.
  - For GitHub authentication, ask the user to complete `gh auth login` in a separate trusted terminal, then retry the requested task.
  - Direct deletion is blocked; use system_cleaner for controlled cleanup and deletion.
  - The core and knowledge directories are permanently protected.
  - Prefer read for file inspection and code search; use edit for edits.
  - stdout and stderr are returned separately.
---
