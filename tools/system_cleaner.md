---
name: system_cleaner
description: "SYSTEM JUNK ONLY: temp files, Python caches, recycle bin. NOT for general file deletion."
parameters:
  target_type: {type: string, enum: [temp, python_cache, recycle_bin, all], description: "Target type (default all)"}
  dry_run: {type: boolean, description: "Preview (true, default) or delete (false)"}
examples:
  - {target_type: temp, dry_run: true, note: "Preview temp files"}
  - {target_type: all, dry_run: false, note: "Clean everything"}
usage_notes:
  - "Default is dry_run=true — always preview first"
  - "Python cache only cleans __pycache__ within the project, not system-wide"
  - "Recycle bin requires Windows"
---

# system_cleaner

Cleans system junk with a simple interface. Choose what to clean, preview first,
then run with `dry_run=false` to actually delete.
