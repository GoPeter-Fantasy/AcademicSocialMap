import json
import string
from pathlib import Path

import networkx as nx
from pyvis.network import Network

COLORS = {
    "idea": "#e6194b",
    "paper": "#3b82f6",
    "author": "#22c55e",
    "method": "#f59e0b",
}

EDGE_COLORS = {
    "cites": "#94a3b8",
    "authored_by": "#65a30d",
    "collaborates": "#0ea5e9",
    "seed": "#e6194b",
    "uses": "#f59e0b",
}

_PYVIS_OPTIONS = """
var options = {
  "physics": {
    "enabled": true,
    "solver": "forceAtlas2Based",
    "stabilization": {
      "enabled": true,
      "iterations": 400,
      "updateInterval": 25,
      "onlyDynamicEdges": false,
      "fit": true
    },
    "forceAtlas2Based": {
      "springLength": 60,
      "springConstant": 0.08,
      "damping": 0.5,
      "avoidOverlap": 1.0,
      "centralGravity": 0.02
    }
  },
  "interaction": {"hover": true, "tooltipDelay": 80, "navigationButtons": true},
  "nodes": {"borderWidth": 1, "font": {"size": 12, "face": "Segoe UI, Microsoft YaHei, sans-serif"}},
  "edges": {"smooth": {"enabled": true, "type": "continuous"}}
}
"""

