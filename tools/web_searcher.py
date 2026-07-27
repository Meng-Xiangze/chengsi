from tools.base import BaseTool
import time

try:
    from ddgs import DDGS
    _PACKAGE_NAME = "ddgs"
except ImportError:
    try:
        from duckduckgo_search import DDGS
        _PACKAGE_NAME = "duckduckgo_search"
    except ImportError:
        DDGS = None
        _PACKAGE_NAME = None


class WebSearcher(BaseTool):
    @property
    def tool_name(self) -> str:
        return "web_searcher"

    @property
    def description(self) -> str:
        return "Searches the web using DuckDuckGo and returns top results with titles, snippets, and URLs."

    @property
    def parameters(self) -> dict:
        return {"query": {"type": "string", "description": "The query to search for on the internet."}}

    def run(self, arguments: dict) -> str:
        if DDGS is None:
            return "Error: web search dependency is not installed. Install it with: pip install ddgs"

        query = str(arguments.get("query", "")).strip()
        if not query:
            return "Error: No query provided."

        last_error = None
        for attempt in range(2):
            try:
                with DDGS() as ddgs:
                    results = list(ddgs.text(query, max_results=5) or [])

                valid = []
                for result in results:
                    if not isinstance(result, dict):
                        continue
                    title = str(result.get("title") or "No title").strip()
                    body = str(result.get("body") or result.get("snippet") or "No snippet").strip()
                    url = str(result.get("href") or result.get("url") or "").strip()
                    if title or body or url:
                        valid.append(f"Title: {title}\nSnippet: {body}\nURL: {url}")

                if valid:
                    return "\n\n".join(valid)
                return f"Search completed, but no results were found for query: '{query}'."
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.5)

        return f"Error during web search execution: {last_error}"
