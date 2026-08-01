---
name: bash
description: "Run quick bounded command-line programs such as git status/diff/log, rg, fd, small tests, version checks, and system utilities. Returns stdout+stderr. Use job for pip install/download, installers, downloads, git clone, dependency setup, large extraction, and long builds."
parameters:
  command: {type: string, description: "Shell command to execute", required: true}
  timeout: {type: integer, description: "Maximum seconds, 5-600; default 30"}
  cwd: {type: string, description: "Working directory; defaults to the Chengsi project root"}
examples:
  - {command: dir, note: "List files on Windows"}
  - {command: "find . -name '*.py' | head -5", note: "Find Python files on Linux"}
  - {command: "git status --short", note: "Quick foreground command"}
usage_notes:
  - "Timeout defaults to 30 seconds and is bounded to 5-600 seconds"
  - "Runs in the Chengsi project root unless cwd is explicitly supplied"
  - "Returns both stdout and stderr, plus exit code on failure"
  - "Output decoding is automatic and mixed-encoding safe: UTF-8 and legacy GBK console output both render correctly"
  - "PowerShell 5.1 reads UTF-8 files as ANSI by default; use [IO.File]::ReadAllText(path) or Get-Content -Encoding UTF8 for UTF-8 file content"
---

# bash

Execute a quick command-line program directly. Use it for `git status/diff/log`, `rg`, `fd`, small tests,
version checks, and system utilities. Route `pip install`, package installation, downloads, installers,
clones, dependency setup, large extraction, and long builds to `job(action='start')`. Python and pip commands are automatically bound
to Chengsi's active virtual environment. Use `read`, `write`, and `edit` for normal file work,
and use `python_executor` for calculations, structured data processing, or direct Python APIs.