_ENHANCEMENT_TEMPLATE = string.Template("""
<style type="text/css">$css</style>

<svg xmlns="http://www.w3.org/2000/svg" style="position:absolute;width:0;height:0;overflow:hidden">
  <symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></symbol>
  <symbol id="i-x" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></symbol>
  <symbol id="i-pause" viewBox="0 0 24 24"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></symbol>
  <symbol id="i-play" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></symbol>
  <symbol id="i-fit" viewBox="0 0 24 24"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></symbol>
</svg>

<div id="graph-toolbar">
  <div class="tb-group">
    <div class="tb-search">
      <svg class="tb-icon"><use href="#i-search"/></svg>
      <input id="search-input" placeholder="搜索节点…" onkeydown="if(event.key==='Enter')searchGraph()">
    </div>
    <button class="tb-btn" onclick="searchGraph()"><svg class="tb-icon"><use href="#i-search"/></svg><span>搜索</span></button>
    <button class="tb-btn" onclick="clearSearch()"><svg class="tb-icon"><use href="#i-x"/></svg><span>清除</span></button>
  </div>
  <div class="tb-group">
    <button class="tb-btn" id="btn-physics" onclick="togglePhysics()"><svg class="tb-icon"><use id="btn-physics-icon" href="#i-pause"/></svg><span id="btn-physics-label">停止布局</span></button>
    <button class="tb-btn" onclick="network.fit()"><svg class="tb-icon"><use href="#i-fit"/></svg><span>适应视图</span></button>
  </div>
  <span id="search-status"></span>
</div>

<div id="graph-legend">
  <div class="legend-title">图例</div>
  <div class="legend-row"><span class="dot" style="background:#e6194b"></span>Idea</div>
  <div class="legend-row"><span class="dot" style="background:#3b82f6"></span>论文</div>
  <div class="legend-row"><span class="dot" style="background:#22c55e"></span>作者</div>
  <div class="legend-row"><span class="dot" style="background:#f59e0b"></span>方法</div>
</div>

<div id="info-panel" style="display:none;">
  <div style="display:flex;align-items:center;padding:10px 14px;border-bottom:1px solid #e2e8f0;position:sticky;top:0;background:#fff;border-radius:12px 12px 0 0;">
    <b id="panel-title" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#1e293b;"></b>
    <button onclick="hidePanel()" style="border:none;background:none;cursor:pointer;color:#64748b;display:flex;padding:4px;"><svg class="tb-icon"><use href="#i-x"/></svg></button>
  </div>
  <div id="panel-body" style="padding:12px 14px;"></div>
</div>

<script>
var DATA_SOURCE = $data_source_json;

function hidePanel() { document.getElementById('info-panel').style.display = 'none'; }

function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function pdfBtn(pdf, doi, title) {
  var t = esc(title || '');
  // P0-3: whitelist URL schemes to prevent javascript:/data: URLs from upstream.
  var safePdf = (pdf && /^https?:\\/\\//i.test(pdf)) ? pdf : '';
  var safeDoi = (doi && /^10\\./.test(doi)) ? doi : '';
  if (safePdf) return '<a target="_blank" rel="noopener noreferrer" href="' + esc(safePdf) + '" style="display:inline-block;margin:2px 6px 2px 0;padding:5px 12px;background:#dc2626;color:#fff;border-radius:6px;text-decoration:none;font-size:12px;">打开 PDF</a>';
  if (safeDoi) return '<a target="_blank" rel="noopener noreferrer" href="https://doi.org/' + esc(safeDoi) + '" style="display:inline-block;margin:2px 6px 2px 0;padding:5px 12px;background:#6366f1;color:#fff;border-radius:6px;text-decoration:none;font-size:12px;">DOI 页面</a>';
  return '<span style="color:#94a3b8;font-size:12px;">无开放 PDF</span>';
}

function showPanel(title, body) {
  document.getElementById('panel-title').textContent = title;
  document.getElementById('panel-body').innerHTML = body;
  document.getElementById('info-panel').style.display = 'block';
}

function nodeById(id) {
  var d = nodes.get(id);
  return d;
}

function onNodeClick(id) {
  var n = nodeById(id);
  if (!n) return;
  var kind = n.kind || 'paper';
  if (kind === 'idea') {
    showPanel('Idea', '<div style="color:#334155;">' + esc(n.name) + '</div>');
  } else if (kind === 'paper') {
    var s = n.summary || {};
    var authors = (s.authors || []).slice(0, 8).map(function (a) { return esc(a.name); }).join(', ') || '未知';
    var abstract = s.abstract ? '<div style="margin-top:8px;color:#475569;max-height:160px;overflow-y:auto;border-top:1px solid #e2e8f0;padding-top:8px;">' + esc(s.abstract) + '</div>' : '';
    var venue = s.venue ? '<div style="color:#64748b;font-size:12px;margin-top:4px;">' + esc(s.venue) + '</div>' : '';
    showPanel('论文 · ' + (n.name || ''), [
      '<div style="color:#64748b;font-size:12px;">' + (s.year || '?') + ' ｜ 被引 ' + (s.cited_by_count || 0) + '</div>',
      venue,
      pdfBtn(s.pdf_url, s.doi, s.title),
      '<div style="margin-top:8px;"><b>作者:</b> ' + authors + '</div>',
      abstract
    ].join(''));
  } else if (kind === 'author') {
    showPanel('作者 · ' + (n.name || ''), '<div style="color:#64748b;">加载文献列表…</div>');
    var ds = n.data_source || DATA_SOURCE || 'openalex';
    var cacheKey = 'author:' + id + ':' + ds;
    if (window.__authorCache && window.__authorCache[cacheKey]) {
      renderAuthorPanel(n, window.__authorCache[cacheKey]);
      return;
    }
    fetch('/api/author/' + encodeURIComponent(id) + '?data_source=' + encodeURIComponent(ds))
      .then(function (r) { return r.json(); })
      .then(function (list) {
        if (!Array.isArray(list)) throw new Error(list.detail || 'failed');
        if (!window.__authorCache) window.__authorCache = {};
        window.__authorCache[cacheKey] = list;
        renderAuthorPanel(n, list);
      })
      .catch(function (e) {
        var msg = String(e);
        var friendly = msg.indexOf('502') !== -1
          ? '数据源限流（429）或暂时不可用，稍等几秒再点'
          : msg;
        document.getElementById('panel-body').innerHTML = '<div style="color:#dc2626;">加载失败: ' + esc(friendly) + '</div>';
      });
  } else if (kind === 'method') {
    showPanel('方法 · ' + (n.name || ''), '<div style="color:#64748b;">方法节点——点击边查看关联</div>');
  }
}

function renderAuthorPanel(n, list) {
  if (!list.length) { document.getElementById('panel-body').innerHTML = '<div style="color:#94a3b8;">该作者暂无文献数据</div>'; return; }
  var inst = n.institution ? '<div style="color:#64748b;font-size:12px;margin-bottom:8px;">' + esc(n.institution) + '</div>' : '';
  var items = list.slice(0, 15).map(function (p) {
    return '<div style="padding:8px 0;border-bottom:1px solid #f1f5f9;">' +
      '<div style="font-weight:500;color:#1e293b;">' + esc(p.title || '') + '</div>' +
      '<div style="color:#64748b;font-size:12px;margin-top:2px;">' + (p.year || '?') + ' ｜ 被引 ' + (p.cited_by_count || 0) + '</div>' +
      '<div style="margin-top:4px;">' + pdfBtn(p.pdf_url, p.doi, p.title) + '</div>' +
      '</div>';
  }).join('');
  document.getElementById('panel-title').textContent = '作者 · ' + (n.name || '');
  document.getElementById('panel-body').innerHTML = inst + items;
}

function onEdgeClick(edgeId) {
  var e = edges.get(edgeId);
  if (!e) return;
  var kind = e.ekind || 'cites';
  var nFrom = nodeById(e.from);
  var nTo = nodeById(e.to);
  var fromName = nFrom ? (nFrom.name || e.from) : e.from;
  var toName = nTo ? (nTo.name || e.to) : e.to;
  var desc = {
    cites: 'A 引用了 B（站在 B 的肩膀上）',
    authored_by: '该作者撰写了这篇论文',
    collaborates: '两位作者有合著关系（≥2 篇共同论文）',
    seed: '种子论文（idea 的锚点）',
    uses: '这篇论文使用了该方法'
  }[kind] || kind;
  var html = '<div style="margin-bottom:8px;"><span style="display:inline-block;padding:2px 10px;border-radius:12px;background:#f1f5f9;color:#475569;font-size:12px;">' + esc(kind) + '</span></div>' +
    '<div style="color:#475569;">' + esc(desc) + '</div>' +
    '<div style="margin-top:10px;padding:8px;background:#f8fafc;border-radius:8px;font-size:12px;color:#334155;">' +
    '<div>起点: <b>' + esc(fromName) + '</b></div>' +
    '<div style="margin-top:4px;">终点: <b>' + esc(toName) + '</b></div></div>';
  showPanel('边信息', html);
}

function onGraphClick(params) {
  if (params.nodes && params.nodes.length) {
    onNodeClick(params.nodes[0]);
  } else if (params.edges && params.edges.length) {
    onEdgeClick(params.edges[0]);
  } else {
    hidePanel();
  }
}

function bindClick() {
  if (typeof network !== 'undefined' && network.on && !window.__clickBound) {
    network.on('click', onGraphClick);
    window.__clickBound = true;
  }
}
if (document.readyState === 'complete') { bindClick(); }
else { window.addEventListener('load', function () { setTimeout(bindClick, 300); }); }

function searchGraph() {
  var q = (document.getElementById('search-input').value || '').trim().toLowerCase();
  var status = document.getElementById('search-status');
  if (!q) { clearSearch(); return; }
  var matched = [];
  var all = nodes.get();
  for (var i = 0; i < all.length; i++) {
    var n = all[i];
    var hay = ((n.name || '') + ' ' + (n.label || '')).toLowerCase();
    if (hay.indexOf(q) !== -1) matched.push(n.id);
  }
  if (!matched.length) {
    status.textContent = '无匹配节点';
    clearHighlights();
    return;
  }
  highlight(matched);
  status.textContent = '匹配 ' + matched.length + ' 个节点';
}

function clearSearch() {
  document.getElementById('search-input').value = '';
  document.getElementById('search-status').textContent = '';
  clearHighlights();
  network.fit();
}

function clearHighlights() {
  var all = nodes.get();
  for (var i = 0; i < all.length; i++) {
    var n = all[i];
    if (n.__hl) {
      nodes.update({ id: n.id, color: n.__hl, borderWidth: n.__bw || 1, __hl: null, __bw: null });
    }
  }
}

function highlight(ids) {
  var idSet = {};
  for (var i = 0; i < ids.length; i++) idSet[ids[i]] = true;
  var all = nodes.get();
  for (var i = 0; i < all.length; i++) {
    var n = all[i];
    if (idSet[n.id]) {
      if (!n.__hl) {
        n.__hl = n.color;
        n.__bw = n.borderWidth || 1;
      }
      nodes.update({ id: n.id, color: '#f59e0b', borderWidth: 5 });
    } else if (n.__hl) {
      nodes.update({ id: n.id, color: n.__hl, borderWidth: n.__bw || 1, __hl: null, __bw: null });
    }
  }
  network.selectNodes(ids, false);
  if (ids.length === 1) { network.focus(ids[0], { scale: 1.2, animation: true }); }
  else { network.fit({ nodes: ids, animation: true }); }
}

function togglePhysics() {
  var on = !(network.physics && network.physics.options && network.physics.options.enabled);
  network.setOptions({physics: {enabled: on}});
  var label = document.getElementById('btn-physics-label');
  var icon = document.getElementById('btn-physics-icon');
  if (label) label.textContent = on ? '停止布局' : '启用布局';
  if (icon) icon.setAttribute('href', on ? '#i-pause' : '#i-play');
  if (on) network.stabilize(300);
}
window.addEventListener('resize', function () {
  if (typeof network !== 'undefined') {
    network.redraw();
    setTimeout(function () { network.fit(); }, 200);
  }
});
</script>
""")

