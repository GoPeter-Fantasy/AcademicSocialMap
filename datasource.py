"""Unified data source facade with runtime backend switching.

The pipeline calls datasource.* functions; the active backend is selected
per-run via datasource.set_backend(name). Backends:
  - "s2":       Semantic Scholar (free, key optional, ~1 req/s shared pool)
  - "openalex": OpenAlex (free ~1000 req/day, key raises limits)
"""

import threading
import time

_BACKENDS: dict[str, object] = {}
_BACKEND = None


class _RateLimiter:
    """Minimal thread-safe minimum-interval rate limiter (P1-4).

    Each call to `wait()` blocks until at least `min_interval` seconds have
    passed since the previous call. Used to avoid hammering S2/OpenAlex and
    triggering 429 responses.
    """

    def __init__(self, min_interval: float = 1.1):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            if elapsed < self.min_interval and self._last > 0:
                time.sleep(self.min_interval - elapsed)
            self._last = time.monotonic()


# Per-backend pacing. S2 is the shared 1 req/s pool; OpenAlex is generous
# unless the user has no key, so we use a small floor to be polite.
_S2_LIMITER = _RateLimiter(min_interval=1.1)
_OA_LIMITER = _RateLimiter(min_interval=0.05)
_LIMITERS = {"s2": _S2_LIMITER, "openalex": _OA_LIMITER}


def _load(name: str):
    """Import (and cache) a backend module by name. Idempotent."""
    cached = _BACKENDS.get(name)
    if cached is not None:
        return cached
    if name == "s2":
        import s2 as _mod
    elif name == "openalex":
        import openalex as _mod
    else:
        raise ValueError(f"Unknown data source: {name} (use 's2' or 'openalex')")
    _BACKENDS[name] = _mod
    return _mod


def get_module(name: str):
    """Return a backend module by name without mutating the active backend.

    Use this from interactive endpoints (paper/author detail, ds-check) so
    they don't race with the pipeline worker thread that owns the global
    `_BACKEND` state.
    """
    return _load(name)


def set_backend(name: str) -> str:
    """Select the active backend for the pipeline. Returns the backend name."""
    global _BACKEND
    _BACKEND = _load(name)
    return _BACKEND.__name__


def get_backend():
    """Return the active backend module (for direct calls like probe)."""
    return _BACKEND


def backend_name() -> str:
    return _BACKEND.__name__ if _BACKEND else "(none)"


def _pace(name: str | None):
    """Apply the per-backend rate limiter if `name` matches a known backend."""
    if not name:
        return
    limiter = _LIMITERS.get(name)
    if limiter:
        limiter.wait()


def search_works(query: str, per_page: int = 20, extra_filter: str = "") -> list[dict]:
    _pace(backend_name())
    return _BACKEND.search_works(query, per_page=per_page, extra_filter=extra_filter)


def get_work(work_id: str) -> dict:
    _pace(backend_name())
    return _BACKEND.get_work(work_id)


def get_paper_detail(work_id: str) -> dict:
    _pace(backend_name())
    return _BACKEND.get_paper_detail(work_id)


def author_papers(author_id: str, limit: int = 25) -> list[dict]:
    _pace(backend_name())
    return _BACKEND.author_papers(author_id, limit=limit)


def get_works_batch(work_ids: list[str]) -> list[dict]:
    _pace(backend_name())
    return _BACKEND.get_works_batch(work_ids)


def citing_works(work_id: str, per_page: int = 50) -> list[dict]:
    _pace(backend_name())
    return _BACKEND.citing_works(work_id, per_page=per_page)


def referenced_works(work: dict, max_ids: int = 60) -> list[dict]:
    _pace(backend_name())
    return _BACKEND.referenced_works(work, max_ids=max_ids)


def work_summary(work: dict | None) -> dict:
    if work is None:
        return {
            "id": "", "title": "", "year": None, "cited_by_count": 0,
            "doi": None, "abstract": "", "pdf_url": "", "venue": "",
            "authors": [], "concepts": [], "referenced_works": [],
        }
    return _BACKEND.work_summary(work)
