---
name: system_cleaner
description: "Preview and clean system temp files, Python caches, recycle bin"
parameters:
  target_type: {type: string, enum: [temp, python_cache, recycle_bin, all], description: "What to clean. Default: all"}
  dry_run: {type: boolean, description: "Preview only (true, default) or actually delete (false)"}
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
