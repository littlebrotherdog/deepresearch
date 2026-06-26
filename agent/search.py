"""Multi-engine search module - Baidu / Google / Google Scholar / arXiv."""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from config import SearchConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
BAIDU_SEARCH_URL = "https://www.baidu.com/s"
BAIDU_SEARCH_URL_HTTP = "http://www.baidu.com/s"
GOOGLE_SEARCH_URL = "https://www.google.com/search"
SCHOLAR_SEARCH_URL = "https://scholar.google.com/scholar"
ARXIV_API_URL = "http://export.arxiv.org/api/query"

# Rotating User-Agent pool to reduce blocking
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    content: str = ""  # full page content (fetched separately)
    engine: str = ""   # source engine: "baidu" | "google" | "scholar" | "arxiv"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _get_headers() -> dict:
    import random
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }


def _get_proxies(config: SearchConfig | None = None) -> dict | None:
    if config and config.proxy:
        return {"http": config.proxy, "https": config.proxy}
    return None


# ---------------------------------------------------------------------------
# Baidu search
# ---------------------------------------------------------------------------
def search_baidu(query: str, config: SearchConfig | None = None) -> list[SearchResult]:
    """Search Baidu and return parsed results."""
    if config is None:
        config = SearchConfig()

    results: list[SearchResult] = []
    search_url = BAIDU_SEARCH_URL if config.use_https else BAIDU_SEARCH_URL_HTTP

    try:
        params = {"wd": query, "rn": str(config.max_results_per_query), "ie": "utf-8"}
        resp = requests.get(
            search_url,
            params=params,
            headers=_get_headers(),
            timeout=config.fetch_timeout,
            proxies=_get_proxies(config),
            allow_redirects=True,
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        # Baidu organic results are in div.result / div.c-container
        for item in soup.select("div.result, div.c-container"):
            title_tag = item.select_one("h3 a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            url = title_tag.get("href", "")

            # Snippet: look for span.content-right_8Zs40 or generic text
            snippet = ""
            snippet_tag = item.select_one(
                "span.content-right_8Zs40, div.c-abstract, span.c-font-normal"
            )
            if snippet_tag:
                snippet = snippet_tag.get_text(strip=True)
            if not snippet:
                # fallback: grab longest text block
                texts = [t.get_text(strip=True) for t in item.find_all(string=False) if t.name]
                snippet = max(texts, key=len) if texts else ""

            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet, engine="baidu"))

            if len(results) >= config.max_results_per_query:
                break

    except Exception as e:
        logger.error(f"Baidu search failed for '{query}': {e}")

    return results


# ---------------------------------------------------------------------------
# Google search
# ---------------------------------------------------------------------------
def search_google(query: str, config: SearchConfig | None = None) -> list[SearchResult]:
    """Search Google and return parsed results."""
    if config is None:
        config = SearchConfig()

    results: list[SearchResult] = []

    try:
        params = {
            "q": query,
            "num": str(config.max_results_per_query),
            "hl": "zh-CN",
        }
        resp = requests.get(
            GOOGLE_SEARCH_URL,
            params=params,
            headers=_get_headers(),
            timeout=config.fetch_timeout,
            proxies=_get_proxies(config),
            allow_redirects=True,
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        for item in soup.select("div.g"):
            title_tag = item.select_one("h3")
            link_tag = item.select_one("a[href]")
            if not title_tag or not link_tag:
                continue

            title = title_tag.get_text(strip=True)
            url = link_tag.get("href", "")

            # Skip non-http links (like search anchors)
            if not url.startswith("http"):
                continue

            # Snippet
            snippet = ""
            snippet_tag = item.select_one("div.VwiC3b, span.aCOpRe, div.IsZvec")
            if snippet_tag:
                snippet = snippet_tag.get_text(strip=True)

            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet, engine="google"))

            if len(results) >= config.max_results_per_query:
                break

    except Exception as e:
        logger.error(f"Google search failed for '{query}': {e}")

    return results


# ---------------------------------------------------------------------------
# Google Scholar search
# ---------------------------------------------------------------------------
def search_scholar(query: str, config: SearchConfig | None = None) -> list[SearchResult]:
    """Search Google Scholar and return parsed results."""
    if config is None:
        config = SearchConfig()

    results: list[SearchResult] = []

    try:
        params = {
            "q": query,
            "num": str(min(config.max_results_per_query, 10)),  # Scholar max is 10
            "hl": "zh-CN",
        }
        resp = requests.get(
            SCHOLAR_SEARCH_URL,
            params=params,
            headers=_get_headers(),
            timeout=config.fetch_timeout,
            proxies=_get_proxies(config),
            allow_redirects=True,
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        for item in soup.select("div.gs_r.gs_or.gs_scl, div.gs_r.gs_or"):
            title_tag = item.select_one("h3.gs_rt a")
            if not title_tag:
                # Could be [PDF] or [CITATION] without link
                title_tag = item.select_one("h3.gs_rt .gs_ctc, h3.gs_rt")
                if title_tag:
                    title = title_tag.get_text(strip=True)
                    url = ""
                else:
                    continue
            else:
                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")

            # Snippet
            snippet = ""
            snippet_tag = item.select_one("div.gs_rs")
            if snippet_tag:
                snippet = snippet_tag.get_text(strip=True)

            # Citation count
            cited_count = ""
            cited_tag = item.select_one("div.gs_fl a")
            if cited_tag:
                m = re.search(r"(\d+)", cited_tag.get_text())
                if m:
                    cited_count = f"[被引{m.group(1)}次] "

            if snippet and cited_count:
                snippet = cited_count + snippet

            # Try to get PDF link if no article link
            if not url:
                pdf_tag = item.select_one("div.gs_or_ggsm a[href]")
                if pdf_tag:
                    url = pdf_tag.get("href", "")

            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet, engine="scholar"))

            if len(results) >= config.max_results_per_query:
                break

    except Exception as e:
        logger.error(f"Scholar search failed for '{query}': {e}")

    return results


