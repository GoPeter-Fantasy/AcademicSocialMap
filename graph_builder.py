import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import networkx as nx

import datasource

ProgressFn = Callable[[str], None]


def _norm_id(x: Any) -> str:
    if isinstance(x, str):
        return x.rsplit("/", 1)[-1]
    return str(x)


_TOKEN_RE = re.compile(r"[a-z][a-z0-9\-]{2,}")


def _tokens(text: str) -> set[str]:
    """Tokenize text for relatedness / gap matching.

    Uses word-boundary regex (not substring) so 'net' doesn't match 'internet'.
    Output is lowercase. Tokens shorter than 3 chars are not produced by the
    regex — acronyms like 'GNN' (3 chars) are preserved."""
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower())}


def _score_relatedness(work: dict, idea_terms: set[str]) -> float:
    """Heuristic relatedness: token overlap of title+abstract with idea concepts/methods.

    Uses word-boundary tokenization (not substring) so 'net' doesn't match
    'internet' and short tokens don't false-positive."""
    if not idea_terms:
        return 0.0
    text_tokens = _tokens(" ".join([
        work.get("display_name") or "",
        work.get("title") or "",
        work.get("abstract") or "",
    ]))
    if not text_tokens:
        return 0.0
    hits = sum(1 for t in idea_terms if t in text_tokens)
    return hits / len(idea_terms)


# Graph size guards (P0-6): keep `summary` blobs bounded so the rendered
# HTML/JSON stays small enough for the browser.
MAX_AUTHORS_PER_PAPER = 8
MAX_REFERENCED_WORKS_IN_SUMMARY = 15
MAX_PAPER_ABSTRACT_LEN = 1500
MAX_TOTAL_PAPERS = 200


def _truncate_summary(work: dict) -> dict:
    """Cap summary fields so the rendered graph HTML/JSON stays bounded.

    The raw dict is mutated in-place by callers, so we return the same object
    after truncating. This keeps the change observable by later code paths."""
    if not work:
        return work
    authors = work.get("authors") or []
    if len(authors) > MAX_AUTHORS_PER_PAPER:
        work["authors"] = authors[:MAX_AUTHORS_PER_PAPER]
    refs = work.get("referenced_works") or []
    if isinstance(refs, list) and len(refs) > MAX_REFERENCED_WORKS_IN_SUMMARY:
        work["referenced_works"] = refs[:MAX_REFERENCED_WORKS_IN_SUMMARY]
    abstract = work.get("abstract") or ""
    if len(abstract) > MAX_PAPER_ABSTRACT_LEN:
        work["abstract"] = abstract[:MAX_PAPER_ABSTRACT_LEN]
    return work


