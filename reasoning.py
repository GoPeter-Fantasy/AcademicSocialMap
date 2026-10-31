from collections import defaultdict

import networkx as nx

from graph_builder import _tokens


def core_authors(g: nx.DiGraph, top: int = 5, min_relatedness: float = 0.05) -> list[dict]:
    """Rank authors by citation impact inside the subgraph + degree centrality.
    Only counts papers that are seeds or that cite seeds (role in {"seed", "citing"}),
    so classic high-cited background references (e.g. PRISMA, U-Net, BioBERT) don't dominate.

    Two-tier ranking:
      1. multi-paper authors (paper_count >= 2) rank above single-paper authors
      2. within each tier: sort by (subgraph_citations, degree) desc

    The top-N authors' representative papers are deduplicated: if author X's
    highest-cited paper is already used by a higher-ranked author, we pick
    X's next-highest-cited unused paper. This avoids the situation where 5/5
    core authors all share the same "代表作" (e.g., a 50-coauthor review).
    """
    authors = [n for n, d in g.nodes(data=True) if d.get("kind") == "author"]
    author_papers: dict[str, list[str]] = defaultdict(list)
    for a, p, _d in g.edges(data=True):
        if g.nodes[a].get("kind") == "author" and g.nodes[p].get("kind") == "paper":
            author_papers[a].append(p)

    scores: list[dict] = []
    for a in authors:
        papers = author_papers.get(a, [])
        relevant = [p for p in papers
                    if g.nodes[p].get("role") in ("seed", "citing")
                    and g.nodes[p].get("relatedness", 0) >= min_relatedness]
        if not relevant:
            continue
        in_sub_cites = sum(g.nodes[p].get("cited_by", 0) for p in relevant)
        centrality = g.degree(a)
        relevant_sorted = sorted(relevant, key=lambda p: g.nodes[p].get("cited_by", 0), reverse=True)
        scores.append({
            "author_id": a,
            "name": g.nodes[a].get("title", a),
            "institution": g.nodes[a].get("institution", ""),
            "paper_count": len(relevant),
            "subgraph_citations": in_sub_cites,
            "degree": centrality,
            "_relevant_sorted": relevant_sorted,
        })

    # Two-tier sort: multi-paper authors always rank above single-paper authors.
    multi_paper = sorted(
        [s for s in scores if s["paper_count"] >= 2],
        key=lambda x: (x["subgraph_citations"], x["degree"]),
        reverse=True,
    )
    single_paper = sorted(
        [s for s in scores if s["paper_count"] < 2],
        key=lambda x: (x["subgraph_citations"], x["degree"]),
        reverse=True,
    )
    scores = multi_paper + single_paper

    out: list[dict] = []
    used_paper_ids: set[str] = set()
    for s in scores:
        if len(out) >= top:
            break
        chosen = None
        for pid in s["_relevant_sorted"]:
            if pid not in used_paper_ids:
                chosen = pid
                break
        if chosen is None:
            # Every paper this author has already appears in a higher-ranked
            # author's top slot. Don't fake a duplicate — mark as None so the
            # UI can show "—" instead of misleading the reader.
            s["top_paper"] = None
            s["top_paper_citations"] = 0
            s.pop("_relevant_sorted", None)
            out.append(s)
            continue
        used_paper_ids.add(chosen)
        s["top_paper"] = g.nodes[chosen].get("title") if chosen else None
        s["top_paper_citations"] = g.nodes[chosen].get("cited_by", 0) if chosen else 0
        s.pop("_relevant_sorted", None)
        out.append(s)
    return out


def citation_network(g: nx.DiGraph, top_n: int = 10) -> list[dict]:
    """Who cites whom, restricted to the highest-cited seeds and citing works."""
    papers = [n for n, d in g.nodes(data=True)
              if d.get("kind") == "paper" and d.get("role") in ("seed", "citing")]
    top = sorted(papers, key=lambda p: g.nodes[p].get("cited_by", 0), reverse=True)[:top_n]
    edges = []
    for e in g.edges(data=True):
        src, dst = e[0], e[1]
        if e[2].get("kind") == "cites" and src in top and dst in top:
            edges.append({
                "from": g.nodes[src].get("title", src)[:100],
                "to": g.nodes[dst].get("title", dst)[:100],
                "year_from": g.nodes[src].get("year"),
                "year_to": g.nodes[dst].get("year"),
            })
    return edges


def method_genealogy(g: nx.DiGraph, methods: dict[str, list[dict]]) -> dict[str, dict]:
    """Build method -> papers -> who uses them, with confidence labels."""
    paper_methods: dict[str, list[dict]] = {}
    for pid, ms in methods.items():
        if g.has_node(pid):
            paper_methods[pid] = ms

    by_name: dict[str, dict] = {}
    for pid, ms in paper_methods.items():
        for m in ms:
            name = m["name"]
            entry = by_name.setdefault(name, {
                "name": name,
                "papers": [],
                "confidence": m["confidence"],
                "max_confidence": m["confidence"],
            })
            entry["papers"].append(pid)
            entry["max_confidence"] = max(entry["max_confidence"], m["confidence"])
    return by_name


_GAP_STOPWORDS = {
    "a", "an", "the", "of", "for", "and", "or", "in", "on", "to",
    "with", "by", "is", "are", "be", "as", "at", "from", "into", "that",
}


def _gap_match(query: str, haystack_tokens: set[str]) -> bool:
    """Match query as a token-set (all meaningful tokens present, order-insensitive).

    Single-word queries still use the same tokenization so 'GNN' matches 'gnn-based'
    but 'net' won't false-positive on 'internet'. Light plural normalization
    (strip trailing 's') so 'networks' matches 'network' AND vice versa. Short
    tokens (<=4 chars, e.g. acronyms like GNN) also match a haystack token that
    starts with the query followed by '-' (e.g. 'gnn-based')."""
    q_tokens = _tokens(query)
    if not q_tokens:
        return False
    for t in q_tokens:
        if t in haystack_tokens:
            continue
        if t.endswith("s") and len(t) > 4 and t[:-1] in haystack_tokens:
            continue
        # Short acronym fallback: allow prefix matching with '-' separator
        # (gnn → gnn-based). Only for tokens ≤4 chars to avoid false positives
        # like 'meth' → 'method'.
        if len(t) <= 4:
            prefix = f"{t}-"
            if any(h.startswith(prefix) for h in haystack_tokens):
                continue
        return False
    return True


def coverage_gaps(g: nx.DiGraph, idea: dict) -> list[str]:
    """Suggest directions that may be under-covered, from the idea's own concepts.
    Checks whether any paper in the subgraph mentions the method/concept in title or abstract.
    Multi-word queries use token-set matching (order-insensitive) to avoid false positives
    like 'lumped mass modeling' being reported as missing when 'lumped mass' appears."""
    paper_tokens: set[str] = set()
    for n, d in g.nodes(data=True):
        if d.get("kind") == "paper":
            title = d.get("title", "")
            summ = d.get("summary") or {}
            abstract = summ.get("abstract", "")
            paper_tokens |= _tokens(title + " " + abstract)

    gaps = []
    for m in idea.get("methods", []):
        name = m["name"]
        if name and m.get("confidence", 0) >= 0.6 and not _gap_match(name, paper_tokens):
            gaps.append(f"method '{name}' is not mentioned in any subgraph paper")
    for c in idea.get("concepts", [])[:5]:
        if c and len(c.split()) >= 2 and not _gap_match(c, paper_tokens):
            gaps.append(f"concept '{c}' has no paper mentioning it in the subgraph")
    return gaps
