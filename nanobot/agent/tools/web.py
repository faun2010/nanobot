"""Web tools: web_search, online_search, and web_fetch."""

import html
import json
import os
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from nanobot.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


def _decode_duckduckgo_url(url: str) -> str:
    """Decode DuckDuckGo redirect URLs into their original target URL."""
    if url.startswith("//"):
        url = f"https:{url}"

    try:
        parsed = urlparse(url)
        if "duckduckgo.com" in parsed.netloc and parsed.path == "/l/":
            target = parse_qs(parsed.query).get("uddg", [None])[0]
            if target:
                return unquote(target)
    except Exception:
        return url

    return url


def _extract_duckduckgo_results(html_text: str, limit: int) -> list[dict[str, str]]:
    """Extract search results from DuckDuckGo HTML response."""
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    title_patterns = (
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>[\s\S]*?)</a>',
        r'<a[^>]+class="[^"]*result-link[^"]*"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>[\s\S]*?)</a>',
    )

    for pattern in title_patterns:
        for match in re.finditer(pattern, html_text, flags=re.I):
            title = _normalize(_strip_tags(match.group("title")))
            url = _decode_duckduckgo_url(html.unescape(match.group("url")))
            if not title or not url or url in seen_urls:
                continue
            results.append({"title": title, "url": url})
            seen_urls.add(url)
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    snippet_matches = re.findall(
        r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)</a>',
        html_text,
        flags=re.I,
    )
    for i, snippet_html in enumerate(snippet_matches[: len(results)]):
        snippet = _normalize(_strip_tags(snippet_html))
        if snippet:
            results[i]["snippet"] = snippet

    return results[:limit]


def _normalize_site_filter(site: str) -> str | None:
    """Normalize site filter into a safe host-like token."""
    raw = (site or "").strip()
    if not raw:
        return None

    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.netloc
    else:
        parsed = urlparse(f"https://{raw}")
        host = parsed.netloc

    host = host.lower().strip().strip(".")
    if ":" in host:
        host = host.split(":", 1)[0]
    if not host:
        return None
    if ".." in host or host.startswith("-") or host.endswith("-"):
        return None
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        return None
    return host


def _compose_online_search_query(query: str, site: str | None = None) -> str:
    """Compose final search query with optional site restriction."""
    q = query.strip()
    if site:
        return f"site:{site} {q}"
    return q


def _map_recency_to_ddg_df(recency: str | None) -> str | None:
    """Map recency option to DuckDuckGo `df` parameter."""
    mapping = {
        "day": "d",
        "week": "w",
        "month": "m",
        "year": "y",
    }
    if not recency:
        return None
    return mapping.get(recency)


class WebSearchTool(Tool):
    """Search the web using Brave Search API."""
    
    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {"type": "integer", "description": "Results (1-10)", "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }
    
    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self.max_results = max_results
    
    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            return "Error: BRAVE_API_KEY not configured"
        
        try:
            n = min(max(count or self.max_results, 1), 10)
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                    timeout=10.0
                )
                r.raise_for_status()
            
            results = r.json().get("web", {}).get("results", [])
            if not results:
                return f"No results for: {query}"
            
            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"


class OnlineSearchTool(Tool):
    """Search the web via DuckDuckGo HTML (no API key required)."""

    name = "online_search"
    description = "Search the web online without API keys. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query", "minLength": 1},
            "count": {"type": "integer", "description": "Results (1-10)", "minimum": 1, "maximum": 10},
            "site": {"type": "string", "description": "Optional site filter, e.g. docs.python.org"},
            "recency": {
                "type": "string",
                "description": "Optional time filter",
                "enum": ["day", "week", "month", "year"],
            },
        },
        "required": ["query"],
    }

    def __init__(self, max_results: int = 5):
        self.max_results = max_results

    async def execute(
        self,
        query: str,
        count: int | None = None,
        site: str | None = None,
        recency: str | None = None,
        **kwargs: Any,
    ) -> str:
        n = min(max(count or self.max_results, 1), 10)
        normalized_site = _normalize_site_filter(site) if site else None
        if site and not normalized_site:
            return f"Error: Invalid site filter '{site}'"
        final_query = _compose_online_search_query(query, normalized_site)
        params: dict[str, str] = {"q": final_query}
        df = _map_recency_to_ddg_df(recency)
        if df:
            params["df"] = df

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=10.0,
            ) as client:
                response = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params=params,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                )
                response.raise_for_status()

            results = _extract_duckduckgo_results(response.text, n)
            if not results:
                return f"No results for: {final_query}"

            lines = [f"Results for: {final_query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if snippet := item.get("snippet"):
                    lines.append(f"   {snippet}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Readability."""
    
    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
    }
    
    def __init__(self, max_chars: int = 50000):
        self.max_chars = max_chars
    
    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        from readability import Document

        max_chars = maxChars or self.max_chars

        # Validate URL before fetching
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url})

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
            
            ctype = r.headers.get("content-type", "")
            
            # JSON
            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2), "json"
            # HTML
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                doc = Document(r.text)
                content = self._to_markdown(doc.summary()) if extractMode == "markdown" else _strip_tags(doc.summary())
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                text, extractor = r.text, "raw"
            
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]
            
            return json.dumps({"url": url, "finalUrl": str(r.url), "status": r.status_code,
                              "extractor": extractor, "truncated": truncated, "length": len(text), "text": text})
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})
    
    def _to_markdown(self, html: str) -> str:
        """Convert HTML to markdown."""
        # Convert links, headings, lists before stripping tags
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return _normalize(_strip_tags(text))
