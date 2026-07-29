---
name: read
description: "Read files, inspect Python symbols, or search code with stable edit anchors"
parameters:
  path: {type: string, description: "File path to read. For search: optional root directory."}
  query: {type: string, description: "Search query or regex; activates search mode"}
  offset: {type: integer, description: "Start line/page/paragraph (1-indexed)"}
  limit: {type: integer, description: "Maximum lines/pages/paragraphs/results"}
  ext: {type: string, description: "File extension filter for search"}
  glob: {type: string, description: "File name glob for search; overrides ext"}
  case_sensitive: {type: boolean, description: "Case-sensitive search (default false)"}
  mode: {type: string, enum: [text, visual, outline, symbol], description: "Read mode"}
  symbol: {type: string, description: "Qualified Python symbol for mode=symbol"}
examples:
  - {path: core/agent_runtime.py, mode: outline}
  - {path: core/agent_runtime.py, mode: symbol, symbol: AgentRuntime.observe}
  - {path: main.py, offset: 1000, limit: 120}
  - {query: "def run", glob: "*.py", limit: 5}
  - {path: paper.pdf, mode: visual, offset: 1}
usage_notes:
  - "Text and symbol output includes a file revision and LINE:HASH anchors"
  - "Use mode=outline before mode=symbol when the exact qualified name is unknown"
  - "Copy revision and anchors exactly into edit; stale content is rejected"
  - "PDF/DOCX visual mode renders pages for vision models"
---

# read

Use `mode=outline` to inspect Python classes and functions without reading the whole file. Use
`mode=symbol` with a qualified name such as `AgentRuntime.observe` to return one complete definition.

Text output follows this protocol:

```text
[file: path rev: CONTENT_HASH lines: 100 showing: 20-30]
[format: LINE:HASH|content; copy anchors exactly for edit operations]
20:0123456789abcdef|def example():
```

The revision guards the complete file. Each line anchor guards the exact line content. Prefer these
values for multiline edits instead of reproducing a large `oldText` string.
