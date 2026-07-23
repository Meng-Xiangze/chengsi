---
name: system_cleaner
description: Preview or clean temp files, caches, logs, Python caches, or an explicitly specified directory with precise filters.
parameters:
  target_types:
    type: array
    description: "Cleanup categories: temp, cache, python_cache, logs, recycle_bin, or custom."
  target_type:
    type: string
    description: "Backward-compatible single category; prefer target_types for multiple categories."
  path:
    type: string
    description: "Scan root; required for custom and defaults to the project root."
  extensions:
    type: array
    description: "Optional extensions such as ['.tmp', '.log']."
  older_than_days:
    type: number
    description: "Only select items whose modification time is at least this many days old."
  min_size_mb:
    type: number
    description: "Only select files at least this large."
  dry_run:
    type: boolean
    description: Preview only; default true. Set false only for explicit deletion.
    default: true
  force:
    type: boolean
    description: Continue after locked-item errors; default false.
    default: false
usage_notes:
  - Clear cleanup requests execute directly; use dry_run=true only for an explicit preview request.
  - The core and knowledge directories are permanently protected.
  - Use target_types to combine categories in one request.
  - Use python_cache for __pycache__, .pyc, and .pyo files.
  - Use extensions, older_than_days, and min_size_mb to narrow the selection.
  - Custom paths should be used only when explicitly requested.
---
