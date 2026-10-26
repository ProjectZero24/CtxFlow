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
from enum import Enum
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

class SearchStatus(str, Enum):
    """Honest outcome of a provider search.

    ``partial`` means at least one provider succeeded and at least one failed;
    ``error`` means every requested provider failed.
    """

    OK = "ok"
    EMPTY = "empty"
    PARTIAL = "partial"
    ERROR = "error"


class ProviderParseError(ValueError):
    """A provider returned a response that could not be parsed."""


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


@dataclass
class ProviderOutcome:
    """Result of one provider call, including failure information.

    The legacy ``search_arxiv`` / ``search_semantic_scholar`` functions still
    return a plain list. Use the ``*_outcome`` variants (or
    :meth:`LiteratureSearchSkill.search_with_outcome`) when the caller needs to
    distinguish "no matches" from "provider failed".
    """

    provider: str
    status: SearchStatus
    results: List[PaperResult] = field(default_factory=list)
    error: str = ""
    error_type: str = ""
    status_code: Optional[int] = None
    from_cache: bool = False
    elapsed_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status.value,
            "result_count": len(self.results),
            "error": self.error,
            "error_type": self.error_type,
            "status_code": self.status_code,
            "from_cache": self.from_cache,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


@dataclass
class SearchOutcome:
    """Aggregate outcome of a (possibly multi-provider) search."""

    query: str
    provider: str
    outcomes: List[ProviderOutcome] = field(default_factory=list)
    results: List[PaperResult] = field(default_factory=list)
    status: SearchStatus = SearchStatus.EMPTY
    elapsed_ms: float = 0.0

    @property
    def errors(self) -> Dict[str, str]:
        """Map provider name -> error message for failed providers."""
        return {
            outcome.provider: outcome.error
            for outcome in self.outcomes
            if outcome.status is SearchStatus.ERROR and outcome.error
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "provider": self.provider,
            "status": self.status.value,
            "result_count": len(self.results),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "providers": {
                outcome.provider: outcome.to_dict() for outcome in self.outcomes
            },
            "errors": self.errors,
        }


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000.0


def _clean_error(exc: BaseException, limit: int = 500) -> str:
    message = " ".join(str(exc).split())
    return message[:limit]


def _status_code(exc: BaseException) -> Optional[int]:
    for attribute in ("code", "status_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _paper_to_dict(paper: PaperResult) -> Dict[str, Any]:
    return {
        "title": paper.title,
        "authors": paper.authors,
        "abstract": paper.abstract,
        "year": paper.year,
        "doi": paper.doi,
        "arxiv_id": paper.arxiv_id,
        "url": paper.url,
        "source": paper.source,
        "metadata": paper.metadata,
    }


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
    """Search arXiv via their Atom API (backwards-compatible wrapper).

    Returns only the results. Use :func:`search_arxiv_outcome` to distinguish
    an empty result set from a provider failure.
    """
    return search_arxiv_outcome(query, max_results=max_results, sort_by=sort_by).results


def search_arxiv_outcome(
    query: str,
    max_results: int = 5,
    sort_by: str = "relevance",
    timeout: float = 30.0,
) -> ProviderOutcome:
    """Search arXiv and return an explicit provider outcome.

    Parameters
    ----------
    query : str
        Search query string.
    max_results : int
        Maximum number of results.
    sort_by : str
        Sort order — ``"relevance"`` or ``"lastUpdatedDate"``.
    timeout : float
        Socket timeout in seconds.

    Returns
    -------
    ProviderOutcome
        ``ok`` with results, ``empty`` with no results, or ``error`` with the
        exception type/message. Malformed XML is an error, never an empty list.
    """
    import urllib.request

    started = time.monotonic()
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": "descending",
    })
    url = f"{_ARXIV_BASE}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            xml_data = resp.read().decode("utf-8")
        results = _parse_arxiv_xml(xml_data)
    except ProviderParseError as exc:
        logger.error("arXiv response parse failed: %s", exc)
        return ProviderOutcome(
            provider="arxiv",
            status=SearchStatus.ERROR,
            error=_clean_error(exc),
            error_type=type(exc).__name__,
            elapsed_ms=_elapsed_ms(started),
        )
    except Exception as exc:
        logger.error("arXiv API request failed: %s", exc)
        return ProviderOutcome(
            provider="arxiv",
            status=SearchStatus.ERROR,
            error=_clean_error(exc),
            error_type=type(exc).__name__,
            status_code=_status_code(exc),
            elapsed_ms=_elapsed_ms(started),
        )

    return ProviderOutcome(
        provider="arxiv",
        status=SearchStatus.OK if results else SearchStatus.EMPTY,
        results=results,
        elapsed_ms=_elapsed_ms(started),
    )


