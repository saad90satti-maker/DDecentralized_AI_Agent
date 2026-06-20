"""
Scraper Engine — BeautifulSoup + Scrapy hybrid data extraction pipeline.
Stores all extracted data in local SQLite databases with GitHub sync.
"""

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, quote

import requests
from bs4 import BeautifulSoup

from human_mimicry import HumanMimicryEngine

logger = logging.getLogger("ScraperEngine")

DATA_DIR = Path(__file__).resolve().parent / "agent_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "scraper_data.db"


class ScraperDB:
    """SQLite storage for all extracted data."""

    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scraped_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE,
                    domain TEXT,
                    title TEXT,
                    extracted_at TEXT,
                    content_preview TEXT,
                    raw_html_length INTEGER,
                    status_code INTEGER,
                    tags TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS extracted_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_url TEXT,
                    field_name TEXT,
                    field_value TEXT,
                    selector TEXT,
                    extracted_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT,
                    result_url TEXT,
                    result_title TEXT,
                    result_snippet TEXT,
                    position INTEGER,
                    extracted_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT,
                    value REAL,
                    details TEXT,
                    timestamp TEXT
                )
            """)
            conn.commit()

    def store_page(self, url: str, title: str, content: str, status_code: int,
                   tags: Optional[List[str]] = None) -> int:
        domain = urlparse(url).netloc
        preview = content[:500] if content else ""
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO scraped_pages
                       (url, domain, title, extracted_at, content_preview, raw_html_length, status_code, tags)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (url, domain, title, datetime.now(timezone.utc).isoformat(),
                     preview, len(content), status_code, json.dumps(tags or []))
                )
                return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            except Exception as e:
                logger.warning("DB store_page: %s", e)
                return -1

    def store_search_result(self, query: str, url: str, title: str, snippet: str, position: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute(
                    """INSERT INTO search_results (query, result_url, result_title, result_snippet, position, extracted_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (query, url, title, snippet, position, datetime.now(timezone.utc).isoformat())
                )
            except Exception as e:
                logger.warning("DB store_search: %s", e)

    def store_extracted(self, source_url: str, field: str, value: str, selector: str = "") -> None:
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute(
                    """INSERT INTO extracted_data (source_url, field_name, field_value, selector, extracted_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (source_url, field, value, selector, datetime.now(timezone.utc).isoformat())
                )
            except Exception as e:
                logger.warning("DB store_extracted: %s", e)

    def log_metric(self, event: str, value: float = 0.0, details: str = "") -> None:
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute(
                    "INSERT INTO metrics_log (event, value, details, timestamp) VALUES (?, ?, ?, ?)",
                    (event, value, details, datetime.now(timezone.utc).isoformat())
                )
            except Exception as e:
                logger.warning("DB log_metric: %s", e)

    def get_stats(self) -> Dict[str, int]:
        with sqlite3.connect(self.db_path) as conn:
            pages = conn.execute("SELECT COUNT(*) FROM scraped_pages").fetchone()[0]
            extracted = conn.execute("SELECT COUNT(*) FROM extracted_data").fetchone()[0]
            searches = conn.execute("SELECT COUNT(*) FROM search_results").fetchone()[0]
            metrics = conn.execute("SELECT COUNT(*) FROM metrics_log").fetchone()[0]
            return {"pages": pages, "extracted_fields": extracted, "searches": searches, "metrics": metrics}

    def export_json(self, table: str = "scraped_pages", limit: int = 100) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]


class ScraperEngine:
    """Extracts structured data from websites using requests + BeautifulSoup."""

    def __init__(self, db: Optional[ScraperDB] = None, mimicry: Optional[HumanMimicryEngine] = None):
        self.db = db or ScraperDB()
        self.mimicry = mimicry or HumanMimicryEngine()
        self.session = requests.Session()

    def scrape_url(self, url: str, extract: Optional[Dict[str, str]] = None,
                   tags: Optional[List[str]] = None) -> Dict[str, Any]:
        self.mimicry.record_action()
        self.mimicry.wait_between_requests()

        headers = self.mimicry.random_headers()
        try:
            r = self.session.get(url, headers=headers, timeout=30)
            r.raise_for_status()
        except Exception as e:
            logger.warning("Scrape failed %s: %s", url, e)
            self.db.log_metric("scrape_error", 1, str(e))
            return {"url": url, "status": "error", "error": str(e)}

        soup = BeautifulSoup(r.text, "lxml")
        title = self._extract_title(soup)

        self.db.store_page(url, title, r.text, r.status_code, tags=tags)
        self.db.log_metric("page_scraped", 1, url)

        result = {
            "url": url,
            "status_code": r.status_code,
            "title": title,
            "content_length": len(r.text),
        }

        if extract:
            extracted = {}
            for field_name, selector in extract.items():
                elements = soup.select(selector)
                if elements:
                    value = elements[0].get_text(strip=True) if len(elements) == 1 else [e.get_text(strip=True) for e in elements]
                    extracted[field_name] = value
                    self.db.store_extracted(url, field_name, str(value), selector)
            result["extracted"] = extracted

        return result

    def search_google(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        self.mimicry.record_action()
        self.mimicry.wait_between_searches()

        headers = self.mimicry.random_headers()
        search_url = f"https://www.google.com/search?q={quote(query)}&num={num_results}"
        try:
            r = self.session.get(search_url, headers=headers, timeout=30)
            r.raise_for_status()
        except Exception as e:
            logger.warning("Google search failed: %s", e)
            self.db.log_metric("search_error", 1, str(e))
            return []

        soup = BeautifulSoup(r.text, "lxml")
        results = []

        for i, g in enumerate(soup.select("div.g, div[data-hveid]")):
            link = g.select_one("a[href]")
            h3 = g.select_one("h3, a > h3")
            snippet = g.select_one("div.VwiC3b, span.aCOpRe, div[data-sncf]")
            if link and h3:
                href = link.get("href", "")
                if href.startswith("/url?q="):
                    href = href.split("/url?q=")[1].split("&")[0]
                title = h3.get_text(strip=True)
                snippet_text = snippet.get_text(strip=True) if snippet else ""
                results.append({"url": href, "title": title, "snippet": snippet_text, "position": i + 1})
                self.db.store_search_result(query, href, title, snippet_text, i + 1)

        self.db.log_metric("search_completed", len(results), query)
        logger.info("Google search '%s': %d results", query, len(results))
        return results

    def extract_links(self, url: str, selector: str = "a[href]") -> List[Dict[str, str]]:
        self.mimicry.record_action()
        self.mimicry.wait_between_requests()

        headers = self.mimicry.random_headers()
        try:
            r = self.session.get(url, headers=headers, timeout=30)
            soup = BeautifulSoup(r.text, "lxml")
        except Exception as e:
            logger.warning("Link extraction failed: %s", e)
            return []

        links = []
        for a in soup.select(selector):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if href and text:
                links.append({"url": href, "text": text})

        self.db.store_page(url, "", r.text[:500], r.status_code, tags=["link_extraction"])
        return links

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        title = soup.select_one("title")
        if title:
            t = title.get_text(strip=True)
            if t:
                return t[:500]
        h1 = soup.select_one("h1")
        return h1.get_text(strip=True)[:500] if h1 else "(no title)"
