from tools.base import BaseTool
from core.process_utils import optional_import
import time
import urllib.parse


# CN network: DuckDuckGo is unreachable (21s timeouts). Give DDG a short
# budget, then fall back to a Bing/360 search URL the model can open with
# web_reader, or a clear hint to use another search route.
_DDG_TIMEOUT_S = 8


def _get_ddgs():
    """Lazy-import DDGS with optional auto-install."""
    for module_name in ("ddgs", "duckduckgo_search"):
        try:
            mod = optional_import(module_name)
            return getattr(mod, "DDGS")
        except ImportError:
            continue
    return None


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
        query = str(arguments.get("query", "")).strip()
        if not query:
            return "Error: No query provided."

        # Quick reachability probe: if DDG isn't importable, skip straight to fallback.
        DDGS = _get_ddgs()
        if DDGS is None:
            return self._fallback(query, "web search dependency is not installed (pip install ddgs)")

        last_error = None
        for attempt in range(2):
            try:
                with DDGS(timeout=_DDG_TIMEOUT_S) as ddgs:
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

        return self._fallback(query, last_error)

    @staticmethod
    def _fallback(query: str, reason) -> str:
        """DDG unreachable (CN network) — hand the model a reachable search URL."""
        bing = "https://www.bing.com/search?q=" + urllib.parse.quote(query)
        baidu = "https://www.baidu.com/s?wd=" + urllib.parse.quote(query)
        return (
            f"⚠️  DuckDuckGo search failed in this network ({reason}).\n"
            f"Bing/Baidu are reachable — open one with web_reader:\n"
            f"  bing:  {bing}\n"
            f"  baidu: {baidu}\n"
            f"Or retry the query with different wording."
        )
