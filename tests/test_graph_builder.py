"""Tests for graph_builder helpers."""
import graph_builder


def test_score_relatedness_title_higher_than_abstract():
    work = {
        "display_name": "Foo",
        "title": "Foo",
        "abstract": "bar baz qux",
    }
    terms = {"foo", "bar"}
    # Title hit + abstract hit = 2; ratio = 2/2 = 1.0
    s1 = graph_builder._score_relatedness(work, terms)
    # No title hit, only abstract hit = 1/2 = 0.5
    work2 = {**work, "display_name": "X", "title": "X"}
    s2 = graph_builder._score_relatedness(work2, terms)
    assert s1 > s2


def test_score_relatedness_zero_when_no_overlap():
    work = {"title": "completely unrelated paper", "abstract": "nothing matches"}
    terms = {"lumped", "mass", "modeling"}
    assert graph_builder._score_relatedness(work, terms) == 0.0


def test_norm_id_strips_url_prefix():
    assert graph_builder._norm_id("https://openalex.org/W123") == "W123"
    assert graph_builder._norm_id("W123") == "W123"
    assert graph_builder._norm_id(42) == "42"


def test_collaborations_requires_shared_papers():
    from graph_builder import _collaborations
    papers = {
        "P1": {"authors": [{"id": "A1"}, {"id": "A2"}]},
        "P2": {"authors": [{"id": "A1"}, {"id": "A2"}]},
        "P3": {"authors": [{"id": "A1"}, {"id": "A3"}]},  # one shared paper with A3
    }
    # frozenset pair order is undefined — compare as sets of frozensets.
    pairs = {frozenset(p) for p in _collaborations(papers)}
    assert frozenset({"A1", "A2"}) in pairs
    assert frozenset({"A1", "A3"}) not in pairs, "single coauthorship must not register"


def test_build_graph_adds_seed_ref_cites_edges(monkeypatch):
    """S2-style summaries carry no referenced_works; seed→ref cites edges must
    still be created from the (seed_id, ref_id) links recorded during reference
    fetching (regression for the S2 backend)."""
    import datasource

    seed = {"id": "S1", "title": "Seed", "year": 2020, "cited_by_count": 10,
            "authors": [{"id": "A1", "name": "Alice"}], "abstract": "", "referenced_works": []}
    ref = {"id": "R1", "title": "Ref", "year": 2018, "cited_by_count": 50,
           "authors": [{"id": "A2", "name": "Bob"}], "abstract": "", "referenced_works": []}

    monkeypatch.setattr(datasource, "work_summary", lambda w: w)
    monkeypatch.setattr(datasource, "citing_works", lambda wid, per_page: [])
    monkeypatch.setattr(datasource, "referenced_works", lambda work, max_ids: [ref])
    monkeypatch.setattr(datasource, "get_work", lambda wid: seed)

    idea = {"concepts": ["seed"], "methods": [], "_text": "seed idea", "_data_source": "s2"}
    g = graph_builder.build_graph(idea, [seed], max_citing_per_seed=5, max_refs_per_seed=5)
    assert g.has_edge("S1", "R1")
    assert g.edges["S1", "R1"]["kind"] == "cites"


def test_citing_edges_only_point_to_source_seed(monkeypatch):
    """Regression for P0-1: a citing paper fetched for seed S must ONLY get a
    cites edge to S, not to every other seed in the run."""
    import datasource

    s1 = {"id": "S1", "title": "Seed one", "year": 2020, "cited_by_count": 100,
          "authors": [], "abstract": "", "referenced_works": []}
    s2 = {"id": "S2", "title": "Seed two", "year": 2019, "cited_by_count": 80,
          "authors": [], "abstract": "", "referenced_works": []}

    # C1 cites S1 only; C2 cites S2 only. Neither cites the other seed.
    c1 = {"id": "C1", "title": "Cites S1", "year": 2021, "cited_by_count": 5,
          "authors": [], "abstract": "", "referenced_works": []}
    c2 = {"id": "C2", "title": "Cites S2", "year": 2022, "cited_by_count": 4,
          "authors": [], "abstract": "", "referenced_works": []}

    monkeypatch.setattr(datasource, "work_summary", lambda w: w)
    monkeypatch.setattr(datasource, "get_work", lambda wid: s1 if wid == "S1" else s2)
    monkeypatch.setattr(datasource, "referenced_works", lambda work, max_ids: [])

    def fake_citing(wid, per_page):
        if wid == "S1":
            return [c1]
        if wid == "S2":
            return [c2]
        return []

    monkeypatch.setattr(datasource, "citing_works", fake_citing)

    idea = {"concepts": ["neural"], "methods": [], "_text": "idea", "_data_source": "s2"}
    g = graph_builder.build_graph(
        idea, [s1, s2],
        max_citing_per_seed=10, max_refs_per_seed=5,
        top_citing=10, top_refs=5,
    )
    assert g.has_node("C1")
    assert g.has_node("C2")
    # C1 cites only S1, not S2.
    assert g.has_edge("C1", "S1")
    assert not g.has_edge("C1", "S2"), "C1 must NOT cite S2 (P0-1 regression)"
    # C2 cites only S2, not S1.
    assert g.has_edge("C2", "S2")
    assert not g.has_edge("C2", "S1"), "C2 must NOT cite S1 (P0-1 regression)"


def test_tokens_word_boundary_prevents_substring_false_positives():
    """Regression for P0-4: substring 'net' must NOT match 'internet'."""
    from graph_builder import _tokens
    text = "internet protocols survey"
    toks = _tokens(text)
    assert "internet" in toks
    assert "protocols" in toks
    assert "net" not in toks, "'net' alone must not be a token of 'internet'"


def test_score_relatedness_uses_word_boundary_not_substring():
    """P0-4: idea term 'net' must not match a paper about internet protocols."""
    work = {"title": "Internet protocols survey", "abstract": "We study HTTP and TCP."}
    terms = {"net"}
    assert graph_builder._score_relatedness(work, terms) == 0.0
    # The same idea term as a phrase, properly tokenized, still matches via overlap.
    work2 = {"title": "Network analysis", "abstract": "We study graph neural networks."}
    assert graph_builder._score_relatedness(work2, {"networks", "graph"}) > 0
