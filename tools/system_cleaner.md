---
name: system_cleaner
description: Preview or clean system temp files, application caches, Python caches, or the Windows recycle bin. Preview is the default.
parameters:
  target_types:
    type: array
    description: "Cleanup categories: temp, cache, python_cache, or recycle_bin."
  target_type:
    type: string
    description: "Backward-compatible single category; prefer target_types for multiple categories."
  path:
    type: string
    description: "Optional directory override for supported cleanup categories."
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
  - Preview is the default; set dry_run=false only for an explicit deletion request.
  - Use target_types to combine categories in one request.
  - Use python_cache for __pycache__, .pyc, and .pyo files.
  - Use extensions, older_than_days, and min_size_mb to narrow the selection.
  - Use file_deleter for one specific user-named file or directory.
---
