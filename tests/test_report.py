"""Tests for the Markdown report writer (no network calls)."""
from pathlib import Path

import networkx as nx

import report


def test_write_report_contains_six_sections(tmp_path):
    g = nx.DiGraph()
    g.add_node("IDEA", kind="idea", title="the idea", size=40, data_source="openalex")
    g.add_node("P1", kind="paper", title="A paper", year=2020, cited_by=10, role="seed", summary={"abstract": "x"})
    g.add_node("P2", kind="paper", title="Another", year=2021, cited_by=20, role="citing", summary={"abstract": "y"})
    g.add_edge("IDEA", "P1", kind="seed")
    g.add_edge("P1", "P2", kind="cites")
    g.add_node("A1", kind="author", title="Alice", institution="Lab")
    g.add_edge("A1", "P1", kind="authored_by")

    seed_works = [{"display_name": "A paper", "publication_year": 2020, "cited_by_count": 10}]
    core = [{
        "name": "Alice", "institution": "Lab",
        "paper_count": 1, "subgraph_citations": 10,
        "top_paper": "A paper", "top_paper_citations": 10,
    }]
    methods = {"Foo": {"name": "Foo", "papers": ["P1"], "confidence": 0.9, "max_confidence": 0.9}}
    citations = [{"from": "X", "to": "Y", "year_from": 2020, "year_to": 2019}]
    gaps = ["method 'Bar' is not mentioned in any subgraph paper"]

    out = report.write_report(
        tmp_path / "report.md", "the idea",
        {"_text": "the idea", "methods": [], "concepts": []},
        g, seed_works, core, citations, methods, gaps,
    )
    text = out.read_text(encoding="utf-8")
    for h in ("## 一、", "## 二、", "## 三、", "## 四、", "## 五、", "## 六、"):
        assert h in text, f"missing section: {h}"


def test_write_report_handles_s2_style_seed_keys(tmp_path):
    """S2 raw work dicts use title/year/citationCount, not
    display_name/publication_year/cited_by_count. Both must render."""
    g = nx.DiGraph()
    seed_works = [{"title": "S2 paper", "year": 2022, "citationCount": 42}]
    out = report.write_report(
        tmp_path / "report.md", "idea text",
        {"_text": "idea text", "methods": [], "concepts": []},
        g, seed_works, [], [], {}, [],
    )
    text = out.read_text(encoding="utf-8")
    assert "S2 paper" in text
    assert "2022" in text
    assert "42" in text


def test_md_cell_escapes_table_separators():
    """P1-6: a value containing '|' must be escaped so it doesn't break the
    table structure."""
    assert report._md_cell("a | b") == "a \\| b"
    assert report._md_cell("plain") == "plain"


def test_md_cell_escapes_html_angle_brackets():
    """P1-6: HTML/JS injection attempts in user-supplied text must be neutralized."""
    assert "&lt;script&gt;" in report._md_cell("<script>")
    assert "&lt;img src=x onerror=alert(1)&gt;" in report._md_cell('<img src=x onerror=alert(1)>')


def test_md_cell_collapses_newlines():
    """P1-6: newlines in any field must not produce extra table rows."""
    assert "\n" not in report._md_cell("line1\nline2\nline3")
    assert report._md_cell("line1\nline2") == "line1 line2"


def test_write_report_neutralizes_xss_in_seed_title(tmp_path):
    """P1-6: a paper title like '<script>alert(1)</script>' must not appear as
    raw HTML in the rendered markdown."""
    g = nx.DiGraph()
    seed_works = [{"title": "<script>alert(1)</script>", "year": 2020, "cited_by_count": 1}]
    out = report.write_report(
        tmp_path / "report.md", "idea",
        {"_text": "idea", "methods": [], "concepts": []},
        g, seed_works, [], [], {}, [],
    )
    text = out.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text
