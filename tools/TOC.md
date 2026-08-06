# Available Tools

## File I/O
- `read`: Read text, CSV, XLSX, PDF, DOCX, images, or search code — unified inspector.
- `write`: Create/overwrite text, CSV, XLSX, or formatted DOCX files.
- `edit`: Precise text/DOCX edits plus exact-cell CSV/XLSX replacement.
- `ls`: List directory contents with file sizes and types.

## Desktop
- `computer`: Observe and operate the Windows desktop with screenshots, window activation, mouse, and keyboard controls.

## Execution
- `bash`: Run bounded command-line programs in the project child environment (cmd.exe on Windows, bash elsewhere); use for git, rg/fd, tests, builds, installers, and system utilities.
- `python_executor`: Run bounded Python for calculations, structured data processing, and direct library APIs.
- `job`: Start and manage persistent background shell jobs in the same child environment. `start` means accepted/running, not completed. Actions: start, status, logs, list, cancel.
- `schedule`: Create persistent one-time or repeating scheduled agent turns. Scheduled turns can call normal tools such as `web_searcher`. Actions: create, list, cancel.

## Web
- `web_searcher`: Search the web via DuckDuckGo. Required: `query`.
- `web_reader`: Fetch a URL and extract text, links, tables, code, or headers.

## Project
- `project_test`: Optional project health checks for explicit user requests; never required after edits. Optional: `scope`.
- `system_cleaner`: Preview/clean system temp, Python cache, recycle bin. `dry_run=false` to delete.

## Meta
- `knowledge_base`: Search and manage local knowledge-base documents.
- `chat_exporter`: Export a session to Desktop as HTML, or list saved sessions. Empty `session_id` = current session.
- `image_generator`: Generate images via cloud API. Required: `prompt`.