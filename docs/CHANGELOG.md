# 更新日志 (Changelog)

> 记录「学术社会地图」项目的每次重要改动。最新的在最上面。

---

## 2026-08-21 — 稳定性修复 + 功能改进 + UI 美化

本次改动横跨多个文件，分为六类：关键 bug 修复、性能与健壮性、数据源修复、功能改进、新增功能、UI 美化。

---

### 一、关键 bug 修复（P0）

| 问题 | 位置 | 修复 |
|---|---|---|
| 检索失败时错误信息永远为空（`NameError`，用户看不到真实原因） | `main.py` | 把异常捕获范围扩大到循环内，用 `last_query_err` 保留最后一个真实异常，拼进错误消息 |
| `/runs/{job_id}/{filename}` 路径穿越风险 | `server.py` | 新增 `_safe_segment()` 白名单校验（字母数字 `_ . -`），路由双参均校验 |
| 图数据 `data_source` 用字符串拼接注入 JS，存在注入隐患 | `visualize.py` | 改 `json.dumps()` 安全序列化（并补 `import json`） |
| 未配置 MiniMax key 时 `import config` 直接崩溃 | `config.py` | `MINIMAX_API_KEY` 改用 `_optional_key`（缺 key 返回空而非抛异常） |

---

### 二、性能与健壮性（P1）

| 改动 | 位置 | 效果 |
|---|---|---|
| 1 跳引用扩展并发 `workers=1 → 4` | `main.py` | OpenAlex 后端图谱构建提速约 4 倍（S2 有全局锁自动串行，无副作用） |
| 新增 `max_citing`/`max_refs` 钳制（5-100 / 5-200） | `main.py` + `server.py` | 防止异常入参拉爆数据源配额 |
| `get_works_batch` 分页重写 | `openalex.py` | 修掉 `range(1,5)` 硬上限 + `count/100` break 条件错误；改 `while` + 去重 + 20 页上限 |
| 数据源 `_get`/`get_works_batch` 改为「400 等永久错误 fail-fast」 | `s2.py` + `openalex.py` | 之前 400 也重试 4 次、白烧限流额度，导致连环 429 |

---

### 三、数据源修复（S2 一直报错的真凶）

**根因**：`s2.py` 的 `FIELDS` 字符串里写了 S2 API 不接受的字段名 `openAccessPdf.url`（嵌套写法），导致 `/paper/search` 每次返回 `400 Unrecognized or unsupported fields`。

| 问题 | 修复 |
|---|---|
| `FIELDS` 含非法字段 `openAccessPdf.url` | 改为顶层 `openAccessPdf`（`DETAIL_FIELDS` 等本就正确，仅主 `FIELDS` 写错） |

排查链条（供后人参考）：

| 现象 | 真实原因 |
|---|---|
| 之前「400 Bad Request」 | `openAccessPdf.url` 字段名非法（本次修复） |
| 之前「429 rate limited」 | 旧代码把 400 也重试 4 次烧光额度（fail-fast 修复后消除） |
| S2 有 key 仍紧 | S2 免费额度仅 1 req/s（设计如此，非 bug） |

> **结论**：日常优先用 OpenAlex（免费额度大、无字段坑、快 4 倍）；S2 留作备选。

---

### 四、功能改进

| 改进 | 位置 | 说明 |
|---|---|---|
| 核心研究者榜多样性 | `reasoning.py` | 两级排序：多论文作者（≥2 篇）优先于单论文作者；同桶内按子图被引 + 度中心性。代表作再做去重（避免 5 个核心人物全是同一篇 review 的合著者） |
| 查漏（coverage gaps）消除假阳性 | `reasoning.py` | 多词短语从子串匹配改为 token 集合匹配（去停用词、顺序无关），不再把「lumped mass modeling」误报为不存在 |

**验证**（8 个历史 run 实测）：

| Run | 核心人物代表作唯一数 |
|---|---|
| 改前（多数 run） | 1/5（5 行同 paper） |
| 改后 | 3/5 ~ 5/5 |

---

### 五、新增功能

| 功能 | 位置 | 说明 |
|---|---|---|
| 历史记录删除按钮 | `server.py` + `static/index.html` | 每条历史记录右侧新增红色「删除」按钮；确认后删除该 run 的整个目录。后端 `DELETE /api/history/{job_id}`，带路径穿越防护 + 运行中任务拒绝删除（409） |

---

### 六、UI 美化

