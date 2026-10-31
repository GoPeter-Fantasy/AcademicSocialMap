import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
import main as pipeline

app = FastAPI(title="学术社会地图")
RUNS_DIR = config.BASE_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()

# Require at least one non-dot character so ".." and "." are rejected.
_SEGMENT_RE = re.compile(r"^(?!\.)[A-Za-z0-9_](?:[A-Za-z0-9_\.\-]*[A-Za-z0-9_])?$")


def _safe_segment(s: str, *, max_len: int = 80) -> str:
    """Whitelist path-segment validation: letters, digits, _, ., - only.
    Rejects empty, '.', '..', and any value starting/ending with a dot to
    harden against path traversal. Covers job_id (uuid4 hex[:12]) and known
    run filenames (graph.html, etc.)."""
    if not s or len(s) > max_len or not _SEGMENT_RE.match(s):
        raise HTTPException(status_code=400, detail="invalid path segment")
    return s


def _resolve_under(base: Path, *parts: str) -> Path:
    p = (base.joinpath(*parts)).resolve()
    base_resolved = base.resolve()
    if p != base_resolved and base_resolved not in p.parents:
        raise HTTPException(status_code=400, detail="invalid path")
    return p


def _safe_url(url: str) -> str:
    """P0-3: allow only http/https schemes. Defends against javascript:/data:
    URLs leaking through from upstream data sources."""
    if not url or not isinstance(url, str):
        return ""
    try:
        u = urlparse(url)
    except Exception:
        return ""
    return url if u.scheme in ("http", "https") else ""


def _safe_doi(doi: str) -> str:
    """P0-3: accept only DOIs starting with the canonical '10.' prefix."""
    if not doi or not isinstance(doi, str):
        return ""
    d = doi.strip()
    if not d.startswith("10."):
        return ""
    # Reject whitespace and HTML-breaking characters; the doi.org URL
    # builder will URL-encode whatever passes this check.
    if any(c.isspace() or c in '<>"' for c in d):
        return ""
    return d


def _sanitize_paper(p: dict) -> dict:
    """P0-3: strip unsafe pdf_url / doi fields before returning to the client."""
    if not p:
        return p
    if "pdf_url" in p:
        p["pdf_url"] = _safe_url(p.get("pdf_url", ""))
    if "doi" in p:
        p["doi"] = _safe_doi(p.get("doi", ""))
    return p


class RunRequest(BaseModel):
    idea: str = Field(..., min_length=1, max_length=4000)
    data_source: str = Field("openalex")
    seed_count: int = Field(10, ge=3, le=20)
    query_count: int = Field(3, ge=1, le=5)
    per_query: int = Field(8, ge=3, le=15)
    max_citing: int = Field(20, ge=5, le=100)
    max_refs: int = Field(30, ge=5, le=200)


def _new_job() -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "status": "queued",
        "logs": [],
        "error": None,
        "out_dir": None,
        "started_at": None,
        "finished_at": None,
    }


def _has_active_run() -> bool:
    with LOCK:
        return any(j.get("status") in ("queued", "running") for j in JOBS.values())


def _run_worker(job_id: str, idea_text: str, data_source: str, params: dict) -> None:
    job = JOBS[job_id]
    out_dir = RUNS_DIR / job_id

    def emit(msg: str):
        with LOCK:
            job["logs"].append(msg)
            job["status"] = "running"

    try:
        job["status"] = "running"
        job["started_at"] = time.time()
        result = pipeline.run(
            idea_text, out_dir=out_dir, log=emit, data_source=data_source,
            seed_count=params.get("seed_count", 10),
            query_count=params.get("query_count", 3),
            per_query=params.get("per_query", 8),
            max_citing_per_seed=params.get("max_citing", 20),
            max_refs_per_seed=params.get("max_refs", 30),
        )
        with LOCK:
            job["out_dir"] = str(out_dir)
            job["status"] = "done"
            job["finished_at"] = time.time()
            job["summary"] = {
                "core_authors": [a["name"] for a in result["core"]],
                "html": f"/runs/{job_id}/graph.html",
                "report": f"/runs/{job_id}/report.md",
                "json": f"/runs/{job_id}/graph.json",
            }
            _persist_meta(job_id, idea_text, data_source, job, params)
    except Exception as e:
        with LOCK:
            job["status"] = "error"
            job["error"] = str(e)
            job["finished_at"] = time.time()
            _persist_meta(job_id, idea_text, data_source, job, params)


