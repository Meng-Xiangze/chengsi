---
name: file_deleter
description: "Safely delete specific files or directories with confirmation"
parameters:
  path:
    type: string
    description: Exact file or directory path to delete. Wildcards and '..' are not allowed.
    required: true
  confirm:
    type: boolean
    description: Must be true to perform deletion; false returns a refusal.
    required: true
examples:
  - action: file_deleter
    arguments:
      path: "C:/temp/example.txt"
      confirm: true
usage_notes:
  - Use only for a specific path supplied by the user.
  - Never use wildcards or parent-directory traversal.
---

# file_deleter

Safely delete specific files or directories with confirmation

(Auto-generated. Edit this file to add parameters, examples, and usage notes.)
