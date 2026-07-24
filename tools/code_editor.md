---
name: code_editor
description: Read and safely modify project files using content-verified line anchors.
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
  revision:
    type: string
    description: Optional revision copied from read; rejects a stale file snapshot.
  operations:
    type: array
    description: Hash edits copied from read/search anchors.
    items:
      type: object
      properties:
        op:
          type: string
          enum: [delete, insert_after, insert_before, replace]
        start:
          type: string
          description: Starting LINE:HASH anchor.
        end:
          type: string
          description: Optional ending LINE:HASH anchor for replace/delete.
        content:
          type: string
          description: Replacement or inserted text.
      required: [op, start]
  offset:
    type: integer
    description: First line for read; default 1.
  limit:
    type: integer
    description: Maximum read lines; default 400, maximum 2000.
  pattern:
    type: string
    description: Regex or text for search.
  glob:
    type: string
    description: Filename glob for search.
  max_results:
    type: integer
    description: Maximum search matches; default 50.
  backup:
    type: boolean
    description: Create .bak before changes; default false.
    default: false
  encoding:
    type: string
    description: File encoding; default utf-8.
    default: utf-8
examples:
  - action: code_editor
    arguments:
      action: read
      path: tools/example.py
      offset: 1
      limit: 200
  - action: code_editor
    arguments:
      action: edit
      path: tools/example.py
      revision: 71c8a5d2b103
      operations:
        - op: replace
          start: "12:a4f0"
          end: "14:990b"
          content: "def updated():\n    return True"
usage_notes:
  - Read before edit and copy LINE:HASH anchors exactly.
  - Supported edit ops are replace, delete, insert_before, and insert_after.
  - Use start and end for a range. end is valid only for replace and delete.
  - Batch related operations in one call; overlapping targets are rejected.
  - A hash or revision mismatch means the file changed; re-read and retry once.
  - Use write only for new files or intentional complete rewrites.
  - The running core directory and main.py are read-only.
---

# Hash-anchored editing

Read output uses this format:

```text
[file: tools/example.py rev: 71c8a5d2b103 lines: 3 showing: 1-3]
[format: LINE:HASH|content; copy anchors exactly for edit operations]
1:9d41|import os
2:0e3a|
3:80b2|def run():
```

An anchor verifies both the line position and its current content. Never guess an anchor. If validation fails, re-read the file before editing again.
