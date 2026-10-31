"""Tests for the FastAPI server's safety guards. No real network or pipeline
calls — we mock `pipeline.run` so the worker thread is a no-op."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Redirect the server's RUNS_DIR into a temp dir so tests don't pollute.
    import server
    server.RUNS_DIR = tmp_path / "runs"
    server.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    server.JOBS.clear()
    server._invalidate_history_cache()
    # Stub out the real pipeline.run so /api/run returns immediately.
    def fake_run(idea, out_dir, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "graph.html").write_text("<html></html>", encoding="utf-8")
        (out_dir / "report.md").write_text("# ok", encoding="utf-8")
        (out_dir / "graph.json").write_text('{"nodes":[],"edges":[]}', encoding="utf-8")
        return {"core": []}
    monkeypatch.setattr("main.run", fake_run, raising=True)
    return TestClient(server.app)


def test_safe_segment_rejects_traversal(client):
    import server
    with pytest.raises(Exception):
        server._safe_segment("..")
    with pytest.raises(Exception):
        server._safe_segment(".")
    with pytest.raises(Exception):
        server._safe_segment("../etc")
    # Valid ones pass through.
    assert server._safe_segment("graph.html") == "graph.html"
    assert server._safe_segment("aa9c50e9572f") == "aa9c50e9572f"


def test_run_rejects_concurrent_submission(client):
    """A second /api/run while the first is still in flight must be 409."""
    # Hold the first job in "running" by mocking the worker to be slow.
    import server
    import threading

    barrier = threading.Event()
    started = threading.Event()

    def slow_run(idea, out_dir, **kwargs):
        started.set()
        barrier.wait(timeout=5)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "graph.html").write_text("<html></html>", encoding="utf-8")
        return {"core": []}

    import main as pipeline
    real_run = pipeline.run
    pipeline.run = slow_run
    try:
        r1 = client.post("/api/run", json={"idea": "first", "data_source": "openalex"})
        assert r1.status_code == 200, r1.text
        # Wait until the worker is actually running.
        assert started.wait(2.0), "worker thread did not start"
        r2 = client.post("/api/run", json={"idea": "second", "data_source": "openalex"})
        assert r2.status_code == 409, r2.text
    finally:
        barrier.set()
        pipeline.run = real_run


def test_run_validates_data_source(client):
    r = client.post("/api/run", json={"idea": "x", "data_source": "bogus"})
    assert r.status_code == 400


def test_run_validates_idea_empty(client):
    r = client.post("/api/run", json={"idea": "   ", "data_source": "openalex"})
    assert r.status_code == 400


def test_run_validates_param_ranges(client):
    # Pydantic Field(ge=…) rejects out-of-range → 422 (validation error).
    r = client.post("/api/run", json={"idea": "x", "seed_count": 1})
    assert r.status_code == 422
    r = client.post("/api/run", json={"idea": "x", "max_citing": 999})
    assert r.status_code == 422


def test_runs_file_rejects_traversal(client, tmp_path):
    """GET /runs/../foo must 400, not serve a file outside RUNS_DIR."""
    r = client.get("/runs/..%2F..%2Fetc/passwd")
    assert r.status_code in (400, 404)


def test_safe_url_whitelists_schemes():
    """P0-3: only http/https schemes are allowed through to the client."""
    import server
    assert server._safe_url("https://example.com/paper.pdf") == "https://example.com/paper.pdf"
    assert server._safe_url("http://example.com/paper.pdf") == "http://example.com/paper.pdf"
    # javascript:, data:, file:, vbscript: must all be rejected.
    assert server._safe_url("javascript:alert(1)") == ""
    assert server._safe_url("data:text/html,<script>alert(1)</script>") == ""
    assert server._safe_url("file:///etc/passwd") == ""
    # Garbage input is harmless.
    assert server._safe_url("") == ""
    assert server._safe_url(None) == ""
    assert server._safe_url("not a url") == ""


def test_safe_doi_validates_prefix():
    """P0-3: DOIs must start with '10.' to be passed to doi.org."""
    import server
    assert server._safe_doi("10.1038/nature12373") == "10.1038/nature12373"
    assert server._safe_doi("  10.1038/nature12373  ") == "10.1038/nature12373"
    assert server._safe_doi("arxiv:1234.5678") == ""
    assert server._safe_doi("https://evil.com/10.x") == ""
    assert server._safe_doi("10.<script>") == ""
    assert server._safe_doi("") == ""
    assert server._safe_doi(None) == ""
