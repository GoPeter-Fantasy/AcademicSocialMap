"""Tests for the data-source facade: module caching, switching helpers,
run-summary shape (no network calls)."""
import datasource
import s2
import openalex


def test_load_caches_modules():
    a = datasource._load("s2")
    b = datasource._load("s2")
    assert a is b
    assert a is s2


def test_load_openalex_caches_modules():
    a = datasource._load("openalex")
    assert a is openalex


def test_get_module_does_not_mutate_global():
    # Even if the global backend is something else, get_module must return
    # the requested module without flipping _BACKEND.
    datasource.set_backend("openalex")
    m = datasource.get_module("s2")
    assert m is s2
    assert datasource.backend_name() == "openalex", "get_module must not change the active backend"


def test_set_backend_returns_module_name():
    name = datasource.set_backend("openalex")
    assert name == "openalex"
    assert datasource.backend_name() == "openalex"


def test_load_rejects_unknown_name():
    import pytest
    with pytest.raises(ValueError):
        datasource._load("not-a-backend")


def test_rate_limiter_enforces_min_interval():
    """P1-4: the limiter must sleep so back-to-back calls are at least
    `min_interval` seconds apart, but the very first call must be immediate."""
    import time
    limiter = datasource._RateLimiter(min_interval=0.10)
    t0 = time.monotonic()
    limiter.wait()
    first = time.monotonic() - t0
    assert first < 0.05, f"first call should not sleep, took {first:.3f}s"
    limiter.wait()
    second = time.monotonic() - t0
    assert second >= 0.10, f"second call should pace, only {second:.3f}s elapsed"


def test_rate_limiter_pace_is_thread_safe():
    """P1-4: concurrent calls must each respect the interval (no double-tap)."""
    import threading
    limiter = datasource._RateLimiter(min_interval=0.05)
    times = []
    lock = threading.Lock()

    def hit():
        limiter.wait()
        with lock:
            times.append(time.monotonic())

    import time
    threads = [threading.Thread(target=hit) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # All 5 hits should span at least 0.20s (5 * 0.05).
    span = max(times) - min(times)
    assert span >= 0.18, f"concurrent hits not paced: span={span:.3f}s, times={times}"
