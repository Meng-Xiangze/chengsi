# -*- coding: utf-8 -*-
from tools.base import BaseTool
import time
import json
import requests
from bs4 import BeautifulSoup
import re

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None


class WebSearchRead(BaseTool):
    @property
    def tool_name(self) -> str:
        return "web_search_read"

    @property
    def description(self) -> str:
        return (
            "Search the web via DuckDuckGo, then optionally fetch full page content "
            "from one or more result URLs. Use this when snippets are not enough and "
            "you need the actual page text."
        )

    @property
    def parameters(self) -> dict:
        return {
            "query": {
                "type": "string",
                "description": "Search query (required)"
            },
            "read_top_n": {
                "type": "integer",
                "description": (
                    "How many top result URLs to fully read after searching. "
                    "0 = search only (return snippets). Default: 0"
                )
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters to return per page when reading. Default: 3000"
            },
            "timeout": {
                "type": "integer",
                "description": "HTTP timeout in seconds for page fetches. Default: 10"
            }
        }

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _search(self, query: str) -> list[dict]:
        """Run DuckDuckGo search, return list of {title, snippet, url}."""
        if DDGS is None:
            return []
        last_err = None
        for attempt in range(2):
            try:
                with DDGS() as ddgs:
                    raw = list(ddgs.text(query, max_results=5) or [])
                results = []
                for r in raw:
                    if not isinstance(r, dict):
                        continue
                    results.append({
                        "title":   str(r.get("title") or "").strip(),
                        "snippet": str(r.get("body") or r.get("snippet") or "").strip(),
                        "url":     str(r.get("href") or r.get("url") or "").strip(),
                    })
                return results
            except Exception as exc:
                last_err = exc
                if attempt == 0:
                    time.sleep(0.5)
        return []

    def _fetch_text(self, url: str, max_chars: int, timeout: int) -> str:
        """Fetch a URL and return clean plain text up to max_chars."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove noise tags
            for tag in soup(["script", "style", "nav", "footer",
                              "header", "aside", "form", "noscript"]):
                tag.decompose()

            # Try to find main content
            main = (
                soup.find("article") or
                soup.find("main") or
                soup.find(id=re.compile(r"content|main|article", re.I)) or
                soup.find(class_=re.compile(r"content|main|article|post", re.I)) or
                soup.body or
                soup
            )
            text = main.get_text(separator="\n", strip=True)
            # Collapse blank lines
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text[:max_chars]
        except Exception as exc:
            return f"[Error fetching {url}: {exc}]"

    # ------------------------------------------------------------------ #
    #  Main entry                                                          #
    # ------------------------------------------------------------------ #

    def run(self, arguments: dict) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return "Error: query is required."

        if DDGS is None:
            return "Error: search dependency not installed. Run: pip install ddgs"

        read_top_n = int(arguments.get("read_top_n", 0))
        max_chars  = int(arguments.get("max_chars", 3000))
        timeout    = int(arguments.get("timeout", 10))

        results = self._search(query)
        if not results:
            return f"No results found for: {query}"

        output_parts = []

        for i, r in enumerate(results):
            block = (
                f"[{i+1}] {r['title']}\n"
                f"URL: {r['url']}\n"
                f"Snippet: {r['snippet']}"
            )
            # Fetch full content for top-n results
            if i < read_top_n and r["url"]:
                page_text = self._fetch_text(r["url"], max_chars, timeout)
                block += f"\n--- Full Content ---\n{page_text}\n--- End ---"
            output_parts.append(block)

        return "\n\n".join(output_parts)