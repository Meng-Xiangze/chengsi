---
name: edit
description: "Precise surgical edits — replace, insert, delete, prepend, append with exact-text anchors"
parameters:
  path: {type: string, description: "File path to edit"}
  edits:
    type: array
    description: "List of {op, oldText, newText} objects."
    items:
      properties:
        op: {type: string, enum: [replace, insert_before, insert_after, delete, prepend, append], description: "Operation (default replace)"}
        oldText: {type: string, description: "Unique anchor text (skip for prepend/append)"}
        newText: {type: string, description: "Replacement or insert text (skip for delete)"}
  revision: {type: string, description: "Optional content hash guard"}
examples:
  - {path: config.py, edits: [{oldText: "DEBUG = True", newText: "DEBUG = False"}]}
  - {path: app.py, edits: [{op: insert_after, oldText: "import sys\n", newText: "import os\n"}]}
  - {path: README.md, edits: [{op: prepend, newText: "# My Project\n\n"}]}
  - {path: report.docx, edits: [{oldText: "Abstract", newText: "{size:14,bold}Abstract{/size}"}]}
usage_notes:
  - "Operations: replace(默认), insert_before, insert_after, delete, prepend, append"
  - "Aliases: remove=delete, add_before=insert_before, add_after=insert_after"
  - "oldText must be unique (exact character match) and edits must not overlap"
  - "Applied atomically from bottom to top (safe line-number-wise)"
  - "DOCX: oldText matches paragraph text; newText supports inline formatting markers"
  - "revision: sha256[:12]; use to prevent editing a stale file"
---

# edit

Precise file editing with exact-text anchors. Supports replace, insert, delete, prepend, append operations on both text files and .docx.

## Text file operations

| op | oldText | newText | 效果 |
|----|---------|---------|------|
| `replace` | 原文（唯一） | 新文本 | 替换 |
| `delete` | 原文（唯一） | — | 删除 |
| `insert_before` | 锚文本 | 插入内容 | 在锚前插入 |
| `insert_after` | 锚文本 | 插入内容 | 在锚后插入 |
| `prepend` | — | 内容 | 文件开头插入 |
| `append` | — | 内容 | 文件末尾追加 |

## Example

```json
{
  "path": "app.py",
  "edits": [
    {"op": "prepend", "newText": "# coding: utf-8\n"},
    {"op": "insert_after", "oldText": "import sys\n", "newText": "import os\nimport json\n"},
    {"oldText": "debug = True", "newText": "debug = False"},
    {"op": "delete", "oldText": "# TODO: remove this"}
  ],
  "revision": "a1b2c3d4e5f6"
}
```

## DOCX mode

Same operations; `oldText` matches paragraph text:

```json
{
  "path": "report.docx",
  "edits": [
    {"oldText": "Introduction", "newText": "{size:16,bold}1. Introduction{/size}"},
    {"op": "insert_after", "oldText": "Methods", "newText": "{color:red}⚠ Experimental{/color}"}
  ]
}
```
