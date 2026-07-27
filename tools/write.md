---
name: write
description: "Create or overwrite files — raw text or formatted DOCX"
parameters:
  path: {type: string, description: "File path (auto-creates parent dirs)"}
  content: {type: string, description: "File content (Markdown-like for DOCX)"}
examples:
  - {path: script.py, content: "print('hello')"}
  - {path: report.docx, content: "# Title ## Section {size:14,bold}Big bold text{/size} **bold** *italic* H_2_O - bullet 1. numbered |Name|Value| |Q|9B| ![](chart.png)"}
usage_notes:
  - "Text files: raw content written verbatim (UTF-8)."
  - "DOCX: Markdown-like → formatted .docx with Times New Roman 12pt default."
  - "Inline markers: **bold** *italic* ^superscript^ _subscript_"
  - "Style spans: {size:N}...{/size} {color:red}...{/color} {size:18,bold,color:blue}..."
  - "Boolean flags: bold, italic — e.g. {size:14,bold} or {size:14,**bold**}"
  - "Blocks: #Heading, -bullet, 1.numbered, |table|, ![](image)"
  - "Images: absolute path or relative to cwd/Desktop."
  - "Overwrites existing files without confirmation."
---

# write

Creates or overwrites a file.

## Text mode (all extensions except .docx)

Raw content written directly, UTF-8.

## DOCX mode

Markdown-like syntax → fully formatted Word document.

### Inline formatting

| Input | Output |
|-------|--------|
| `**bold**` | **Bold** text |
| `*italic*` | *Italic* text |
| `^text^` | Superscript |
| `_text_` | Subscript |
| `{size:18}text{/size}` | 18pt font |
| `{color:red}text{/color}` | Red text |
| `{color:#FF0000}text{/color}` | Hex color |
| `{size:16,bold,color:blue}text{/size}` | Combined |

### Block elements

| Input | Output |
|-------|--------|
| `# Title` | Heading 1 (18pt) |
| `## Section` | Heading 2 (14pt) |
| `- item` | Bullet list |
| `1. item` | Numbered list |
| `\| H1 \| H2 \|` | Table (first row = bold header) |
| `\| R1 \| R2 \|` | Subsequent table rows |
| `![](diagram.png)` | Embedded image (4.5" wide) |
| `![caption](diagram.png)` | Image + caption paragraph |