def _persist_meta(job_id: str, idea_text: str, data_source: str, job: dict, params: dict | None = None) -> None:
    """Write run metadata to disk so it survives server restarts."""
    meta = {
        "id": job_id,
        "idea": idea_text,
        "data_source": data_source,
        "params": params or {},
        "status": job["status"],
        "error": job.get("error"),
        "created_at": job.get("started_at") or time.time(),
        "finished_at": job.get("finished_at"),
        "elapsed": round((job.get("finished_at") or time.time()) - (job.get("started_at") or time.time()), 1)
        if job.get("started_at") else None,
        "summary": job.get("summary"),
    }
    try:
        (RUNS_DIR / job_id / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:
        pass


_HISTORY_CACHE: dict = {"entries": None, "expires_at": 0.0, "mtime": 0.0}
HISTORY_CACHE_TTL = 5.0


def _scan_history() -> list:
    entries = []
    if RUNS_DIR.exists():
        for d in sorted(RUNS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not d.is_dir():
                continue
            meta_path = d / "meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            else:
                meta = {}
            has_graph = (d / "graph.html").exists()
            has_report = (d / "report.md").exists()
            idea = meta.get("idea", "")
            created = meta.get("created_at")
            if not idea and (d / "graph.json").exists():
                try:
                    gdata = json.loads((d / "graph.json").read_text(encoding="utf-8"))
                    for n in gdata.get("nodes", []):
                        if n.get("id") == "IDEA":
                            idea = n.get("title", "")
                            break
                except Exception:
                    pass
            if created is None:
                try:
                    created = d.stat().st_mtime
                except Exception:
                    pass
            entries.append({
                "id": d.name,
                "idea": idea,
                "data_source": meta.get("data_source", "?"),
                "params": meta.get("params") or {},
                "status": meta.get("status", "done" if has_graph else "?"),
                "error": meta.get("error"),
                "created_at": created,
                "elapsed": meta.get("elapsed"),
                "summary": meta.get("summary") or {
                    "html": f"/runs/{d.name}/graph.html" if has_graph else None,
                    "report": f"/runs/{d.name}/report.md" if has_report else None,
                    "json": f"/runs/{d.name}/graph.json",
                },
            })
    return entries


@app.get("/api/history")
async def history():
    """List all past runs (newest first). In-memory TTL cache (5s) so the
    dashboard can poll without re-reading the runs dir every time."""
    now = time.time()
    try:
        dir_mtime = RUNS_DIR.stat().st_mtime if RUNS_DIR.exists() else 0.0
    except Exception:
        dir_mtime = 0.0
    cache = _HISTORY_CACHE
    if (
        cache["entries"] is not None
        and now < cache["expires_at"]
        and cache["mtime"] == dir_mtime
    ):
        return cache["entries"]
    entries = _scan_history()
    cache["entries"] = entries
    cache["expires_at"] = now + HISTORY_CACHE_TTL
    cache["mtime"] = dir_mtime
    return entries


def _invalidate_history_cache():
    _HISTORY_CACHE["entries"] = None
    _HISTORY_CACHE["expires_at"] = 0.0
    _HISTORY_CACHE["mtime"] = 0.0


@app.delete("/api/history/{job_id}")
async def delete_history(job_id: str):
    """Delete a past run's directory. Refuses to delete a run in progress."""
    job_id = _safe_segment(job_id, max_len=40)
    with LOCK:
        job = JOBS.get(job_id)
        if job and job.get("status") in ("running", "queued"):
            raise HTTPException(status_code=409, detail="任务运行中，无法删除")
    target = _resolve_under(RUNS_DIR, job_id)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="record not found")
    shutil.rmtree(target)
    with LOCK:
        JOBS.pop(job_id, None)
    _invalidate_history_cache()
    return {"ok": True}


@app.post("/api/run")
async def start_run(req: RunRequest):
    idea = req.idea.strip()
    data_source = (req.data_source or "openalex").strip().lower()
    if data_source not in ("s2", "openalex"):
        raise HTTPException(status_code=400, detail="data_source 必须是 s2 或 openalex")
    if not idea:
        raise HTTPException(status_code=400, detail="idea 不能为空")
    if _has_active_run():
        raise HTTPException(status_code=409, detail="已有任务运行中，请等待完成后再提交")
    params = {
        "seed_count": req.seed_count,
        "query_count": req.query_count,
        "per_query": req.per_query,
        "max_citing": req.max_citing,
        "max_refs": req.max_refs,
    }
    with LOCK:
        job = _new_job()
        job["data_source"] = data_source
        job["params"] = params
        JOBS[job["id"]] = job
    threading.Thread(target=_run_worker, args=(job["id"], idea, data_source, params), daemon=True).start()
    _invalidate_history_cache()
    return {"job_id": job["id"], "data_source": data_source}


@app.get("/api/status/{job_id}")
async def job_status(job_id: str):
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "status": job["status"],
            "data_source": job.get("data_source", "openalex"),
            "logs": job["logs"],
            "error": job["error"],
            "summary": job.get("summary"),
            "elapsed": round((job.get("finished_at") or time.time()) - (job.get("started_at") or time.time()), 1),
        }