_INJECTION_CSS = """
html, body { height: 100%; margin: 0; padding: 0; overflow: hidden; }
.card { height: 100%; }
.card-body, #mynetwork { height: 100vh !important; width: 100% !important; }
:root {
  --primary:#6366f1; --primary-light:#eef2ff;
  --surface:#fff; --border:#e2e8f0; --border-strong:#cbd5e1;
  --text:#1e293b; --text-muted:#64748b; --text-faint:#94a3b8; --danger:#dc2626;
  --radius-sm:8px; --shadow-sm:0 1px 2px rgba(15,23,42,.06); --shadow-md:0 4px 16px rgba(15,23,42,.12);
  --font:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
}
#graph-toolbar {
  position: fixed; top: 12px; left: 12px; z-index: 9999;
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  font-family: var(--font);
}
.tb-group {
  display: flex; gap: 4px; align-items: center;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 5px; box-shadow: var(--shadow-md);
}
.tb-search {
  display: flex; align-items: center; gap: 6px;
  padding: 0 9px; border: 1px solid var(--border-strong);
  border-radius: 7px; background: var(--surface);
}
.tb-search .tb-icon { color: var(--text-faint); }
.tb-search input {
  border: none; outline: none; font-size: 13px; font-family: var(--font);
  width: 150px; padding: 7px 0; color: var(--text); background: transparent;
}
.tb-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 12px; border: none; border-radius: 7px;
  background: transparent; color: var(--text-muted); cursor: pointer;
  font-size: 13px; font-family: var(--font); font-weight: 500;
  transition: all .15s ease; white-space: nowrap;
}
.tb-btn:hover { background: var(--primary-light); color: var(--primary); }
.tb-icon { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; flex-shrink: 0; }
#search-status { font-size: 12px; color: var(--text-muted); }
#graph-legend {
  position: fixed; right: 12px; bottom: 12px; z-index: 9997;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 10px 14px; box-shadow: var(--shadow-md);
  font-family: var(--font); font-size: 12px; color: var(--text-muted);
}
#graph-legend .legend-title { font-weight: 600; color: var(--text); margin-bottom: 6px; font-size: 12px; }
.legend-row { display: flex; align-items: center; gap: 7px; padding: 2px 0; }
.legend-row .dot { width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; }
#info-panel {
  position: fixed; top: 60px; right: 12px; width: 340px; max-height: calc(100vh - 90px);
  overflow-y: auto; background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: var(--shadow-md); z-index: 9998;
  font-size: 13px; line-height: 1.6; font-family: var(--font);
  animation: panelIn .18s ease;
}
@keyframes panelIn { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }
"""


