---
name: bash
description: "Run a bounded foreground shell command for quick one-shot terminal tasks. Returns stdout+stderr. 60s timeout; use job for commands that may run longer."
parameters:
  command: {type: string, description: "Shell command to execute", required: true}
examples:
  - {command: dir, note: "List files on Windows"}
  - {command: "find . -name '*.py' | head -5", note: "Find Python files on Linux"}
  - {command: "pip install requests", note: "Install a Python package"}
usage_notes:
  - "Timeout is 60 seconds"
  - "Runs in the current working directory"
  - "Returns both stdout and stderr, plus exit code on failure"
---

# bash

Execute a shell command directly. Works like a terminal — `dir`/`ls` for listing,
`find`/`grep` for searching, `mkdir`/`cp`/`mv` for file operations, `pip install` for
packages, and anything else a command line can do.

Prefer this over `python_executor` for simple shell operations.