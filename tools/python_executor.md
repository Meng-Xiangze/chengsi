---
name: python_executor
description: "Run Python code for calculations, data processing, loops/conditionals, and Python libraries. Not a shell substitute. Deletion blocked; use system_cleaner. Returns stdout+stderr."
parameters:
  code:
    type: string
    description: Python code to execute
    required: true
examples:
  - action: python_executor
    arguments:
      code: "import platform; print(platform.platform())"
usage_notes:
  - Use for calculations, structured data processing, loops/conditionals, and direct Python library APIs.
  - Code runs in an isolated child Python process. Child stdout and stderr are captured and returned to the WebUI; they must not be used as a hidden terminal channel.
  - Child stdin is closed. Interactive commands such as `gh auth login`, `git push` credential prompts, editors, and confirmation prompts fail or exit instead of waiting for input.
  - For GitHub authentication, ask the user to complete `gh auth login` in a separate trusted terminal, then retry the requested task.
  - Direct deletion is blocked; use system_cleaner for controlled cleanup and deletion.
  - The core and knowledge directories are permanently protected.
  - Use bash for command-line programs, package installation, git, and system commands.
  - Prefer read for file inspection and code search; use write or edit for file changes.
  - stdout and stderr are returned separately.
---
