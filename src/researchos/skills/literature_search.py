"""Literature Search Skill — arXiv & Semantic Scholar API client with caching.

Wraps external academic search APIs with:
- Normalized query strings (lowercase, whitespace collapse)
- Persistent SQLite TTL-based response cache
- Configurable max results and sort order
- Unified result format across providers
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

# Default cache TTL: 7 days in seconds.
_DEFAULT_TTL = 7 * 24 * 3600

# arXiv API constants
_ARXIV_BASE = "http://export.arxiv.org/api/query"
_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Semantic Scholar API constants
_S2_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class PaperResult:
    """Unified paper result from any search provider.

    Attributes
    ----------
    title : str
        Paper title.
    authors : list[str]
        List of author names.
    abstract : str
        Paper abstract.
    year : int | None
        Publication year.
    doi : str
        DOI identifier (empty string if unavailable).
    arxiv_id : str
        arXiv identifier (empty string if unavailable).
    url : str
        Direct link to the paper.
    source : str
        Which API returned this result (``"arxiv"`` or ``"semantic_scholar"``).
    metadata : dict
        Provider-specific extra fields.
    """

    title: str = ""
    authors: List[str] = field(default_factory=list)
    abstract: str = ""
    year: Optional[int] = None
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cache Layer (SQLite)
# ---------------------------------------------------------------------------

class _QueryCache:
    """Persistent key-value cache backed by SQLite."""

    def __init__(self, db_path: str, ttl: int = _DEFAULT_TTL) -> None:
        self.ttl = ttl
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                ts    REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def get(self, key: str) -> Optional[str]:
        """Return cached value if present and not expired, else None."""
        row = self._conn.execute(
            "SELECT value, ts FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, ts = row
        if time.time() - ts > self.ttl:
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self._conn.commit()
            return None
        return value

    def set(self, key: str, value: str) -> None:
        """Insert or update a cache entry."""
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, ts) VALUES (?, ?, ?)",
            (key, value, time.time()),
        )
        self._conn.commit()

    def clear(self) -> None:
        """Drop all cached entries."""
        self._conn.execute("DELETE FROM cache")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _normalize_query(query: str) -> str:
    """Normalize a search query for cache key generation."""
    return " ".join(query.lower().split())


def _cache_key(provider: str, query: str, max_results: int) -> str:
    """Generate a deterministic cache key."""
    normalized = _normalize_query(query)
    raw = f"{provider}:{normalized}:{max_results}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# arXiv Client
# ---------------------------------------------------------------------------

def search_arxiv(
    query: str,
    max_results: int = 5,
    sort_by: str = "relevance",
) -> List[PaperResult]:
    """Search arXiv via their Atom API.

    Parameters
    ----------
    query : str
        Search query string.
    max_results : int
        Maximum number of results.
    sort_by : str
        Sort order — ``"relevance"`` or ``"lastUpdatedDate"``.

    Returns
    -------
    list[PaperResult]
    """
    import urllib.request

    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": "descending",
    })
    url = f"{_ARXIV_BASE}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            xml_data = resp.read().decode("utf-8")
    except Exception as exc:
        logger.error("arXiv API request failed: %s", exc)
        return []

    return _parse_arxiv_xml(xml_data)


def _parse_arxiv_xml(xml_data: str) -> List[PaperResult]:
    """Parse arXiv Atom XML into PaperResult list."""
    results: List[PaperResult] = []
    try:
        root = ElementTree.fromstring(xml_data)
    except ElementTree.ParseError:
        logger.error("Failed to parse arXiv XML response")
        return results

    for entry in root.findall("atom:entry", _ARXIV_NS):
        title_el = entry.find("atom:title", _ARXIV_NS)
        summary_el = entry.find("atom:summary", _ARXIV_NS)
        id_el = entry.find("atom:id", _ARXIV_NS)
        published_el = entry.find("atom:published", _ARXIV_NS)

        authors = []
        for author_el in entry.findall("atom:author", _ARXIV_NS):
            name_el = author_el.find("atom:name", _ARXIV_NS)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        abstract = summary_el.text.strip() if summary_el is not None and summary_el.text else ""
        paper_url = id_el.text.strip() if id_el is not None and id_el.text else ""

        year = None
        if published_el is not None and published_el.text:
            try:
                year = int(published_el.text[:4])
            except (ValueError, IndexError):
                pass

        # Extract arXiv ID from the URL
        arxiv_id = ""
        if paper_url:
            arxiv_id = paper_url.rsplit("/", 1)[-1]

        results.append(PaperResult(
            title=title,
            authors=authors,
            abstract=abstract,
            year=year,
            arxiv_id=arxiv_id,
            url=paper_url,
            source="arxiv",
        ))

    return results


# ---------------------------------------------------------------------------
# Semantic Scholar Client
# ---------------------------------------------------------------------------

def search_semantic_scholar(
    query: str,
    max_results: int = 5,
    fields: Optional[List[str]] = None,
) -> List[PaperResult]:
    """Search Semantic Scholar via their Graph API.

    Parameters
    ----------
    query : str
        Search query string.
    max_results : int
        Maximum number of results (capped at 100 by S2 API).
    fields : list[str] | None
        Fields to retrieve. Defaults to title, abstract, authors, year, DOI, URL.

    Returns
    -------
    list[PaperResult]
    """
    import urllib.request

    if fields is None:
        fields = ["title", "abstract", "authors", "year", "externalIds", "url"]

    params = urllib.parse.urlencode({
        "query": query,
        "limit": min(max_results, 100),
        "fields": ",".join(fields),
    })
    url = f"{_S2_BASE}?{params}"

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.error("Semantic Scholar API request failed: %s", exc)
        return []

    return _parse_s2_response(data)


def _parse_s2_response(data: Dict[str, Any]) -> List[PaperResult]:
    """Parse Semantic Scholar JSON response into PaperResult list."""
    results: List[PaperResult] = []
    papers = data.get("data", [])

    for paper in papers:
        authors = []
        for author in paper.get("authors", []):
            name = author.get("name", "")
            if name:
                authors.append(name)

        external_ids = paper.get("externalIds", {}) or {}
        doi = external_ids.get("DOI", "") or ""
        arxiv_id = external_ids.get("ArXiv", "") or ""

        results.append(PaperResult(
            title=paper.get("title", "") or "",
            authors=authors,
            abstract=paper.get("abstract", "") or "",
            year=paper.get("year"),
            doi=doi,
            arxiv_id=arxiv_id,
            url=paper.get("url", "") or "",
            source="semantic_scholar",
            metadata={"paperId": paper.get("paperId", "")},
        ))

    return results


# ---------------------------------------------------------------------------
# Unified Search with Caching
# ---------------------------------------------------------------------------

class LiteratureSearchSkill:
    """Unified literature search across arXiv and Semantic Scholar with caching.

    Parameters
    ----------
    cache_dir : str | None
        Directory for the SQLite cache database. Defaults to ``.cache/``
        in the current directory.
    cache_ttl : int
        Cache time-to-live in seconds (default: 7 days).
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        cache_ttl: int = _DEFAULT_TTL,
    ) -> None:
        cache_path = Path(cache_dir or ".cache")
        cache_path.mkdir(parents=True, exist_ok=True)
        self._cache = _QueryCache(
            str(cache_path / "literature_cache.db"), ttl=cache_ttl
        )

    def search(
        self,
        query: str,
        max_results: int = 5,
        provider: str = "both",
    ) -> List[PaperResult]:
        """Search for papers.

        Parameters
        ----------
        query : str
            Search query.
        max_results : int
            Max results per provider.
        provider : str
            ``"arxiv"``, ``"semantic_scholar"``, or ``"both"`` (default).

        Returns
        -------
        list[PaperResult]
            Deduplicated results across providers.
        """
        results: List[PaperResult] = []

        if provider in ("arxiv", "both"):
            results.extend(self._cached_search("arxiv", query, max_results))

        if provider in ("semantic_scholar", "both"):
            results.extend(
                self._cached_search("semantic_scholar", query, max_results)
            )

        # Deduplicate by title (case-insensitive)
        seen_titles: set = set()
        deduped: List[PaperResult] = []
        for r in results:
            key = r.title.lower().strip()
            if key and key not in seen_titles:
                seen_titles.add(key)
                deduped.append(r)

        return deduped

    def _cached_search(
        self, provider: str, query: str, max_results: int
    ) -> List[PaperResult]:
        """Search with cache layer."""
        key = _cache_key(provider, query, max_results)

        # Check cache
        cached = self._cache.get(key)
        if cached is not None:
            logger.info("Cache hit for %s query: %s", provider, query)
            try:
                raw_list = json.loads(cached)
                return [PaperResult(**r) for r in raw_list]
            except (json.JSONDecodeError, TypeError):
                pass

        # Cache miss — fetch from API
        logger.info("Cache miss for %s query: %s", provider, query)
        if provider == "arxiv":
            results = search_arxiv(query, max_results)
        else:
            results = search_semantic_scholar(query, max_results)

        # Store in cache
        serializable = [
            {
                "title": r.title,
                "authors": r.authors,
                "abstract": r.abstract,
                "year": r.year,
                "doi": r.doi,
                "arxiv_id": r.arxiv_id,
                "url": r.url,
                "source": r.source,
                "metadata": r.metadata,
            }
            for r in results
        ]
        self._cache.set(key, json.dumps(serializable))
        return results

    def clear_cache(self) -> None:
        """Clear all cached search results."""
        self._cache.clear()

    def close(self) -> None:
        """Close the cache database connection."""
        self._cache.close()
