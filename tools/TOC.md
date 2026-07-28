# Available Tools

## File I/O
- `read`: Read text, CSV, XLSX, PDF, DOCX, images, or search code — unified inspector.
- `write`: Create/overwrite text, CSV, XLSX, or formatted DOCX files.
- `edit`: Precise text/DOCX edits plus exact-cell CSV/XLSX replacement.
- `ls`: List directory contents with file sizes and types.

## Execution
- `bash`: Run a shell command. Required: `command`. 60s timeout.
- `python_executor`: Run Python code for calculations, file I/O, OS operations. Required: `code`.

## Web
- `web_searcher`: Search the web via DuckDuckGo. Required: `query`.
- `web_reader`: Fetch a URL and extract text, links, tables, code, or headers.

## Project
- `project_test`: Check project health — syntax, imports, config, unittest. Optional: `scope`.
- `system_cleaner`: Preview/clean system temp, Python cache, recycle bin. `dry_run=false` to delete.

## Meta
- `knowledge_base`: Search and manage local knowledge-base documents.
- `chat_exporter`: Export a session as Markdown. Empty `session_id` = current session.
- `image_generator`: Generate images via cloud API. Required: `prompt`.
