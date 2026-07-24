---
name: web_search_read
description: "Search the web and optionally fetch full content from result URLs"
parameters:
  query:
    type: string
    description: Search query.
    required: true
  read_top_n:
    type: integer
    description: Number of top result pages to fetch; 0 returns snippets only.
    default: 0
  max_chars:
    type: integer
    description: Maximum characters returned per fetched page.
    default: 3000
  timeout:
    type: integer
    description: HTTP timeout in seconds for page fetches.
    default: 10
examples:
  - action: web_search_read
    arguments:
      query: "Python 3.14 release notes"
      read_top_n: 2
usage_notes:
  - Use read_top_n=0 when snippets are sufficient.
  - Use read_top_n=1 or 2 when the answer needs page content.
---

# web_search_read

Search the web and optionally fetch full content from result URLs

(Auto-generated. Edit this file to add parameters, examples, and usage notes.)
