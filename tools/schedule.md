---
name: schedule
description: Create and manage persistent scheduled agent tasks that can call normal Chengsi tools when triggered.
parameters:
  action:
    type: string
    enum: [create, list, cancel]
    required: true
  prompt:
    type: string
    description: Work to perform when triggered. Required for create.
  run_at:
    type: string
    description: Local ISO datetime, for example 2026-08-01T09:30:00.
  interval_seconds:
    type: integer
    description: Repeat interval in seconds, minimum 60. Omit for one-time tasks.
  schedule_id:
    type: string
    description: Schedule identifier for cancel.
---

# Schedule Tool

Use this tool for persistent time-based agent work. The scheduled prompt starts a normal Chengsi turn, so it may call `web_searcher`, `read`, or other available tools. Use an explicit local ISO datetime. Repeating tasks require `interval_seconds` of at least 60. Scheduled work sends its result to the session that created it.
