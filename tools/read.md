---
name: read
description: "Read text files, PDFs, DOCX, view images, or search code — one unified inspector"
parameters:
  path: {type: string, description: "File path to read (text, PDF, DOCX, or image). For search: optional root directory."}
  query: {type: string, description: "Search query — activates code search mode"}
  offset: {type: integer, description: "Start line/page/paragraph (1-indexed)"}
  limit: {type: integer, description: "Max lines(200)/pages(1)/paragraphs(50)/results(20)"}
  ext: {type: string, description: "File extension filter (e.g. .py)"}
  glob: {type: string, description: "Glob pattern for search, overrides ext"}
  case_sensitive: {type: boolean, description: "Case-sensitive search (default false)"}
  mode: {type: string, description: "'text' (default) or 'visual' for PDF/DOCX"}
examples:
  - {query: "def run", glob: "*.py", limit: 5, note: "Search with glob"}
  - {query: "TODO", path: "src/", case_sensitive: true, note: "Case-sensitive search in dir"}
  - {path: paper.pdf, offset: 1, note: "PDF page 1 as text"}
  - {path: report.docx, offset: 1, limit: 20, note: "DOCX paragraphs 1-20"}
usage_notes:
  - "Search: set query to activate. Use glob for file name filter, ext for extension, case_sensitive for exact case."
  - "PDF text: PyMuPDF preferred; falls back to pypdf"
  - "PDF/DOCX visual: renders at 200 DPI → vision models read tables/figures/formulas"
  - "DOCX text: paragraphs + tables (pipe-delimited), embedded image count, formatting markers"
  - "Auto-truncates at 50KB; use offset to paginate"
---

# read

One tool for all file inspection and code search.

## Modes

| Action | Parameters |
|--------|-----------|
| Read text | `path` |
| Read image | `path` (jpg/png/gif/webp/bmp) |
| Read PDF | `path` ± `offset`/`limit` pages |
| Read DOCX | `path` ± `offset`/`limit` paragraphs |
| Search code | `query` ± `glob`/`ext`/`case_sensitive` |
| Search in dir | `query` + `path` + `glob` |