@app.get("/api/paper/{work_id}")
async def paper_detail(work_id: str, data_source: str = "openalex"):
    """Paper detail incl. PDF link — used by the graph click panel."""
    if data_source not in ("s2", "openalex"):
        raise HTTPException(status_code=400, detail="data_source 必须是 s2 或 openalex")
    mod = pipeline.datasource.get_module(data_source)
    try:
        raw = mod.get_paper_detail(work_id)
        return _sanitize_paper(mod.work_summary(raw))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取论文详情失败: {str(e)[:200]}")


@app.get("/api/author/{author_id}")
async def author_detail(author_id: str, data_source: str = "openalex"):
    """Author's paper list incl. PDF links — used by the graph click panel."""
    if data_source not in ("s2", "openalex"):
        raise HTTPException(status_code=400, detail="data_source 必须是 s2 或 openalex")
    mod = pipeline.datasource.get_module(data_source)
    try:
        papers = mod.author_papers(author_id, limit=25)
        return [_sanitize_paper(mod.work_summary(p)) for p in papers]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取作者文献失败: {str(e)[:200]}")


@app.get("/api/dscheck")
async def ds_check():
    """Probe both data sources in parallel, single attempt each. Uses
    per-name module refs so the probe never mutates the pipeline's
    active backend."""
    import concurrent.futures
    import time as _time

    def probe(name: str):
        mod = pipeline.datasource.get_module(name)
        t0 = _time.time()
        try:
            result = mod.probe() if hasattr(mod, "probe") else {"ok": bool(mod.search_works("graph neural network", per_page=1))}
            result = dict(result)
            result.setdefault("latency_ms", round((_time.time() - t0) * 1000))
            result["key"] = bool((pipeline.config.S2_API_KEY if name == "s2" else pipeline.config.OPENALEX_API_KEY))
            return result
        except Exception as e:
            return {"ok": False, "latency_ms": round((_time.time() - t0) * 1000), "error": str(e)[:150]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f_s2 = ex.submit(probe, "s2")
        f_oa = ex.submit(probe, "openalex")
        return {"s2": f_s2.result(), "openalex": f_oa.result()}


@app.get("/", response_class=HTMLResponse)
async def index():
    html = (config.BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/runs/{job_id}/{filename}")
async def run_file(job_id: str, filename: str):
    job_id = _safe_segment(job_id)
    filename = _safe_segment(filename, max_len=40)
    path = _resolve_under(RUNS_DIR, job_id, filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")
