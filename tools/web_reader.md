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
examples: []
usage_notes: []
---

# web_reader

Fetch and analyze web page content, extract text, links, metadata, and structured data

(Auto-generated. Edit this file to add parameters, examples, and usage notes.)
