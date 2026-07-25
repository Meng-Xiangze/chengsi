---
name: read
description: "Read text files, PDFs, DOCX, view images, or search code — one unified inspector"
parameters:
  path: {type: string, description: "File path to read (text, PDF, DOCX, or image). For search: optional root directory."}
  query: {type: string, description: "Search query — activates code search mode"}
  offset: {type: integer, description: "For text: line (1-indexed). PDF: page. DOCX: paragraph."}
  limit: {type: integer, description: "For text: max lines (200). PDF: max pages (1). DOCX: max paragraphs (50). Search: max results (20)."}
  ext: {type: string, description: "File extension filter for search, e.g. .py"}
  glob: {type: string, description: "File name glob for search, e.g. '*.py'. Overrides ext."}
  case_sensitive: {type: boolean, description: "Match case in search. Default: false."}
  mode: {type: string, description: "For PDF/DOCX: 'text' (default) or 'visual' (render as image for vision models)"}
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
