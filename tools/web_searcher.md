---
name: web_searcher
description: Search the web using DuckDuckGo and return top results with titles and snippets.
parameters:
  query:
    type: string
    description: The search query to look up on the internet.
examples:
  - action: web_searcher
    arguments:
      query: "latest AI developments 2026"
usage_notes:
  - Requires the ddgs package (install with: pip install ddgs).
  - Returns up to 5 results by default.
  - Results include title, snippet, and URL for each hit.
---

# web_searcher

Searches the web via DuckDuckGo and returns a list of results with titles and snippets.

## Parameters

| Name | Type | Description |
|------|------|-------------|
| `query` | string | The search query |

## Notes

- Max 5 results per query.
- If `duckduckgo_search` is not installed, the tool will ask you to install it via `python_executor`.