def render_html(g: nx.DiGraph, out_path: Path, methods: dict[str, list[str]] | None = None) -> Path:
    """Render the interactive graph at full container size.

    Layout: the physics engine (forceAtlas2Based) stabilizes the graph and
    then stops automatically — so the graph looks organic but does NOT keep
    vibrating. A toolbar button lets the user re-enable the physics engine.

    `methods` is {method_name: [paper_id, ...]} — used to attach orange
    method nodes and "uses" edges to the graph.
    """
    work = g.copy()
    if methods:
        for mname, pids in list(methods.items())[:20]:
            mnode = f"method::{mname}"
            work.add_node(mnode, kind="method", title=mname)
            for pid in pids:
                if pid in work:
                    work.add_edge(mnode, pid, kind="uses")

    net = Network(height="100%", width="100%", directed=True, notebook=False, cdn_resources="in_line")

    for node, data in work.nodes(data=True):
        kind = data.get("kind", "paper")
        label = data.get("title", node)
        if kind == "paper":
            label = f"{label} ({data.get('year') or '?'})"
        extra = {
            "kind": kind,
            "name": label[:200],
            "data_source": data.get("data_source", "") or work.nodes.get("IDEA", {}).get("data_source", ""),
        }
        if kind == "paper" and data.get("summary"):
            s = data["summary"]
            extra["summary"] = {
                "id": s.get("id"),
                "title": s.get("title"),
                "year": s.get("year"),
                "cited_by_count": s.get("cited_by_count", 0),
                "doi": s.get("doi"),
                "abstract": (s.get("abstract") or "")[:1200],
                "pdf_url": s.get("pdf_url", ""),
                "venue": s.get("venue", ""),
                "authors": s.get("authors", [])[:20],
            }
        if kind == "author":
            extra["institution"] = data.get("institution", "")
        # Per-kind size floor so author/method don't shrink to the graph's
        # paper-level default of 18 and look like dots in dense graphs.
        _SIZE_FLOOR = {"idea": 40, "paper": 22, "author": 16, "method": 18}
        net.add_node(
            node,
            label=str(label)[:60],
            color=COLORS.get(kind, "#888"),
            size=max(data.get("size", _SIZE_FLOOR.get(kind, 12)), _SIZE_FLOOR.get(kind, 12)),
            title=str(label),
            group=kind,
            **extra,
        )

    for e in work.edges(data=True):
        src, dst, data = e
        kind = data.get("kind", "cites")
        net.add_edge(
            src, dst,
            title=kind,
            color=EDGE_COLORS.get(kind, "#888"),
            ekind=kind,
            from_id=src,
            to_id=dst,
        )

    net.set_options(_PYVIS_OPTIONS)
    html = net.generate_html()
    out_path.write_text(html, encoding="utf-8")
    idea_attrs = work.nodes.get("IDEA") or {}
    _inject_enhancements(out_path, data_source=idea_attrs.get("data_source", ""))
    return out_path


def _inject_enhancements(out_path: Path, data_source: str = "") -> None:
    """Inject the toolbar, legend, info panel, and behaviour scripts into the
    pyvis-generated HTML. Body content is split out into a single template
    so this function stays ~30 lines instead of 250."""
    html = out_path.read_text(encoding="utf-8")
    rendered = _ENHANCEMENT_TEMPLATE.substitute(
        css=_INJECTION_CSS,
        data_source_json=json.dumps(data_source or ""),
    )
    if "</body>" in html:
        html = html.replace("</body>", rendered + "</body>", 1)
    else:
        html += rendered
    out_path.write_text(html, encoding="utf-8")
