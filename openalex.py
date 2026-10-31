import time
from typing import Any

import requests

import config

BASE = "https://api.openalex.org"


def _headers() -> dict[str, str]:
    headers = {"User-Agent": config.USER_AGENT}
    if config.OPENALEX_API_KEY:
        headers["X-OpenAlex-Key"] = config.OPENALEX_API_KEY
    return headers


def _get(path: str, params: dict[str, Any], retries: int = 3) -> dict:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(
                f"{BASE}/{path}",
                params=params,
                headers=_headers(),
                timeout=30,
            )
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else 2.0 * (attempt + 1)
            last_err = RuntimeError(
                f"OpenAlex rate limited (HTTP 429, retry-after={retry_after})"
            )
            time.sleep(min(wait, 20))
            continue
        if resp.status_code >= 400:
            last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:120]}")
            break
        return resp.json()
    raise RuntimeError(f"OpenAlex request failed: {last_err}")


def search_works(query: str, per_page: int = 20, extra_filter: str = "") -> list[dict]:
    flt = "language:en"
    if extra_filter:
        flt += f",{extra_filter}"
    data = _get("works", {"search": query, "per-page": per_page, "filter": flt})
    return data.get("results", [])


def probe() -> dict:
    """Single quick request, no retries — for health checks."""
    try:
        resp = requests.get(f"{BASE}/works", params={"per-page": 1}, headers=_headers(), timeout=15)
        if resp.status_code == 200:
            return {"ok": True}
        return {"ok": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def get_work(work_id: str) -> dict:
    return _get(f"works/{work_id}", {})


def get_paper_detail(work_id: str) -> dict:
    """Full paper detail incl. PDF link, journal, authors (for the UI)."""
    return _get(f"works/{work_id}", {})


def author_papers(author_id: str, limit: int = 25) -> list[dict]:
    """Top papers by an author (for the UI author panel)."""
    data = _get("works", {
        "filter": f"author.id:{author_id},language:en",
        "per-page": limit,
        "sort": "cited_by_count:desc",
    })
    return data.get("results", [])


def get_works_batch(work_ids: list[str]) -> list[dict]:
    """Fetch multiple works by OpenAlex IDs in one OR-filter request."""
    if not work_ids:
        return []
    flt = "|".join(work_ids)
    out: list[dict] = []
    seen_ids: set[str] = set()
    per_page = 100
    page = 1
    while True:
        data = _get("works", {
            "filter": f"ids.openalex:{flt}",
            "per-page": per_page,
            "page": page,
        })
        results = [r for r in data.get("results", []) if r]
        if not results:
            break
        for r in results:
            rid = _id_of(r)
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                out.append(r)
        if len(results) < per_page:
            break
        page += 1
        if page > 20:
            break
    return out


def citing_works(work_id: str, per_page: int = 50) -> list[dict]:
    data = _get("works", {
        "filter": f"cites:{work_id},language:en",
        "per-page": per_page,
        "sort": "cited_by_count:desc",
    })
    return data.get("results", [])


def referenced_works(work: dict, max_ids: int = 60) -> list[dict]:
    refs = work.get("referenced_works", [])
    if not refs:
        return []
    ids = [r.rsplit("/", 1)[-1] for r in refs[:max_ids]]
    return get_works_batch(ids)


def get_author(author_id: str) -> dict:
    return _get(f"authors/{author_id}", {})


def _id_of(entity: dict) -> str:
    raw = entity.get("id")
    if not raw:
        return ""
    return raw.rsplit("/", 1)[-1]


def openalex_author_id(author: dict) -> str:
    return _id_of(author)


def work_summary(work: dict) -> dict:
    best_oa = (work.get("best_oa_location") or {})
    pdf = (best_oa.get("pdf_url") or "") or (work.get("open_access") or {}).get("oa_url") or ""
    return {
        "id": _id_of(work),
        "title": work.get("display_name") or "",
        "year": work.get("publication_year"),
        "cited_by_count": work.get("cited_by_count", 0),
        "doi": work.get("doi"),
        "abstract": _abstract(work),
        "pdf_url": pdf or "",
        "venue": (work.get("primary_location") or {}).get("source", {}).get("display_name", "") if work.get("primary_location") else "",
        "authors": [
            {"id": _id_of(a.get("author", {})),
             "name": (a.get("author") or {}).get("display_name", ""),
             "institution": (a.get("institutions") or [{}])[0].get("display_name", "") if a.get("institutions") else ""}
            for a in work.get("authorships", [])
        ],
        "concepts": [c.get("display_name", "") for c in (work.get("concepts") or [])][:5],
        "referenced_works": [r.rsplit("/", 1)[-1] for r in work.get("referenced_works", [])],
    }


def _abstract(work: dict) -> str:
    inv = work.get("abstract_inverted_index")
    if not inv:
        return ""
    pos: list[tuple[int, str]] = []
    for word, positions in inv.items():
        for p in positions:
            pos.append((p, word))
    pos.sort()
    return " ".join(w for _, w in pos)
