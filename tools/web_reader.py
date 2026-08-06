# -*- coding: utf-8 -*-
from tools.base import BaseTool
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import json


class WebReader(BaseTool):
    @property
    def tool_name(self) -> str:
        return "web_reader"

    @property
    def description(self) -> str:
        return "Fetch and analyze web page content, extract text, links, metadata, and structured data"

    @property
    def parameters(self) -> dict:
        return {
            "url": {
                "type": "string",
                "description": "Target URL to fetch and analyze (required)"
            },
            "action": {
                "type": "string",
                "description": "Action type: 'read' (extract main text), 'analyze' (deep analysis with structure), 'extract' (specific elements). Default: read"
            },
            "element_type": {
                "type": "string",
                "description": "For extract action: 'table', 'code', 'links', 'images', 'list', 'headers'"
            },
            "selector": {
                "type": "string",
                "description": "Optional CSS selector for targeted extraction"
            },
            "timeout": {
                "type": "integer",
                "description": "Request timeout in seconds. Default: 10"
            },
            "offset": {
                "type": "integer",
                "description": "Character offset for read action pagination (1-indexed). When content is longer than the cap, use offset to continue reading the rest."
            },
            "limit": {
                "type": "integer",
                "description": "Max characters for read action. Default: 50000 (soft cap)."
            }
        }

    def run(self, arguments: dict) -> str:
        url = arguments.get("url")
        if not url:
            return json.dumps({"error": "URL is required"}, ensure_ascii=False, indent=2)

        action = arguments.get("action", "read")
        element_type = arguments.get("element_type")
        selector = arguments.get("selector")
        timeout = arguments.get("timeout", 10)
        try:
            offset = max(1, int(arguments.get("offset", 1) or 1))
        except (TypeError, ValueError):
            offset = 1
        try:
            limit = max(1000, int(arguments.get("limit", 50000) or 50000))
        except (TypeError, ValueError):
            limit = 50000

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            response.encoding = response.apparent_encoding

            soup = BeautifulSoup(response.text, 'html.parser')

            if action == "read":
                result = self._read_content(soup, url, offset, limit)
            elif action == "analyze":
                result = self._analyze_page(soup, url, response)
            elif action == "extract":
                result = self._extract_elements(soup, url, element_type, selector)
            else:
                result = {"error": f"Unknown action: {action}. Use 'read', 'analyze', or 'extract'"}

            return json.dumps(result, ensure_ascii=False, indent=2)

        except requests.exceptions.RequestException as e:
            return json.dumps({"error": f"Request failed: {str(e)}"}, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": f"Processing failed: {str(e)}"}, ensure_ascii=False, indent=2)

    def _read_content(self, soup, url, offset=1, limit=50000):
        """Extract main text content. Paginated via offset/limit (character-based).

        Ecosystem standard: the leading hint tells the model UP FRONT how long
        the page is and how to continue, so it pages through the whole
        conversation instead of assuming the first chunk is everything.
        """
        for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            element.decompose()

        title = soup.title.string if soup.title else "No title"

        main_content = soup.find('main') or soup.find('article') or soup.find('body')

        if main_content:
            text = main_content.get_text(separator='\n', strip=True)
            text = re.sub(r'\n\s*\n+', '\n\n', text)
        else:
            text = soup.get_text(separator='\n', strip=True)

        total = len(text)
        start = offset - 1
        chunk = text[start:start + limit]
        remaining = total - (start + len(chunk))

        hint_lines = [f"📄 {url}", f"Title: {title}"]
        if total > limit or offset > 1:
            hint_lines.append(
                f"⚠️  Page content is {total:,} chars; showing chars {offset:,}-{start + len(chunk):,}."
            )
            if remaining > 0:
                hint_lines.append(
                    f"⏩  Content continues! Read the rest with offset={start + len(chunk) + 1} "
                    f"({remaining:,} chars remaining) before judging the task."
                )
            else:
                hint_lines.append("✅ End of content reached.")
        hint_lines.append(f"Full page length: {total:,} chars.")

        return {
            "url": url,
            "title": title,
            "content": "\n".join(hint_lines) + "\n\n" + chunk,
            "content_length": total,
            "chars_shown": len(chunk),
            "offset": offset,
            "truncated": remaining > 0,
            "next_offset": (start + len(chunk) + 1) if remaining > 0 else None
        }

    def _analyze_page(self, soup, url, response):
        """Deep analysis of page structure."""
        meta_tags = {}
        for meta in soup.find_all('meta'):
            name = meta.get('name') or meta.get('property', '')
            content = meta.get('content', '')
            if name and content:
                meta_tags[name] = content

        headers = {}
        for i in range(1, 7):
            h_tags = soup.find_all(f'h{i}')
            if h_tags:
                headers[f'h{i}'] = [h.get_text(strip=True) for h in h_tags[:20]]

        links = []
        for a in soup.find_all('a', href=True)[:50]:
            href = urljoin(url, a['href'])
            text = a.get_text(strip=True)
            links.append({"text": text, "url": href})

        images = []
        for img in soup.find_all('img')[:20]:
            src = img.get('src', '')
            if src:
                src = urljoin(url, src)
                alt = img.get('alt', '')
                images.append({"src": src, "alt": alt})

        main_tags = ['header', 'nav', 'main', 'article', 'aside', 'footer', 'section']
        structure = {tag: len(soup.find_all(tag)) for tag in main_tags}

        return {
            "url": url,
            "title": soup.title.string if soup.title else "No title",
            "status_code": response.status_code,
            "content_type": response.headers.get('content-type', ''),
            "metadata": meta_tags,
            "headers": headers,
            "links_count": len(soup.find_all('a', href=True)),
            "links_sample": links,
            "images_count": len(soup.find_all('img')),
            "images_sample": images,
            "structure": structure,
            "has_forms": len(soup.find_all('form')) > 0,
            "has_tables": len(soup.find_all('table')) > 0,
            "has_code_blocks": len(soup.find_all(['code', 'pre'])) > 0
        }

    def _extract_elements(self, soup, url, element_type, selector):
        """Extract specific elements from page."""
        result = {"url": url, "element_type": element_type}

        if selector:
            elements = soup.select(selector)
            result["elements"] = [el.get_text(strip=True) for el in elements[:50]]
            result["count"] = len(elements)
            return result

        if element_type == "table":
            tables = []
            for table in soup.find_all('table')[:10]:
                rows = []
                for tr in table.find_all('tr')[:100]:
                    cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
                    if cells:
                        rows.append(cells)
                tables.append(rows)
            result["tables"] = tables
            result["count"] = len(tables)

        elif element_type == "code":
            code_blocks = []
            for code in soup.find_all(['code', 'pre'])[:30]:
                code_blocks.append({
                    "tag": code.name,
                    "content": code.get_text()[:1000],
                    "class": ' '.join(code.get('class', []))
                })
            result["code_blocks"] = code_blocks
            result["count"] = len(code_blocks)

        elif element_type == "links":
            links = []
            for a in soup.find_all('a', href=True):
                links.append({
                    "text": a.get_text(strip=True),
                    "url": urljoin(url, a['href']),
                    "title": a.get('title', '')
                })
            result["links"] = links
            result["count"] = len(links)

        elif element_type == "images":
            images = []
            for img in soup.find_all('img'):
                images.append({
                    "src": urljoin(url, img.get('src', '')),
                    "alt": img.get('alt', ''),
                    "title": img.get('title', '')
                })
            result["images"] = images
            result["count"] = len(images)

        elif element_type == "list":
            lists = []
            for ul in soup.find_all(['ul', 'ol'])[:20]:
                items = [li.get_text(strip=True) for li in ul.find_all('li', recursive=False)]
                lists.append({
                    "type": ul.name,
                    "items": items
                })
            result["lists"] = lists
            result["count"] = len(lists)

        elif element_type == "headers":
            headers = {}
            for i in range(1, 7):
                h_tags = soup.find_all(f'h{i}')
                if h_tags:
                    headers[f'h{i}'] = [h.get_text(strip=True) for h in h_tags]
            result["headers"] = headers

        else:
            result["error"] = f"Unknown element_type: {element_type}. Use: table, code, links, images, list, headers"

        return result