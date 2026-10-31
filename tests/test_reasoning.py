"""Tests for reasoning helpers: core_authors ranking, coverage_gaps matching."""
import networkx as nx

import reasoning


def _make_graph(papers):
    """Build a graph with papers, each tagged role=seed/citing and cited_by."""
    g = nx.DiGraph()
    for pid, attrs in papers.items():
        g.add_node(pid, kind="paper", **attrs)
    return g


def test_core_authors_two_tier_multi_paper_first():
    """Multi-paper authors must rank above single-paper authors even when the
    single-paper author has higher raw citation totals (the regression that
    caused 5/5 core authors to share one review)."""
    g = nx.DiGraph()
    # Three multi-paper authors (each with 2 papers, moderate citations).
    multi = {
        ("A1", "P1"): 200, ("A1", "P2"): 100,
        ("A2", "P3"): 180, ("A2", "P4"): 90,
        ("A3", "P5"): 150, ("A3", "P6"): 80,
    }
    # One single-paper author on a massive review.
    g.add_node("P1", kind="paper", role="seed", cited_by=200, relatedness=0.5, title="P1")
    g.add_node("P2", kind="paper", role="citing", cited_by=100, relatedness=0.5, title="P2")
    g.add_node("P3", kind="paper", role="seed", cited_by=180, relatedness=0.5, title="P3")
    g.add_node("P4", kind="paper", role="citing", cited_by=90, relatedness=0.5, title="P4")
    g.add_node("P5", kind="paper", role="seed", cited_by=150, relatedness=0.5, title="P5")
    g.add_node("P6", kind="paper", role="citing", cited_by=80, relatedness=0.5, title="P6")
    # Single-paper author on a 5000-citation review.
    g.add_node("PREV", kind="paper", role="seed", cited_by=5000, relatedness=0.5, title="PREV")
    for author, paper in multi:
        g.add_node(author, kind="author", title=author)
        g.add_edge(author, paper, kind="authored_by")
    g.add_node("SOLO", kind="author", title="SOLO")
    g.add_edge("SOLO", "PREV", kind="authored_by")

    top = reasoning.core_authors(g, top=5)
    names = [a["name"] for a in top]
    assert "SOLO" not in names[:3], "single-paper author must not rank above multi-paper authors"
    assert names[0] == "A1", "multi-paper author with highest citations must rank first"
    # Representative papers must be unique across the top 5.
    rep_papers = [a["top_paper"] for a in top]
    assert len(set(rep_papers)) == len(rep_papers), f"duplicate rep papers: {rep_papers}"


def test_core_authors_dedup_representative_paper():
    """Two authors sharing the same top paper must not both claim it. When
    a lower-ranked author has no unused paper left, top_paper must be None
    (rather than fabricating a duplicate)."""
    g = nx.DiGraph()
    g.add_node("P1", kind="paper", role="seed", cited_by=300, relatedness=0.5, title="Shared")
    g.add_node("P2", kind="paper", role="seed", cited_by=100, relatedness=0.5, title="Other")
    g.add_node("A1", kind="author", title="A1")
    g.add_node("A2", kind="author", title="A2")
    g.add_edge("A1", "P1", kind="authored_by")
    g.add_edge("A1", "P2", kind="authored_by")
    g.add_edge("A2", "P1", kind="authored_by")
    top = reasoning.core_authors(g, top=2)
    # A1 (highest) gets its top paper; A2's only paper is already used →
    # top_paper must be None rather than a duplicate of A1's claim.
    assert top[0]["top_paper"] in ("Shared", "Other")
    assert top[1]["top_paper"] is None, "duplicate top_paper must be suppressed (set to None)"


def _toks(s: str) -> set[str]:
    """Tokenize the haystack the way coverage_gaps does (post-P0-5)."""
    from graph_builder import _tokens
    return _tokens(s)


def test_gap_match_token_set_prevents_false_negative():
    """Multi-word query should match when ALL meaningful tokens are present,
    even if the exact phrase isn't (order-insensitive)."""
    haystack = _toks("We propose a new lumped mass technique for cleanroom resonators.")
    # "lumped mass" (both tokens present) → True
    assert reasoning._gap_match("lumped mass", haystack) is True
    # Adding "modeling" — which isn't in the haystack — should be False
    # (this proves the test would catch a naive substring regression).
    assert reasoning._gap_match("lumped mass modeling", haystack) is False


def test_gap_match_handles_acronyms_and_punctuation():
    """P0-5 regression: token-based matching handles punctuation and acronyms
    that broke the old split()-based implementation."""
    # Old impl would split on whitespace → "networks," would never equal "networks"
    haystack = _toks("We study graph neural networks, including GNN-based methods.")
    assert reasoning._gap_match("neural networks", haystack) is True
    # GNN acronym (3 chars) is preserved by the tokenizer and matches.
    assert reasoning._gap_match("GNN", haystack) is True


def test_gap_match_handles_simple_plurals():
    """P0-5: 'networks' should match a haystack containing 'network'."""
    haystack = _toks("We propose a new graph neural network for molecules.")
    assert reasoning._gap_match("neural networks", haystack) is True


def test_gap_match_word_boundary_no_substring():
    """P0-5: 'net' must not match a haystack containing 'internet'."""
    haystack = _toks("An internet protocols survey over HTTP and TCP.")
    assert reasoning._gap_match("net", haystack) is False


def test_gap_match_single_word_substring():
    """Single-word query uses token matching (case-insensitive) so 'GNN'
    matches 'gnn-based model' but not 'engine'."""
    haystack1 = _toks("deep neural network for graphs")
    haystack2 = _toks("we introduce a GNN-based model")
    haystack3 = _toks("deep neural network for graphs")
    assert reasoning._gap_match("GNN", haystack1) is False
    assert reasoning._gap_match("GNN", haystack2) is True
    assert reasoning._gap_match("engine", haystack3) is False


def test_gap_match_stopword_handling():
    """Stop words in the query should not block a match."""
    haystack = _toks("we propose a new clustering method for medical images")
    assert reasoning._gap_match("method for clustering of images", haystack) is True


def test_coverage_gaps_filters_low_confidence():
    """Methods below the confidence threshold must not be reported as gaps."""
    g = nx.DiGraph()
    g.add_node("P1", kind="paper", title="Foo", summary={"abstract": "bar baz"})
    idea = {"methods": [
        {"name": "unrelated niche method", "confidence": 0.9},
        {"name": "another niche method", "confidence": 0.3},
    ], "concepts": []}
    gaps = reasoning.coverage_gaps(g, idea)
    assert any("unrelated niche method" in g for g in gaps)
    assert not any("another niche method" in g for g in gaps), "low-confidence methods should not be flagged"


def test_citation_network_top_n_window():
    """Citation network restricts to top-N nodes by cited_by."""
    g = nx.DiGraph()
    for i, c in enumerate([1000, 800, 5, 5, 5]):
        g.add_node(f"P{i}", kind="paper", role="seed", cited_by=c, title=f"P{i}", year=2020)
    g.add_edge("P0", "P1", kind="cites")
    g.add_edge("P2", "P3", kind="cites")
    edges = reasoning.citation_network(g, top_n=3)
    srcs = {(e["from"], e["to"]) for e in edges}
    # Only P0 and P1 are in top 3; P2/P3/P4 are not.
    assert ("P0", "P1") in srcs
    assert ("P2", "P3") not in srcs