视觉风格：**现代学术风·浅色**，靛蓝/紫罗兰点缀（`#6366f1` 系），emoji 全部替换为内联 SVG 图标。

| 改动 | 位置 | 说明 |
|---|---|---|
| CSS 设计系统 | `static/index.html` | 顶部 `:root` 定义色彩/间距/圆角/阴影/字体令牌，全文件引用；新增响应式 `@media` |
| Header 品牌区 | `static/index.html` | 顶部渐变条 + SVG 网络 logo + 副标题 + 品牌 tag |
| 按钮/输入/示例 | `static/index.html` | 主按钮渐变 + 悬停抬升；输入框聚焦光晕；示例 chips 化；标签页淡入动画 |
| 报告表格 | `static/index.html` | 斑马纹 + 表头底色 + 行悬停高亮（纯 CSS，不改 renderMarkdown） |
| 历史列表/空状态 | `static/index.html` | 卡片化 hover、空状态配 SVG 图标 + CSS spinner |
| SVG 图标 | `static/index.html` + `static/favicon.svg` | `<symbol>` sprite + `<use>` 复用；新增 SVG 品牌 favicon（消除 404） |
| 图谱工具栏 | `visualize.py` | 工具栏分组（搜索组/布局组）、SVG 图标、统一圆角阴影 |
| 节点图例 | `visualize.py` | 右下角固定图例（红=idea 蓝=论文 绿=作者 橙=方法） |
| 信息面板 | `visualize.py` | 淡入动画 + 圆角阴影 |
| 物理选项修复 | `visualize.py` | 清除 vis-network 已废弃的 `stabilizeOnly`、`gravity`（改 `centralGravity`），消除红色 console 报错 |

> 附：UI 下拉框默认数据源已从 `s2` 改为 `openalex`（配合数据源修复的结论「OpenAlex 优先」）。

---

## 遗留事项（V2 方向，未做）

- [ ] 补最小回归测试集（mock 两个数据源 API）
- [ ] 重构 `visualize.py` 的 `_inject_enhancements`（250 行字符串拼接）
- [ ] API key 从明文文件改系统 keyring 存储
- [ ] `/api/history` 加缓存（当前每次全量读盘）
- [ ] `llm.py` 的 `print` 改 `logging`
- [ ] idea 从 GET query 改 POST body（避免明文进 URL/日志）
- [ ] 默认数据源 `s2` → `openalex`（UI 下拉框已默认 openalex；`config.py` 的 CLI 默认值仍为 `s2`）
- [ ] 历史 run 的 graph.html 仍是旧样式（图例/新工具栏需重跑才更新）

---

## 2026-08-21 — P0 修复 + 全局竞态治理 + 顺手清理

本轮把所有遗留项一次性做完（含两处新发现的 P0/P1 bug）。

---

### 一、关键 bug 修复

| 问题 | 位置 | 修复 |
|---|---|---|
| **图谱里方法节点被标成论文 ID、`uses` 边全丢**（之前 report 第四章正常，HTML 里却是错的） | `main.py` | `method_genealogy` 已经返回 `{方法名: {papers:[…]}}`，在 `main.run` 把它转成 `{name: [pids]}` 再传给 `render_html`，原来传的是 paper→methods 的反向 map |
| **全局后端竞态**：交互端点（点作者面板、点论文、检测数据源）调 `set_backend` 改 `_BACKEND`，会和正在跑的流水线线程打架 | `server.py` + `datasource.py` | 端点改用 `datasource.get_module(name)`（按名取模块，不动全局）；流水线仍走 `set_backend`（每次 run 开头设一次），双源切换能力保留 |
| **并发 run 互相覆盖后端**：两个任务用不同数据源时，第二个任务的 `set_backend` 会让第一个任务后续请求跑错数据源 | `server.py` `/api/run` | 检测到已有 `queued/running` 任务时返回 409（与 delete-while-running 同款） |
| **缺 DeepSeek key 时 `import config` 直接崩溃**（任意 `import config` 都受影响） | `config.py` | `DEEPSEEK_API_KEY` 改走 `_optional_key`，缺 key 返回 `""` 而非抛异常，调用点友好报错 |
| **核心人物 dedup 后还会撞 rep paper**：低排名作者只有 1 篇且被前面占用时，原代码仍强行写同一篇 | `reasoning.py` | 没有可用候选时把 `top_paper` 置 `None`（报告里显示空），而不是伪造重复 |
| **`_safe_segment` 正则放过 `..`**：单参数路由可被 `filename=".."` 越界到 `RUNS_DIR` 父目录 | `server.py` | 正则改为 `^(?!\.)[A-Za-z0-9_]…$`（首字符不能是 `.`、末字符必须是字母/数字/_）；`run_file` 加 `_resolve_under` 父目录校验 |

