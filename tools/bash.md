---
name: bash
description: "Run a bounded foreground shell command for quick one-shot terminal tasks. Returns stdout+stderr. Use job for commands that may run longer."
parameters:
  command: {type: string, description: "Shell command to execute", required: true}
  timeout: {type: integer, description: "Maximum seconds, 5-600; default 30"}
  cwd: {type: string, description: "Working directory; defaults to the Chengsi project root"}
examples:
  - {command: dir, note: "List files on Windows"}
  - {command: "find . -name '*.py' | head -5", note: "Find Python files on Linux"}
  - {command: "python -m pip install requests", note: "Install into Chengsi's active virtual environment"}
usage_notes:
  - "Timeout defaults to 30 seconds and is bounded to 5-600 seconds"
  - "Runs in the Chengsi project root unless cwd is explicitly supplied"
  - "Returns both stdout and stderr, plus exit code on failure"
---

# bash

Execute a shell command directly. Works like a terminal — `dir`/`ls` for listing,
`find`/`grep` for searching, `mkdir`/`cp`/`mv` for file operations, and
`python -m pip install` for packages. Python and pip commands are automatically bound to
Chengsi's active virtual environment.

Prefer this over `python_executor` for simple shell operations.