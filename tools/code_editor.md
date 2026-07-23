---
name: code_editor
description: Read or safely modify project files with predictable actions.
parameters:
  action:
    type: string
    description: read, write, edit, or search. Default read.
    default: read
  path:
    type: string
    description: Relative project file path.
    required: true
  content:
    type: string
    description: Complete content for write.
  old:
    type: string
    description: Exact text for edit; first match only.
  new:
    type: string
    description: Replacement text for edit.
  backup:
    type: boolean
    description: Create .bak before changes; default false.
    default: false
  encoding:
    type: string
    description: File encoding; default utf-8.
    default: utf-8
  changes:
    type: array
    description: Optional edit list of old/new objects.
usage_notes:
  - Read before edit.
  - Use this for project files; do not use python_executor for project file I/O.
---
