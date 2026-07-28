---
name: job
description: "Manage detached shell jobs for commands that may run for minutes or hours. Start returns a job_id immediately; inspect status/logs or cancel later."
parameters:
  action:
    type: string
    enum: [start, status, logs, list, cancel]
    required: true
  command:
    type: string
    description: Shell command for start.
  cwd:
    type: string
    description: Working directory for start.
  job_id:
    type: string
    description: Identifier for status, logs, or cancel.
  tail_lines:
    type: integer
    description: Trailing log lines, default 100.
---

# Background Job Tool

Use `start` for commands expected to run longer than an ordinary foreground tool call. It returns immediately with a `job_id`. Use `status` and `logs` in later turns; use `cancel` only when the user requests cancellation. Job metadata and logs are stored in the user's local Chengsi data directory and survive application restarts.