def _parse_arxiv_xml(xml_data: str) -> List[PaperResult]:
    """Parse arXiv Atom XML into PaperResult list.

    Raises
    ------
    ProviderParseError
        If the payload is not valid XML. A valid XML document with no entries
        is a legitimate empty result, not an error.
    """
    results: List[PaperResult] = []
    try:
        root = ElementTree.fromstring(xml_data)
    except ElementTree.ParseError as exc:
        raise ProviderParseError("arXiv response was not valid XML") from exc

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
    """Search Semantic Scholar via their Graph API (compatibility wrapper).

    Returns only the results. Use :func:`search_semantic_scholar_outcome` to
    distinguish an empty result set from a provider failure.
    """
    return search_semantic_scholar_outcome(
        query, max_results=max_results, fields=fields
    ).results


def search_semantic_scholar_outcome(
    query: str,
    max_results: int = 5,
    fields: Optional[List[str]] = None,
    timeout: float = 30.0,
) -> ProviderOutcome:
    """Search Semantic Scholar and return an explicit provider outcome."""
    import urllib.request

    started = time.monotonic()
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = _parse_s2_response(data)
    except ProviderParseError as exc:
        logger.error("Semantic Scholar response parse failed: %s", exc)
        return ProviderOutcome(
            provider="semantic_scholar",
            status=SearchStatus.ERROR,
            error=_clean_error(exc),
            error_type=type(exc).__name__,
            elapsed_ms=_elapsed_ms(started),
        )
    except Exception as exc:
        logger.error("Semantic Scholar API request failed: %s", exc)
        return ProviderOutcome(
            provider="semantic_scholar",
            status=SearchStatus.ERROR,
            error=_clean_error(exc),
            error_type=type(exc).__name__,
            status_code=_status_code(exc),
            elapsed_ms=_elapsed_ms(started),
        )

    return ProviderOutcome(
        provider="semantic_scholar",
        status=SearchStatus.OK if results else SearchStatus.EMPTY,
        results=results,
        elapsed_ms=_elapsed_ms(started),
    )


