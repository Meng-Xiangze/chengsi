---
name: bash
description: "Run a shell command. Preferred for: file ops (ls, cp, mv, rm, mkdir, find), git, pip install — one-shot terminal tasks. For multi-step logic use python_executor. Returns stdout+stderr. 60s timeout."
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
