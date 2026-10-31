import argparse
import json
import re
from pathlib import Path
from typing import Callable

import config
import extractor
import graph_builder
import datasource
import reasoning
import report as report_mod
import visualize

LogFn = Callable[[str], None]

_IDEA_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")

_FALLBACK_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those",
    "into", "using", "are", "was", "were", "have", "has", "will", "would",
    "can", "could", "should", "their", "your", "our", "its", "not", "also",
    "more", "most", "some", "such", "than", "when", "where", "which", "who",
    "about", "between", "through", "under", "over", "after", "before", "how",
    "what", "why", "then", "there", "here",
}


def _fallback_concepts(idea_text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in _IDEA_TOKEN_RE.findall((idea_text or "").lower()):
        if t in _FALLBACK_STOPWORDS:
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= 5:
            break
    return out


def _title_match(work: dict, idea_terms: set[str]) -> bool:
    title = ((work.get("display_name") or work.get("title")) or "").lower()
    return any(t in title for t in idea_terms)


def _select_seeds(candidates: dict[str, dict], idea_terms: set[str]) -> list[dict]:
    """Prefer title-matched works (precise), fall back to abstract-matched."""
    ranked = sorted(
        candidates.values(),
        key=lambda w: (
            _title_match(w, idea_terms),
            graph_builder._score_relatedness(datasource.work_summary(w), idea_terms),
        ),
        reverse=True,
    )
    title_hits = [w for w in ranked if _title_match(w, idea_terms)]
    if len(title_hits) >= 5:
        return title_hits[:10]
    return ranked[:10]


def run(
    idea_text: str,
    out_dir: Path | None = None,
    max_citing_per_seed: int = 20,
    max_refs_per_seed: int = 30,
    seed_count: int = 10,
    query_count: int = 3,
    per_query: int = 8,
    log: LogFn | None = None,
    data_source: str | None = None,
) -> dict:
    if data_source is None:
        if datasource._BACKEND is None:
            backend = datasource.set_backend(config.DATA_SOURCE)
        else:
            backend = datasource.backend_name()
    else:
        backend = datasource.set_backend(data_source)
    def emit(msg: str):
        if log:
            log(msg)
        else:
            print(msg, flush=True)

    out_dir = out_dir or config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    seed_count = max(3, min(int(seed_count), 20))
    query_count = max(1, min(int(query_count), 5))
    per_query = max(3, min(int(per_query), 15))
    max_citing_per_seed = max(5, min(int(max_citing_per_seed), 100))
    max_refs_per_seed = max(5, min(int(max_refs_per_seed), 200))

    emit("[1/6] LLM 理解 idea...")
    idea = extractor.extract_idea(idea_text)
    idea["_text"] = idea_text
    idea["_data_source"] = data_source or backend
    if not idea.get("concepts") and not idea.get("methods"):
        idea["concepts"] = _fallback_concepts(idea_text)
    queries = idea.get("queries", [idea_text])[:query_count]
    emit(f"  方法: {[m['name'] for m in idea.get('methods', [])]}")
    emit(f"  概念: {idea.get('concepts', [])}")
    emit(f"  检索({len(queries)} 条): {queries}")

    emit(f"[2/6] {datasource.backend_name()} 检索种子论文...")
    idea_terms = {t.lower() for t in idea.get("concepts", [])[:5]}
    idea_terms.update(m["name"].lower() for m in idea.get("methods", [])[:5])
    candidates: dict[str, dict] = {}
    failed_queries = 0
    last_query_err: Exception | None = None
    max_candidates = max(seed_count * 3, 15)
    for q in queries:
        try:
            for w in datasource.search_works(q, per_page=per_query):
                wid = datasource.work_summary(w)["id"]
                candidates.setdefault(wid, w)
            if len(candidates) >= max_candidates:
                break
        except Exception as e:
            failed_queries += 1
            last_query_err = e
            emit(f"  ! 检索 '{q[:40]}' 失败: {str(e)[:80]}")
    if not candidates:
        snippet = f" 最近错误: {str(last_query_err)[:80]}" if last_query_err else ""
        raise RuntimeError(
            f"数据源 {datasource.backend_name()} 检索失败"
            f"（{failed_queries}/{len(queries)} 次尝试均失败）。"
            f"请稍后重试，或切换数据源（UI 下拉框）。{snippet}"
        )
    seed_works = _select_seeds(candidates, idea_terms)[:seed_count]
    relevant = [w for w in seed_works
                if graph_builder._score_relatedness(datasource.work_summary(w), idea_terms) > 0]
    if len(relevant) < 5:
        emit("  ! 相关种子不足 5 篇，保留原始检索结果")
        seed_works = sorted(
            candidates.values(),
            key=lambda w: graph_builder._score_relatedness(datasource.work_summary(w), idea_terms),
            reverse=True,
        )[:seed_count]
    emit(f"  种子论文 {len(seed_works)} 篇（相关 {len(relevant)} 篇）")

    emit("[3/6] 构建图谱（引用链 1 跳扩展）...")
    g = graph_builder.build_graph(
        idea, seed_works,
        max_citing_per_seed=max_citing_per_seed,
        max_refs_per_seed=max_refs_per_seed,
        workers=4,
        progress=emit,
    )
    emit(f"  节点 {g.number_of_nodes()} / 边 {g.number_of_edges()}")

    emit("[4/6] LLM 从摘要抽取方法...")
    paper_summaries = [
        data["summary"]
        for n, data in g.nodes(data=True)
        if data.get("kind") == "paper" and data.get("summary")
        and data.get("relatedness", 0) > 0.15
    ]
    method_map = extractor.extract_methods_from_abstracts(paper_summaries, log=log)
    emit(f"  {len(method_map)} 篇论文抽到方法")

    emit("[5/6] 推理：核心人物 / 引用网络 / 方法谱系...")
    core = reasoning.core_authors(g, top=5)
    citations = reasoning.citation_network(g, top_n=10)
    methods = reasoning.method_genealogy(g, method_map)
    gaps = reasoning.coverage_gaps(g, idea)
    emit(f"  核心人物: {[a['name'] for a in core]}")

    emit("[6/6] 输出...")
    g_json = nx_to_dict(g)
    (out_dir / "graph.json").write_text(json.dumps(g_json, ensure_ascii=False, indent=1), encoding="utf-8")
    method_to_papers = {name: entry["papers"] for name, entry in methods.items()}
    html_path = visualize.render_html(g, out_dir / "graph.html", methods=method_to_papers)
    md_path = report_mod.write_report(
        out_dir / "report.md", idea_text, idea, g, seed_works, core, citations, methods, gaps,
    )
    emit(f"  图谱 HTML: {html_path}")
    emit(f"  报告 MD:   {md_path}")
    emit("DONE")

    return {"idea": idea, "graph": g, "core": core, "report": md_path, "html": html_path}


def nx_to_dict(g) -> dict:
    return {
        "nodes": [{"id": n, **d} for n, d in g.nodes(data=True)],
        "edges": [{"source": u, "target": v, **d} for u, v, d in g.edges(data=True)],
    }


def main():
    ap = argparse.ArgumentParser(description="Academic Social Map MVP")
    ap.add_argument("idea", help="研究 idea 文本")
    ap.add_argument("--out", type=Path, default=None, help="输出目录（默认 output/）")
    ap.add_argument("--max-citing", type=int, default=20)
    ap.add_argument("--max-refs", type=int, default=30)
    ap.add_argument("--seeds", type=int, default=10, help="种子论文数量（3-20）")
    ap.add_argument("--queries", type=int, default=3, help="智能搜索 query 数量（1-5）")
    ap.add_argument("--per-query", type=int, default=8, help="每个 query 检索篇数（3-15）")
    ap.add_argument("--data-source", dest="data_source", default=None,
                    choices=("openalex", "s2"), help="数据源（openalex / s2，默认走 config）")
    args = ap.parse_args()
    run(args.idea, args.out, args.max_citing, args.max_refs,
        seed_count=args.seeds, query_count=args.queries, per_query=args.per_query,
        data_source=args.data_source)


if __name__ == "__main__":
    main()