def build_graph(
    idea: dict,
    seed_works: list[dict],
    max_citing_per_seed: int = 30,
    max_refs_per_seed: int = 40,
    top_citing: int = 25,
    top_refs: int = 25,
    progress: ProgressFn | None = None,
    workers: int = 1,
) -> nx.DiGraph:
    """
    Build the idea-centered graph:
      - seed papers (nodes)
      - papers citing seeds (1-hop in, pruned by relatedness)
      - papers cited by seeds (1-hop out)
      - authors of all papers (nodes)
      - edges: cites / authored_by / collaborates
    Paper summaries (incl. abstract) are stored in node attributes as `summary`.
    """
    def log(msg: str):
        if progress:
            progress(msg)

    g = nx.DiGraph()
    idea_terms = set()
    for t in idea.get("concepts", [])[:5]:
        idea_terms.update(_tokens(t))
    for m in idea.get("methods", [])[:5]:
        idea_terms.update(_tokens(m.get("name", "")))

    g.add_node("IDEA", kind="idea", title=idea.get("_text", "Idea")[:200],
               size=40, color="#e6194b", data_source=idea.get("_data_source", ""))

    all_papers: dict[str, dict] = {}
    raw_by_id: dict[str, dict] = {}
    for sw in seed_works:
        s = _truncate_summary(datasource.work_summary(sw))
        all_papers[s["id"]] = s
        raw_by_id[s["id"]] = sw
    seed_ids = set(all_papers)

    citing_pool: list[dict] = []

    def fetch_citing(seed_id: str) -> tuple[str, list[dict]]:
        try:
            papers = [datasource.work_summary(w)
                      for w in datasource.citing_works(seed_id, max_citing_per_seed)]
            return seed_id, [_truncate_summary(p) for p in papers]
        except Exception as e:
            log(f"  ! citing {seed_id} failed: {e}")
            return seed_id, []

    def fetch_refs(seed_id: str) -> tuple[str, list[dict]]:
        try:
            raw = raw_by_id.get(seed_id)
            if raw is None:
                raw = datasource.get_work(seed_id)
            papers = [datasource.work_summary(w)
                      for w in datasource.referenced_works(raw, max_refs_per_seed)]
            return seed_id, [_truncate_summary(p) for p in papers]
        except Exception as e:
            log(f"  ! refs {seed_id} failed: {e}")
            return seed_id, []

    seeds = list(seed_ids)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut_citing = {ex.submit(fetch_citing, sid): sid for sid in seeds}
        fut_refs = {ex.submit(fetch_refs, sid): sid for sid in seeds}
        done_citing = 0
        # Maps each citing paper id -> the set of seed ids it actually cites.
        # Replaces the old "every kept citing paper cites every seed" bug (P0-1).
        seed_to_citing: dict[str, set[str]] = defaultdict(set)
        for fut in as_completed(fut_citing):
            done_citing += 1
            src_seed, papers = fut.result()
            for p in papers:
                citing_pool.append(p)
                seed_to_citing[src_seed].add(_norm_id(p["id"]))
            log(f"  引用拉取 {done_citing}/{len(seeds)} 篇种子")
        done_refs = 0
        ref_pool: list[dict] = []
        ref_links: list[tuple[str, str]] = []
        for fut in as_completed(fut_refs):
            done_refs += 1
            seed_id, refs = fut.result()
            ref_pool.extend(refs)
            for r in refs:
                ref_links.append((seed_id, _norm_id(r["id"])))
            log(f"  参考文献拉取 {done_refs}/{len(seeds)} 篇种子")

    for c in citing_pool:
        all_papers[c["id"]] = c
    for r in ref_pool:
        all_papers[r["id"]] = r
    citing_pool_ids = {_norm_id(p["id"]) for p in citing_pool}
    ref_pool_ids = {_norm_id(p["id"]) for p in ref_pool}

    rel_scores = {
        _norm_id(p["id"]): score
        for p, score in (
            sorted(
                ((p, _score_relatedness(p, idea_terms)) for p in citing_pool),
                key=lambda x: x[1],
                reverse=True,
            )
            + sorted(
                ((p, _score_relatedness(p, idea_terms)) for p in ref_pool),
                key=lambda x: x[1],
                reverse=True,
            )
        )
    }
    keep_citing = {
        _norm_id(p["id"]) for p, _ in
        sorted(((p, rel_scores.get(_norm_id(p["id"]), 0)) for p in citing_pool),
               key=lambda x: x[1], reverse=True)[:top_citing]
    }
    keep_refs = {
        _norm_id(p["id"]) for p, _ in
        sorted(((p, rel_scores.get(_norm_id(p["id"]), 0)) for p in ref_pool),
               key=lambda x: x[1], reverse=True)[:top_refs]
    }

    for pid, p in all_papers.items():
        if pid not in seed_ids:
            if pid in citing_pool_ids and pid not in keep_citing:
                continue
            if pid in ref_pool_ids and pid not in keep_refs:
                continue
        role = "seed" if pid in seed_ids else ("citing" if pid in citing_pool_ids else "ref")
        g.add_node(pid, kind="paper", title=p.get("title", "")[:200],
                   year=p.get("year"), cited_by=p.get("cited_by_count", 0), size=18,
                   relatedness=rel_scores.get(pid, 1.0 if pid in seed_ids else 0.0),
                   role=role,
                   summary=p)

    # P0-6: bound total paper count so the rendered graph doesn't blow up the
    # browser. Seeds are always kept; if there are too many other papers we
    # prune by lowest relatedness first.
    paper_nodes = [n for n, d in g.nodes(data=True) if d.get("kind") == "paper"]
    non_seed_papers = [n for n in paper_nodes if n not in seed_ids]
    if len(paper_nodes) > MAX_TOTAL_PAPERS:
        overflow = len(paper_nodes) - MAX_TOTAL_PAPERS
        ranked = sorted(
            non_seed_papers,
            key=lambda n: g.nodes[n].get("relatedness", 0.0),
        )
        for n in ranked[:overflow]:
            g.remove_node(n)

    for pid in seed_ids:
        if g.has_node(pid):
            g.add_edge("IDEA", pid, kind="seed")

    # Only add a cites edge for the actual (seed, citing_paper) pairs returned
    # by the API. A citing paper fetched for seed S must NOT be connected to
    # any other seed T just because T happens to be in the seed set.
    for src_seed, citing_pids in seed_to_citing.items():
        for pid in citing_pids & keep_citing:
            if g.has_node(pid) and g.has_node(src_seed):
                g.add_edge(pid, src_seed, kind="cites")

    for pid, p in list(all_papers.items()):
        if not g.has_node(pid):
            continue
        for ref in p.get("referenced_works", []):
            if ref in g:
                g.add_edge(pid, ref, kind="cites")

    for seed_id, ref_id in ref_links:
        if g.has_node(seed_id) and g.has_node(ref_id):
            g.add_edge(seed_id, ref_id, kind="cites")

    for pid, p in all_papers.items():
        if not g.has_node(pid):
            continue
        for a in p.get("authors", []):
            aid = _norm_id(a.get("id"))
            if not aid:
                continue
            g.add_node(aid, kind="author", title=a.get("name", aid),
                       institution=a.get("institution", ""), size=12)
            g.add_edge(aid, pid, kind="authored_by")

    for a1, a2 in _collaborations(all_papers):
        if g.has_node(a1) and g.has_node(a2):
            g.add_edge(a1, a2, kind="collaborates")

    return g


def _collaborations(all_papers: dict[str, dict]) -> list[tuple[str, str]]:
    """Author A collaborates with B if they share >= 2 papers together."""
    authors_of_paper: dict[str, list[str]] = {}
    for pid, p in all_papers.items():
        aids = [_norm_id(a.get("id")) for a in p.get("authors", [])]
        aids = [a for a in aids if a]
        if aids:
            authors_of_paper[pid] = aids

    shared_count: dict[frozenset, int] = defaultdict(int)
    for pid, aids in authors_of_paper.items():
        unique = sorted(set(aids))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                shared_count[frozenset((unique[i], unique[j]))] += 1

    pairs = []
    for pair, count in shared_count.items():
        if count >= 2 and len(pair) == 2:
            a1, a2 = tuple(pair)
            pairs.append((a1, a2))
    return pairs
