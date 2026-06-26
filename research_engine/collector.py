from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from research_engine.models import ResearchSource, SourceType

logger = logging.getLogger("research.collector")


class ResearchCollector:
    """Collects research data from multiple sources."""

    def __init__(self, max_concurrent: int = 5):
        self._client = httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            headers={"User-Agent": "ResearchEngine/1.0 (Academic Research Agent)"},
        )
        self._sem = asyncio.Semaphore(max_concurrent)

    async def close(self):
        await self._client.aclose()

    async def search_web(self, query: str, max_results: int = 10) -> List[ResearchSource]:
        """Search web via a public academic search endpoint."""
        import urllib.parse as up
        sources = []
        encoded = up.quote(query)
        urls = [
            f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1",
            f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded}&format=json&srlimit={min(max_results, 50)}",
        ]
        for url in urls:
            try:
                async with self._sem:
                    resp = await self._client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    parsed = self._parse_search_response(url, data, query)
                    sources.extend(parsed[:max_results])
            except Exception as e:
                logger.debug("Search failed for %s: %s", url, e)
        return sources

    async def search_arxiv(self, query: str, max_results: int = 20) -> List[ResearchSource]:
        """Search arXiv API for academic papers."""
        search_q = "+AND+".join(
            f"all:{urllib.parse.quote(t.strip(), safe='')}"
            for t in query.split() if t.strip()
        )
        url = (
            f"http://export.arxiv.org/api/query?search_query={search_q}"
            f"&start=0&max_results={min(max_results, 100)}"
            f"&sortBy=relevance&sortOrder=descending"
        )
        try:
            async with self._sem:
                resp = await self._client.get(url)
            if resp.status_code == 200:
                return self._parse_arxiv_response(resp.text)
        except Exception as e:
            logger.debug("arXiv search failed: %s", e)
        return []

    async def fetch_url(self, url: str) -> Optional[str]:
        """Fetch raw content from a URL."""
        try:
            async with self._sem:
                resp = await self._client.get(url)
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            logger.debug("Failed to fetch %s: %s", url, e)
        return None

    async def collect_topic(self, topic: str, max_per_source: int = 10) -> List[ResearchSource]:
        """Collect sources for a topic from all available sources."""
        tasks = [
            self.search_arxiv(topic, max_per_source),
            self.search_web(topic, max_per_source),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        sources = []
        seen_urls = set()
        for batch in results:
            if isinstance(batch, list):
                for src in batch:
                    if src.url not in seen_urls:
                        seen_urls.add(src.url)
                        sources.append(src)
        return sources

    def _parse_arxiv_response(self, xml_text: str) -> List[ResearchSource]:
        sources = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("a:entry", ns):
                title = entry.findtext("a:title", "", ns).strip().replace("\n", " ")
                summary = entry.findtext("a:summary", "", ns).strip().replace("\n", " ")
                link_el = entry.find("a:link", ns)
                url = link_el.get("href", "") if link_el is not None else ""
                published = entry.findtext("a:published", "", ns)[:10]
                doi = self._extract_doi(summary) or self._extract_doi(url)
                authors = []
                for author in entry.findall("a:author", ns):
                    name = author.findtext("a:name", "", ns)
                    if name:
                        authors.append(name.strip())
                src = ResearchSource(
                    title=title,
                    url=url,
                    source_type=SourceType.arxiv,
                    authors=authors,
                    published=published,
                    abstract=summary[:2000],
                    doi=doi,
                    keywords=self._extract_keywords(summary),
                    publisher="arXiv",
                )
                sources.append(src)
        except Exception as e:
            logger.debug("arXiv parse error: %s", e)
        return sources

    def _parse_search_response(self, url: str, data: dict, query: str) -> List[ResearchSource]:
        sources = []
        try:
            if "query" in url and "pages" in data.get("query", {}):
                for page in data["query"].get("search", []):
                    title = page.get("title", "")
                    page_id = page.get("pageid", "")
                    snippet = page.get("snippet", "")
                    src = ResearchSource(
                        title=title,
                        url=f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                        source_type=SourceType.academic,
                        abstract=re.sub(r"<[^>]+>", "", snippet)[:2000],
                        keywords=[query],
                        publisher="Wikipedia",
                    )
                    sources.append(src)
        except Exception as e:
            logger.debug("Parse error: %s", e)
        return sources

    def _extract_doi(self, text: str) -> Optional[str]:
        m = re.search(r"10\.\d{4,}/[\w.\-/:;()]+", text)
        return m.group(0) if m else None

    def _extract_keywords(self, text: str) -> List[str]:
        words = re.findall(r"\b[A-Z][a-z]{3,}(?:\s[A-Z][a-z]{3,})?\b", text[:1000])
        return list(set(w.lower() for w in words))[:10]