def _parse_s2_response(data: Dict[str, Any]) -> List[PaperResult]:
    """Parse Semantic Scholar JSON response into PaperResult list.

    Raises
    ------
    ProviderParseError
        If the payload is not a search response object or ``data`` is not a
        list. A valid response with an empty ``data`` list is ``empty``.
    """
    if not isinstance(data, dict):
        raise ProviderParseError("Semantic Scholar response was not a JSON object")

    papers = data.get("data", [])
    if papers is None:
        papers = []
    if not isinstance(papers, list):
        raise ProviderParseError(
            "Semantic Scholar response 'data' field was not a list"
        )
    if "error" in data and not papers:
        raise ProviderParseError(str(data["error"]))

    results: List[PaperResult] = []
    for paper in papers:
        if not isinstance(paper, dict):
            raise ProviderParseError(
                "Semantic Scholar response contained a non-object paper entry"
            )
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
        """Search for papers (backwards-compatible list result).

        Use :meth:`search_with_outcome` when the caller needs to distinguish
        ``empty`` from ``error`` or inspect per-provider status.
        """
        return self.search_with_outcome(
            query=query, max_results=max_results, provider=provider
        ).results

    def search_with_outcome(
        self,
        query: str,
        max_results: int = 5,
        provider: str = "both",
    ) -> SearchOutcome:
        """Search for papers and return an explicit aggregate outcome.

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
        SearchOutcome
            ``status`` is ``ok`` (at least one result), ``empty`` (all
            providers returned no matches), ``partial`` (some providers failed),
            or ``error`` (all requested providers failed). Failed providers
            carry their exception type/message and are never cached.
        """
        started = time.monotonic()
        normalized = (provider or "both").strip().lower()

        if normalized == "both":
            providers = ["arxiv", "semantic_scholar"]
        elif normalized in ("arxiv", "semantic_scholar"):
            providers = [normalized]
        else:
            message = (
                f"unsupported provider {provider!r}; expected "
                "'arxiv', 'semantic_scholar', or 'both'"
            )
            logger.error(message)
            return SearchOutcome(
                query=query,
                provider=normalized,
                outcomes=[
                    ProviderOutcome(
                        provider=normalized,
                        status=SearchStatus.ERROR,
                        error=message,
                        error_type="ValueError",
                    )
                ],
                results=[],
                status=SearchStatus.ERROR,
                elapsed_ms=_elapsed_ms(started),
            )

        outcomes = [
            self._cached_search(name, query, max_results) for name in providers
        ]
        results = self._dedupe(
            [paper for outcome in outcomes for paper in outcome.results]
        )
        status = self._aggregate_status(outcomes)

        if status is SearchStatus.ERROR:
            logger.error("Literature search failed for %r: %s", query, {
                outcome.provider: outcome.error for outcome in outcomes
            })
        elif status is SearchStatus.PARTIAL:
            logger.warning("Literature search partially failed for %r: %s", query, {
                outcome.provider: outcome.error
                for outcome in outcomes
                if outcome.status is SearchStatus.ERROR
            })

        return SearchOutcome(
            query=query,
            provider=normalized,
            outcomes=outcomes,
            results=results,
            status=status,
            elapsed_ms=_elapsed_ms(started),
        )

    @staticmethod
    def _dedupe(results: List[PaperResult]) -> List[PaperResult]:
        """Deduplicate by title (case-insensitive).

        Metadata-based dedupe (DOI -> arXiv ID -> title) is a separate gap and
        is intentionally not changed here.
        """
        seen_titles: set = set()
        deduped: List[PaperResult] = []
        for result in results:
            key = result.title.lower().strip()
            if key and key not in seen_titles:
                seen_titles.add(key)
                deduped.append(result)
        return deduped

    @staticmethod
    def _aggregate_status(outcomes: List[ProviderOutcome]) -> SearchStatus:
        if not outcomes:
            return SearchStatus.EMPTY
        statuses = {outcome.status for outcome in outcomes}
        if statuses == {SearchStatus.ERROR}:
            return SearchStatus.ERROR
        if SearchStatus.ERROR in statuses:
            return SearchStatus.PARTIAL
        if SearchStatus.OK in statuses:
            return SearchStatus.OK
        return SearchStatus.EMPTY

    def _cached_search(
        self, provider: str, query: str, max_results: int
    ) -> ProviderOutcome:
        """Return a provider outcome, using the cache only for success/empty."""
        key = _cache_key(provider, query, max_results)

        cached = self._cache.get(key)
        if cached is not None:
            outcome = self._deserialize_cache(provider, cached)
            if outcome is not None:
                outcome.from_cache = True
                outcome.elapsed_ms = 0.0
                logger.info("Cache hit for %s query: %s", provider, query)
                return outcome
            logger.warning("Ignoring unreadable cache entry for %s: %s", provider, query)

        logger.info("Cache miss for %s query: %s", provider, query)
        outcome = self._fetch_outcome(provider, query, max_results)

        # Never cache failures: a transient provider outage must not look like
        # "no matches" for the next seven days.
        if outcome.status in (SearchStatus.OK, SearchStatus.EMPTY):
            self._cache.set(key, self._serialize_cache(outcome))
        return outcome

    @staticmethod
    def _fetch_outcome(
        provider: str, query: str, max_results: int
    ) -> ProviderOutcome:
        if provider == "arxiv":
            return search_arxiv_outcome(query, max_results=max_results)
        if provider == "semantic_scholar":
            return search_semantic_scholar_outcome(
                query, max_results=max_results
            )
        return ProviderOutcome(
            provider=provider,
            status=SearchStatus.ERROR,
            error=f"unsupported provider {provider!r}",
            error_type="ValueError",
        )

    @staticmethod
    def _serialize_cache(outcome: ProviderOutcome) -> str:
        return json.dumps({
            "status": outcome.status.value,
            "error": outcome.error,
            "error_type": outcome.error_type,
            "status_code": outcome.status_code,
            "results": [_paper_to_dict(paper) for paper in outcome.results],
        })

    @staticmethod
    def _deserialize_cache(
        provider: str, cached: str
    ) -> Optional[ProviderOutcome]:
        """Read new or legacy cache entries; return None to force a refetch."""
        try:
            payload = json.loads(cached)
        except (json.JSONDecodeError, TypeError):
            return None

        # Legacy format: a raw list of serialized PaperResult dicts.
        if isinstance(payload, list):
            try:
                results = [PaperResult(**item) for item in payload]
            except (TypeError, ValueError):
                return None
            return ProviderOutcome(
                provider=provider,
                status=SearchStatus.OK if results else SearchStatus.EMPTY,
                results=results,
            )

        if not isinstance(payload, dict):
            return None

        try:
            status = SearchStatus(payload.get("status", SearchStatus.OK.value))
        except ValueError:
            status = SearchStatus.OK
        if status is SearchStatus.ERROR:
            return None

        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            return None
        try:
            results = [PaperResult(**item) for item in raw_results]
        except (TypeError, ValueError):
            return None

        return ProviderOutcome(
            provider=provider,
            status=status,
            results=results,
            error=str(payload.get("error", "") or ""),
            error_type=str(payload.get("error_type", "") or ""),
            status_code=payload.get("status_code"),
        )

    def clear_cache(self) -> None:
        """Clear all cached search results."""
        self._cache.clear()

    def close(self) -> None:
        """Close the cache database connection."""
        self._cache.close()
