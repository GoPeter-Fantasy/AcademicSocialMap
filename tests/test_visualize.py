"""Tests for visualize.render_html: graph → HTML. Confirms the P0 method-node
fix: when `methods` is passed as {method_name: [paper_id, ...]} (not the
reversed paper→methods map), the resulting graph.html must contain
method nodes keyed by the method name and `uses` edges."""
import json
import re
from pathlib import Path

import networkx as nx

import visualize


def test_render_html_method_nodes_use_method_names(tmp_path):
    g = nx.DiGraph()
    g.add_node("IDEA", kind="idea", title="my idea", size=40, data_source="openalex")
    g.add_node("W1", kind="paper", title="Paper One", year=2020, cited_by=10, role="seed",
               summary={"abstract": "x", "authors": []})
    g.add_node("W2", kind="paper", title="Paper Two", year=2021, cited_by=20, role="citing",
               summary={"abstract": "y", "authors": []})
    g.add_node("A1", kind="author", title="Alice", institution="Lab")
    g.add_edge("IDEA", "W1", kind="seed")
    g.add_edge("A1", "W1", kind="authored_by")
    g.add_edge("A1", "W2", kind="authored_by")

    # Correct shape: {method_name: [paper_id, ...]}
    method_to_papers = {"Graph Neural Networks": ["W1", "W2"]}
    out = visualize.render_html(g, tmp_path / "graph.html", methods=method_to_papers)
    html = Path(out).read_text(encoding="utf-8")

    assert "method::Graph Neural Networks" in html, (
        "method node must be keyed by method name (got paper id instead — this is the P0 bug)"
    )
    # Confirm kind is method — pyvis may serialise with or without space.
    assert ('"kind": "method"' in html) or ('"kind":"method"' in html), (
        "method node must carry kind=method"
    )
    # Uses edges: each of W1 and W2 should have a 'uses' edge from the method node.
    # pyvis emits the edge dict with keys in this order: arrows, color, ekind, from, from_id, title, to, to_id.
    uses = re.findall(r'"ekind":\s*"uses"[^}]*?"to_id":\s*"(W[12])"', html)
    assert len(uses) == 2, f"expected 2 uses edges, got {uses}"


def test_render_html_no_methods_does_not_add_method_nodes(tmp_path):
    g = nx.DiGraph()
    g.add_node("W1", kind="paper", title="Paper", year=2020, cited_by=1, role="seed",
               summary={"abstract": "", "authors": []})
    out = visualize.render_html(g, tmp_path / "graph.html", methods=None)
    html = Path(out).read_text(encoding="utf-8")
    assert "method::" not in html


def test_render_html_physics_central_gravity_positive(tmp_path):
    """A negative centralGravity repels nodes to the canvas edges, producing the
    ugly 'square + diagonals' layout. Lock the rendered physics to centering
    (centralGravity > 0) so that layout can never regress."""
    g = nx.DiGraph()
    g.add_node("IDEA", kind="idea", title="idea", size=40, data_source="openalex")
    g.add_node("W1", kind="paper", title="P", year=2020, cited_by=1, role="seed",
               summary={"abstract": "", "authors": []})
    g.add_edge("IDEA", "W1", kind="seed")
    out = visualize.render_html(g, tmp_path / "graph.html", methods=None)
    html = Path(out).read_text(encoding="utf-8")
    m = re.search(r"var options = (\{.*?\});", html)
    assert m, "pyvis options block not found in rendered HTML"
    opts = json.loads(m.group(1))
    cg = opts["physics"]["forceAtlas2Based"]["centralGravity"]
    assert cg > 0, f"centralGravity must be > 0 to keep nodes centered, got {cg}"
