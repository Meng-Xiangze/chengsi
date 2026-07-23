# Available Tools

Use the tool directly when the request is clear. Call `tool_info` only when full details are needed.

- `python_executor`: Run Python for OS operations, diagnostics, calculations, and package installation. Required argument: `code`.
- `web_searcher`: Search the web. Required argument: `query`.
- `code_editor`: Read or modify project files. Required argument: `path`; use `action` to choose read/write/edit/search.
- `code_context`: Search project source files. Required argument: `query`.
- `project_test`: Check project health. Optional `scope`: syntax, imports, config, all.
- `image_reader`: Inspect an image file. Required argument: `path`.
- `chat_exporter`: Export a session as Markdown. Empty `session_id` means the current session.
- `system_cleaner`: Preview cleanup targets by default. Required `target_type`; deletion requires `dry_run=false`.
- `tool_info`: Read full documentation. Required argument: `tool_name`.
- `tool_creator`: Create or manage tools. Use only when explicitly requested.
- `knowledge_base`: Search and explicitly ingest, list, or remove local knowledge-base documents.