# ---------------------------------------------------------------------------
# arXiv search (via API)
# ---------------------------------------------------------------------------
def search_arxiv(query: str, config: SearchConfig | None = None) -> list[SearchResult]:
    """Search arXiv via the public API and return parsed results."""
    if config is None:
        config = SearchConfig()

    results: list[SearchResult] = []

    try:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": config.max_results_per_query,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        resp = requests.get(
            ARXIV_API_URL,
            params=params,
            timeout=max(config.fetch_timeout, 30),  # arXiv API can be slow
            proxies=_get_proxies(config),
        )
        resp.encoding = "utf-8"

        soup = BeautifulSoup(resp.text, "lxml-xml")
        # Atom namespace
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in soup.find_all("entry"):
            title_tag = entry.find("title")
            id_tag = entry.find("id")
            summary_tag = entry.find("summary")
            published_tag = entry.find("published")

            if not title_tag or not id_tag:
                continue

            title = title_tag.get_text(strip=True).replace("\n", " ")
            # arXiv ID URL -> abstract page URL
            url = id_tag.get_text(strip=True).replace("http://", "https://")

            # Summary as snippet
            snippet = ""
            if summary_tag:
                snippet = summary_tag.get_text(strip=True).replace("\n", " ")[:300]

            # Add publish date to snippet
            if published_tag:
                pub_date = published_tag.get_text(strip=True)[:10]
                snippet = f"[{pub_date}] {snippet}"

            # Full abstract as content (no need to fetch page)
            content = ""
            if summary_tag:
                content = summary_tag.get_text(strip=True)[:config.max_content_length]

            if title and url:
                results.append(SearchResult(
                    title=title, url=url, snippet=snippet,
                    content=content, engine="arxiv",
                ))

            if len(results) >= config.max_results_per_query:
                break

    except Exception as e:
        logger.error(f"arXiv search failed for '{query}': {e}")

    return results


# ---------------------------------------------------------------------------
# Multi-engine search
# ---------------------------------------------------------------------------
def search_multi(query: str, config: SearchConfig | None = None) -> list[SearchResult]:
    """Search across multiple engines in parallel and merge deduplicated results."""
    if config is None:
        config = SearchConfig()

    all_results: list[SearchResult] = []
    seen_urls: set[str] = set()

    engine_map = {
        "baidu": search_baidu,
        "google": search_google,
        "scholar": search_scholar,
        "arxiv": search_arxiv,
    }

    # Collect valid engines
    tasks: list[tuple[str, callable]] = []
    for engine_name in config.engines:
        engine_name = engine_name.strip().lower()
        search_fn = engine_map.get(engine_name)
        if not search_fn:
            logger.warning(f"Unknown search engine: {engine_name}")
            continue
        tasks.append((engine_name, search_fn))

    # Parallel execution across engines
    with ThreadPoolExecutor(max_workers=len(tasks) or 1) as pool:
        future_to_name = {
            pool.submit(fn, query, config): name
            for name, fn in tasks
        }
        for future in as_completed(future_to_name):
            engine_name = future_to_name[future]
            try:
                results = future.result()
                logger.info(f"{engine_name} returned {len(results)} results for '{query}'")
                for r in results:
                    if r.url and r.url not in seen_urls:
                        seen_urls.add(r.url)
                        all_results.append(r)
            except Exception as e:
                logger.warning(f"{engine_name} search failed for '{query}': {e}")

    return all_results


# ---------------------------------------------------------------------------
# Fetch page content (shared by Baidu/Google/Scholar)
# ---------------------------------------------------------------------------
def fetch_page_content(url: str, config: SearchConfig | None = None) -> str:
    """Fetch and extract text content from a URL."""
    if config is None:
        config = SearchConfig()

    try:
        # Baidu redirect URLs need to be resolved first
        if "baidu.com/link" in url:
            resp = requests.head(url, headers=_get_headers(), timeout=config.fetch_timeout, allow_redirects=True, proxies=_get_proxies(config))
            url = resp.url

        resp = requests.get(url, headers=_get_headers(), timeout=config.fetch_timeout, proxies=_get_proxies(config))
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        # Remove script/style/nav elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        # Try article/main/body in order
        for selector in ["article", "main", "#content", ".content", "#article", ".article", "body"]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    return text[: config.max_content_length]

        text = soup.get_text(separator="\n", strip=True)
        return text[: config.max_content_length]
    except Exception as e:
        logger.debug(f"Failed to fetch {url}: {e}")
        return ""


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------
def search_and_fetch(query: str, config: SearchConfig | None = None) -> list[SearchResult]:
    """Search across configured engines and optionally fetch full page content."""
    if config is None:
        config = SearchConfig()

    results = search_multi(query, config)

    if not config.snippet_only:
        for r in results:
            # arXiv results already have content from the API
            if r.engine == "arxiv" and r.content:
                continue
            r.content = fetch_page_content(r.url, config)
            time.sleep(0.3)  # gentle delay

    return results