### 二、数据源与安全加固

| 改动 | 位置 | 说明 |
|---|---|---|
| `KEYS_DIR` 改为环境变量可覆盖 | `config.py` | `KEYS_DIR = Path(os.environ.get("KEYS_DIR", str(Path.home() / ".academic-social-map" / "keys")))`，迁移/多机器友好 |
| 读 key 优先级 = 环境变量 → keyring → 文件 | `config.py` | 完全向后兼容：现存明文文件直接生效；用户可渐进迁移到 keyring |
| 默认数据源 `s2 → openalex`（CLI + API + UI 三处统一） | `config.py` + `server.py` | 配合 CHANGELOG 上一轮「S2 经常报错」的结论 |
| `_safe_segment` 收紧 + `run_file` 加父目录校验 | `server.py` | 防御路径穿越 |

### 三、keyring 存储（含文件回退）

- `set_api_key.py`：默认写入 Windows Credential Manager（macOS Keychain / Linux Secret Service）；写入失败自动落回 `KEYS_DIR/*.txt`（默认 `~/.academic-social-map/keys`），永不丢 key
- `set_api_key.py --check`：同时显示 keyring 和文件来源
- `set_api_key.py --remove <name>`：从 keyring + 遗留文件中清除
- `requirements.txt` 增 `keyring`

### 四、idea 走 POST body

- `server.py` `/api/run` 改为接收 JSON body（Pydantic `RunRequest`），参数范围由 Pydantic `Field(ge/le)` 校验（缺/越界返回 422）
- `index.html` 改成 `fetch('/api/run', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(...) })`，idea 不再出现在 URL/浏览器历史/服务器 access 日志里

### 五、LLM 与日志

- `llm.py` 的 `print` 全部换成 `logging.getLogger(__name__)`；缺 key 时 `debug` 跳过该 provider 而非 `print` 噪音

### 六、缓存

- `/api/history` 加进程内 TTL 缓存（5 秒，按 `RUNS_DIR` mtime 失效）：前端轮询不再每次全量读盘

### 七、`visualize.py` 重构

- `_inject_enhancements` 从 ~250 行字符串拼接 → 一份 `string.Template` + CSS 常量，函数本身 ~30 行
- 同步删掉 docstring 里已废弃的 `stabilizeOnly` 描述
- JS 里默认 `data_source` 从 `'s2'` 改成 `'openalex'`，与新的全局默认一致

### 八、回归测试

新增 `tests/`（pytest, 33 个用例，全过）：

| 测试 | 覆盖 |
|---|---|
| `test_reasoning.py` | `core_authors` 两级排序 + dedup、`_gap_match` token 集匹配、`coverage_gaps` 阈值、`citation_network` top-N |
| `test_graph_builder.py` | `_score_relatedness`、`_norm_id`、`_collaborations` ≥2 篇共同作者阈值 |
| `test_datasource.py` | `_load` 模块缓存、`get_module` 不动全局后端、未知来源报错 |
| `test_server.py` | `_safe_segment` 拒绝 `..`/`.`/`../etc`、`/api/run` Pydantic 422 + 空 idea 400 + 并发 409、`/runs/..` 越界 400/404 |
| `test_config.py` | env > keyring > file 优先级、`prefix` 解析、空文件返回 `""`、缺 DeepSeek key 不崩 |
| `test_visualize.py` | **P0 回归**：方法节点必须用方法名作 key、`uses` 边必须画出来 |
| `test_report.py` | 六章结构、S2/OpenAlex 双数据源的种子字段兼容 |

### 九、收尾

- `requirements.txt` 增 `pytest`、`httpx`、`keyring`、`pydantic`
- `README.md` 文档同步（数据源默认、key 存储方式、测试方法）

---

### 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/       # 33 passed
.\.venv\Scripts\python.exe set_api_key.py --check  # 三源状态
```

P0 修复后的实际产出（已 smoke 跑过）：
- graph.html: 37 个方法节点、13 条 uses 边（之前都是 0）
- report.md: 核心人物代表作去重后展示空（而不是 5/5 撞同一篇）

### 非代码遗留（重跑才会更新）

- 历史 run 的 `graph.html` 仍是旧样式（需要重新跑一次才能用上新工具栏/图例）
