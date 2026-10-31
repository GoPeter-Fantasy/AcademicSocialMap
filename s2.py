"""Semantic Scholar data source (free, no key required for basic use).

With a free API key (x-api-key header) the shared-pool rate limit is
relaxed (~100 req/sec). Store it with `python set_api_key.py s2 <key>`
(keyring by default, KEYS_DIR file as fallback).
"""
import threading
import time
from typing import Any

import requests

import config

BASE = "https://api.semanticscholar.org/graph/v1"

_throttle = threading.Lock()
_last_req = [0.0]
MIN_INTERVAL = 2.0  # seconds between requests (S2 free-key limit is 1 RPS)

# In-memory cache for interactive endpoints (author papers / paper detail),
# so clicking around the graph does not re-hit the API and trigger 429s.
_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 600.0


def _cached(key: str, fetcher):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    value = fetcher()
    _cache[key] = (now, value)
    return value


def _clear_cache():
    _cache.clear()


def _headers() -> dict[str, str]:
    headers = {}
    if config.S2_API_KEY:
        headers["x-api-key"] = config.S2_API_KEY
    return headers


def _throttled_request(func, *args, **kwargs):
    with _throttle:
        wait = MIN_INTERVAL - (time.time() - _last_req[0])
        if wait > 0:
            time.sleep(wait)
        resp = func(*args, headers=_headers(), **kwargs)
        _last_req[0] = time.time()
    return resp

# S2 returns ~100 citations/references per paper in batch responses;
# pagination is not supported for nested fields, so we cap by preference.
FIELDS = "title,year,citationCount,abstract,externalIds,references.paperId,authors.name,authors.authorId,authors.affiliations,openAccessPdf"

DETAIL_FIELDS = (
    "title,year,citationCount,abstract,externalIds,openAccessPdf,"
    "authors.name,authors.authorId,authors.affiliations,venue,publicationTypes"
)


def _get(path: str, params: dict[str, Any], retries: int = 4) -> dict:
    """429 retried with backoff (S2 free-key window is 1 RPS). Other 4xx/5xx
    errors (e.g. 400 rejected query) are permanent, so we fail fast instead of
    wasting the rate-limit budget on retries that can't succeed."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = _throttled_request(
                requests.get, f"{BASE}/{path}", params=params, timeout=30
            )
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else 5.0 * (attempt + 1)
            last_err = RuntimeError(f"S2 rate limited (HTTP 429)")
            time.sleep(min(wait, 25))
            continue
        if resp.status_code >= 400:
            last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:120]}")
            break
        return resp.json()
    raise RuntimeError(f"S2 request failed: {last_err}")


def search_works(query: str, per_page: int = 20, extra_filter: str = "") -> list[dict]:
    data = _get("paper/search", {"query": query, "limit": per_page, "fields": FIELDS})
    return data.get("data", [])


def probe() -> dict:
    """Single quick request, no retries — for health checks."""
    resp = _throttled_request(
        requests.get, f"{BASE}/paper/search",
        params={"query": "graph neural network", "limit": 1, "fields": "title"},
        timeout=15,
    )
    if resp.status_code == 200:
        return {"ok": True}
    return {"ok": False, "error": f"HTTP {resp.status_code}"}


def get_work(work_id: str) -> dict:
    return _get(f"paper/{work_id}", {"fields": FIELDS})


def get_paper_detail(work_id: str) -> dict:
    """Full paper detail incl. PDF link, journal, authors (for the UI)."""
    return _cached(f"paper:{work_id}", lambda: _get(f"paper/{work_id}", {"fields": DETAIL_FIELDS}))


def author_papers(author_id: str, limit: int = 25) -> list[dict]:
    """Recent/highly-cited papers by an author (for the UI author panel)."""
    def fetch():
        data = _get(f"author/{author_id}/papers", {
            "fields": "title,year,citationCount,externalIds,openAccessPdf,venue,authors.name",
            "limit": limit,
            "sort": "citationCount:desc",
        })
        return data.get("data", [])
    return _cached(f"author:{author_id}:{limit}", fetch)


def get_works_batch(work_ids: list[str]) -> list[dict]:
    """Fetch multiple works by S2 paper IDs (batched POST)."""
    if not work_ids:
        return []
    out: list[dict] = []
    ids = list(dict.fromkeys(work_ids))
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        for attempt in range(4):
            try:
                resp = _throttled_request(
                    requests.post,
                    f"{BASE}/paper/batch",
                    json={"ids": chunk},
                    params={"fields": FIELDS},
                    timeout=60,
                )
            except Exception:
                if attempt == 3:
                    break
                time.sleep(3.0 * (attempt + 1))
                continue
            if resp.status_code == 429:
                time.sleep(5.0 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                break
            out.extend(x for x in resp.json() if x)
            break
    return out


CITING_FIELDS = "citations.title,citations.year,citations.citationCount,citations.externalIds"


def citing_works(work_id: str, per_page: int = 50) -> list[dict]:
    data = _get(f"paper/{work_id}", {"fields": CITING_FIELDS})
    cites = data.get("citations") or []
    cites.sort(key=lambda c: c.get("citationCount") or 0, reverse=True)
    papers = []
    for c in cites[:per_page]:
        if isinstance(c, dict):
            p = c.get("citingPaper") or c
            papers.append(p)
    # citing papers lack author info (unsupported nested field);
    # enrich them in one batch request.
    ids = [p.get("paperId") for p in papers if p.get("paperId")]
    if ids:
        enriched = {w.get("paperId"): w for w in get_works_batch(ids)}
        for p in papers:
            e = enriched.get(p.get("paperId"))
            if e:
                p["authors"] = e.get("authors", [])
                p["abstract"] = p.get("abstract") or e.get("abstract")
    return papers


def referenced_works(work: dict, max_ids: int = 60) -> list[dict]:
    refs = work.get("references") or []
    if not refs:
        return []
    ids = [r.get("paperId") for r in refs[:max_ids] if r.get("paperId")]
    return get_works_batch(ids)


def _first_affiliation(a: dict) -> str:
    """S2 affiliations can be [{'name':...}] or [str] or []."""
    affs = a.get("affiliations") or []
    if not affs:
        return ""
    first = affs[0]
    if isinstance(first, dict):
        return first.get("name", "")
    return str(first)


def work_summary(work: dict) -> dict:
    pdf = ""
    try:
        pdf = ((work.get("openAccessPdf") or {}).get("url") or "")
    except AttributeError:
        pdf = ""
    journal = work.get("journal") or {}
    venue = work.get("venue") or journal.get("name") or ""
    return {
        "id": work.get("paperId", ""),
        "title": work.get("title") or "",
        "year": work.get("year"),
        "cited_by_count": work.get("citationCount", 0),
        "doi": work.get("externalIds", {}).get("DOI") if work.get("externalIds") else None,
        "abstract": work.get("abstract") or "",
        "pdf_url": pdf,
        "venue": venue,
        "authors": [
            {"id": a.get("authorId", ""),
             "name": a.get("name", ""),
             "institution": _first_affiliation(a)}
            for a in work.get("authors", [])
        ],
        "concepts": [],
        "referenced_works": [],
    }


def openalex_author_id(author: dict) -> str:
    return author.get("authorId", "")
