---
name: edit
description: "Atomically edit text with Python symbols, hash ranges, or short exact-text anchors"
parameters:
  path: {type: string, description: "File path to edit"}
  edits:
    type: array
    description: "Non-overlapping edit operations applied atomically"
    items:
      properties:
        op: {type: string, enum: [replace_symbol, delete_symbol, replace_range, delete_range, insert_before_anchor, insert_after_anchor, replace, delete, insert_before, insert_after, prepend, append]}
        symbol: {type: string, description: "Qualified Python symbol for symbol operations"}
        start: {type: string, description: "Inclusive start LINE:HASH anchor for range operations"}
        end: {type: string, description: "Inclusive end LINE:HASH anchor for range operations"}
        anchor: {type: string, description: "LINE:HASH anchor for anchored insertion"}
        oldText: {type: string, description: "Short unique text for legacy text operations"}
        newText: {type: string, description: "Replacement or inserted text"}
  revision: {type: string, description: "Optional file revision from read; rejects stale edits"}
examples:
  - {path: app.py, revision: 0123456789abcdef01234567, edits: [{op: replace_symbol, symbol: App.run, newText: "    def run(self):\n        return True\n"}]}
  - {path: app.py, revision: 0123456789abcdef01234567, edits: [{op: replace_range, start: "20:0123456789abcdef", end: "24:fedcba9876543210", newText: "replacement\n"}]}
  - {path: config.py, edits: [{oldText: "DEBUG = True", newText: "DEBUG = False"}]}
usage_notes:
  - "Prefer replace_symbol for a complete Python function, method, or class"
  - "Prefer hash range operations for multiline code not represented by one symbol"
  - "Range start and end anchors are inclusive whole lines"
  - "Use oldText only for short text known to be unique"
  - "All edits are validated before an atomic write; overlapping edits are rejected"
  - "Python files are parsed after editing and invalid syntax is never written"
---

# edit

Editing priority:

1. `replace_symbol` or `delete_symbol` for complete Python definitions.
2. `replace_range` or `delete_range` with anchors copied from `read` for multiline changes.
3. `insert_before_anchor` or `insert_after_anchor` for stable line-relative insertion.
4. Exact `oldText` operations for short unique values.

A supplied `revision` must match the current file. Hash anchors also validate their line contents, so
stale model context produces an error instead of changing the wrong location.
