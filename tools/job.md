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
  auto_followup:
    type: boolean
    description: Automatically process the terminal result only when the user's original request explicitly asks for continuation. Default false.
---

# Background Job Tool

Use `start` for commands expected to run longer than an ordinary foreground tool call. It returns immediately with a `job_id` and `status: starting`; this means only that the job was accepted, not that the command completed. Never report the requested work as complete until a later status or completion event says `status: completed`. A `failed`, `interrupted`, `cancelled`, or nonzero exit status must be reported as failure. Every terminal job sends a user-facing notification. Set `auto_followup: true` only when the original request explicitly asks Chengsi to continue automatically after completion, such as generating a report from finished output. Otherwise leave it false and wait for the user's next request. Use `status` and `logs` in later turns; use `cancel` only when the user requests cancellation. Job metadata and logs are stored in the user's local Chengsi data directory and survive application restarts.