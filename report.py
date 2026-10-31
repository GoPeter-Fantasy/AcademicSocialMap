from pathlib import Path

import networkx as nx


def _fmt_cites(n: int) -> str:
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def _md_cell(s: str) -> str:
    """P1-6: escape a value for safe use inside a Markdown table cell.

    - Replaces newlines with spaces (one row per line).
    - Escapes '|' (the table column separator).
    - Escapes HTML '<' / '>' so the report can't smuggle raw HTML/JS into
      a Markdown renderer that allows inline HTML.
    """
    if s is None:
        return ""
    s = str(s).replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    s = s.replace("<", "&lt;").replace(">", "&gt;")
    return s


def write_report(
    out_path: Path,
    idea_text: str,
    idea: dict,
    g: nx.DiGraph,
    seed_works: list[dict],
    core: list[dict],
    citations: list[dict],
    methods: dict[str, dict],
    gaps: list[str],
) -> Path:
    lines = []
    add = lines.append
    add(f"# 学术社会地图报告\n")
    add(f"**输入 Idea**：{_md_cell(idea_text)}\n")
    add(f"**网络规模**：{g.number_of_nodes()} 节点 / {g.number_of_edges()} 边")
    add(f"（论文 {sum(1 for _, d in g.nodes(data=True) if d.get('kind')=='paper')} ｜ "
        f"作者 {sum(1 for _, d in g.nodes(data=True) if d.get('kind')=='author')}）\n")

    add("## 一、种子论文 Top-10\n")
    add("| 论文 | 年份 | 被引 |")
    add("|---|---|---|")
    for w in seed_works:
        title = (w.get("display_name") or w.get("title") or "")
        year = w.get("publication_year") or w.get("year") or "?"
        cites = w.get("cited_by_count") or w.get("citationCount") or 0
        add(f"| {_md_cell(title)[:90]} | {_md_cell(str(year))} | {_fmt_cites(cites)} |")

    add("\n## 二、核心研究者 Top-5\n")
    add("| 研究者 | 机构 | 子图论文数 | 子图被引 | 代表作 |")
    add("|---|---|---|---|---|")
    for a in core:
        add(f"| {_md_cell(a['name'])[:40]} | {_md_cell(a.get('institution') or '')[:40]} | {a['paper_count']} | "
            f"{_fmt_cites(a['subgraph_citations'])} | {_md_cell(a.get('top_paper') or '')[:60]}")

    add("\n## 三、谁引用谁（Top 论文间引用）\n")
    if citations:
        add("| 引用方 | 被引用方 |")
        add("|---|---|")
        for e in citations[:15]:
            add(f"| {_md_cell(e['from'])[:70]} ({_md_cell(str(e['year_from']))}) | "
                f"{_md_cell(e['to'])[:70]} ({_md_cell(str(e['year_to']))}) |")
    else:
        add("（Top 论文间无直接引用边）")

    add("\n## 四、方法谱系（LLM 候选，需人工确认）\n")
    if methods:
        add("| 方法 | 置信度 | 关联论文数 |")
        add("|---|---|---|")
        for m in sorted(methods.values(), key=lambda x: -x["max_confidence"])[:20]:
            add(f"| {_md_cell(m['name'])[:70]} | {m['max_confidence']:.2f} | {len(m['papers'])} |")
        add("\n> 注意：论文→方法 的边由 LLM 从摘要抽取，**带置信度、需人工确认后才视为事实**。")
    else:
        add("（未抽到方法）")

    add("\n## 五、潜在遗漏方向（查漏）\n")
    if gaps:
        for gtext in gaps:
            add(f"- {_md_cell(gtext)}")
    else:
        add("- 未发现明显遗漏")

    add("\n## 六、建议行动\n")
    add("- **该引谁**：优先引用种子论文 Top-10 及核心研究者的代表作。")
    add("- **该联系谁**：核心研究者 Top-5（子图被引最高者），合 作者网络（collaborates 边）可做合作推荐。")
    add("- **风险提示**：方法边为 LLM 候选，引用前请核对原文摘要。")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
