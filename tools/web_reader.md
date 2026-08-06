---
name: web_reader
description: "Fetch and analyze web page content, extract text, links, metadata, and structured data"
parameters:
  url:
    type: string
    description: HTTP/HTTPS URL to fetch
    required: true
  action:
    type: string
    enum: [read, analyze, extract]
    description: "read | analyze | extract"
    default: read
  element_type:
    type: string
    enum: [table, code, links, images, list, headers]
    description: Element type (table/code/links/images/list/headers)
  selector:
    type: string
    description: CSS selector for extract
  timeout:
    type: integer
    description: Request timeout seconds (default 10)
  offset:
    type: integer
    description: Character offset for read pagination (1-indexed). Continue with this when content shows ⏩ remaining.
  limit:
    type: integer
    description: Max chars for read (default 50000, min 1000)
examples: []
usage_notes:
  - "Long pages: when content begins with ⏩ Content continues!, keep calling read with offset=next_offset until you see ✅ End of content reached. — never judge a task from only the first chunk."
  - "SPA/JS-heavy sites may return little text; consider web_searcher or a mobile/AMP URL instead."
---

# web_reader

Fetch and analyze web page content, extract text, links, metadata, and structured data

(Auto-generated. Edit this file to add parameters, examples, and usage notes.)
