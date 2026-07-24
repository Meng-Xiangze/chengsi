---
name: web_reader
description: "Fetch and analyze web page content, extract text, links, metadata, and structured data"
parameters:
  url:
    type: string
    description: HTTP or HTTPS URL to fetch.
    required: true
  action:
    type: string
    enum: [read, analyze, extract]
    description: read for main text, analyze for page structure, extract for selected elements.
    default: read
  element_type:
    type: string
    enum: [table, code, links, images, list, headers]
    description: Element type for extract.
  selector:
    type: string
    description: Optional CSS selector for extract.
  timeout:
    type: integer
    description: Request timeout in seconds.
    default: 10
examples: []
usage_notes: []
---

# web_reader

Fetch and analyze web page content, extract text, links, metadata, and structured data

(Auto-generated. Edit this file to add parameters, examples, and usage notes.)
