---
name: ls
description: "List directory contents with file sizes and types"
parameters:
  path: {type: string, description: "Directory path. Default: current working directory."}
examples:
  - {path: "."}
  - {path: "C:/Users/MengX/Desktop"}
usage_notes:
  - "Hidden files (starting with .) are excluded."
  - "Directories show item count, files show size."
  - "Sorts directories first, then files (alphabetical)."
---

# ls

List directory contents.

```
📂 D:\Chengsi-v0.2.0\tools
  📁 __pycache__/  (21 items)

  🐍 base.py  (2 KB)
  📝 read.md  (1 KB)
  🐍 read.py  (25 KB)
  ...
```

- 📁 = directory (with item count)
- 🐍 = Python, 📝 = Markdown, 🖼️ = Image, 📕 = PDF, 📘 = DOCX, etc.
