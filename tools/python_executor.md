---
name: python_executor
description: "Run Python code for calculations, data processing, loops/conditionals, and Python libraries. Not a shell substitute. Mass-deletion blocked; single-file os.remove() is allowed. Returns stdout+stderr."
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
  - Single-file deletion (os.remove, os.unlink, os.rmdir) is allowed. Mass-deletion (shutil.rmtree, rm -rf *, del /F /S) is blocked.
  - The core and knowledge directories are permanently protected.
  - Use bash for command-line programs, package installation, git, and system commands.
  - Prefer read for file inspection and code search; use write or edit for file changes.
  - stdout and stderr are returned separately.
---
