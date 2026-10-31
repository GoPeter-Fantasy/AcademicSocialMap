# 学术社会地图 · 项目说明

> idea → 研究者网络：输入一段研究 idea 文本，系统自动构建"这个 idea 所处学术社区的地图"——谁在研究这个方向、谁引用谁（学派）、方法谱系、该引谁、该联系谁。

---

## 一、项目一句话

输入一段研究 idea 文本 → 系统自动"调查"这个 idea 所处的学术社区 → 输出一张可交互的研究者网络图和一份行动报告。

**核心思想（社会事实先验）**：图里的每一条边（谁引用谁、谁合著过）都是从 OpenAlex / Semantic Scholar 真实数据里取出的**客观事实**，不是 LLM 编造的。LLM 只负责两件事：

1. 理解你的 idea 该搜什么（抽取方法/概念/检索词）
2. 从论文摘要抽取方法名（带置信度标注，需人工确认）

---

## 二、项目结构

```
academic-social-map\
├── .venv\              # 独立 Python 环境
├── static\index.html   # Web UI 前端（单页）
├── runs\               # 每次运行的结果（历史记录）
├── docs\               # 项目文档（含 CHANGELOG.md 更新日志）
├── config.py           # API key 加载 + 数据源选择
├── llm.py              # LLM 客户端（DeepSeek 主 / MiniMax 备）
├── datasource.py       # 数据源统一接口（S2 / OpenAlex 运行时切换）
├── s2.py               # Semantic Scholar 后端
├── openalex.py         # OpenAlex 后端
├── extractor.py        # LLM 结构化抽取（方法/概念/query）
├── graph_builder.py    # 图谱构建（引用链 1 跳扩展）
├── reasoning.py        # 推理分析（核心人物/引用网络/方法谱系/查漏）
├── visualize.py        # 交互式图谱渲染
├── report.py           # 结构化 Markdown 报告
├── main.py             # 流水线入口（CLI）
├── server.py           # FastAPI Web 服务
├── start_ui.py         # 一键启动 UI
└── set_api_key.py      # 配置数据源 API key
```

---

## 三、六个步骤（调查方法论）

```
① LLM 理解 idea ──→ ② 检索种子论文 ──→ ③ 构建图谱 ──→ ④ 方法抽取 ──→ ⑤ 推理分析 ──→ ⑥ 输出
```

### ① LLM 理解 idea（extractor.py）

idea 文本送给 LLM（DeepSeek v4-flash），结构化抽出三样东西：

- **方法**（如 `Graph Neural Networks`，带置信度 0-1）
- **概念**（如 `drug discovery`、`cheminformatics`）
- **3 条检索 query**（不同搜索角度）

> 为什么 3 条 query？单条搜索会漏。一条搜完整 idea 关键词，一条搜"方法+核心问题"，一条搜更广的领域——提高召回率。

### ② 检索种子论文（main.py）

3 条 query 各搜 8 篇，合并去重（25 篇上限），再做**相关度排序**：

- 计算每篇论文的标题+摘要与"方法+概念"的词项重合度
- **标题命中优先**（精准），摘要命中次之（召回）
- 取 Top-10 作为"种子论文"——网络的锚点

> 这步决定调查入口质量。不加过滤会把摘要碰巧提到相关词的无关综述选进来（如 1999 年的 "Data clustering" 摘要提到 "information retrieval"），所以采用标题优先策略。

### ③ 构建图谱（graph_builder.py）

对 10 篇种子做 **1 跳引用扩展**（并发拉取 + 限流自适应）：

- **入边**：谁引用了种子（citing works，按被引数取 Top-25，再做相关度剪枝）
- **出边**：种子引用了谁（references）
- **作者**：所有论文的作者作为独立节点，连 `authored_by` 边
- **合著**：同一作者 ID 出现在 ≥2 篇共同论文里的两人，连 `collaborates` 边
- **角色标记**：每个节点标注 `seed / citing / ref` 三种身份

> 角色标记是质量关键：推理时只统计 seed+citing 的作者，这样 BioBERT / U-Net 这类"种子引用的经典背景文献"的作者不会污染核心人物榜。

### ④ 方法抽取（extractor.py）

对图内高被引论文（限 60 篇、有摘要的）分批送 LLM，每篇抽 ≤3 个方法名+置信度。**这是唯一的"LLM 猜测"环节**，报告里明确标注"需人工确认"。

### ⑤ 推理分析（reasoning.py）

- **核心研究者 Top-5**：两级排序 ——（1）按"子图内论文数 ≥ 2 的多论文作者"vs"单论文作者"分桶，多论文作者桶永远排在前面；（2）同桶内按"子图被引数 + 度中心性"排序（只统计 seed/citing 角色的论文）。这样避免 5 个单论文合著者（都是同一篇高被引 review）霸榜。代表作再做去重：若某作者的代表作已被前面作者占用，自动换该作者的下一篇候选
- **谁引用谁**：子图内被引最高的 Top-10 论文之间的引用边
- **方法谱系**：方法名 → 哪些论文用了它（置信度聚合）
- **查漏**：idea 里的方法/概念在图内论文的标题+摘要中找不到的，列为"潜在遗漏方向"（**token 集合匹配**，对多词短语鲁棒，不会把"lumped mass modeling"误报为不存在而论文里只写了"lumped mass"）

### ⑥ 输出（见下文）

---

## 四、所有输出产物

每次运行生成在 `runs/<任务ID>/` 下（4 个文件）：

| 文件 | 内容 |
|---|---|
| **graph.html** | 交互式图谱（"看"的输出）|
| **graph.json** | 图数据（节点+边+全部属性），可程序化复用 |
| **report.md** | 六章结构化报告（"读"的输出）|
| **meta.json** | 元数据（idea、时间、数据源、耗时），支撑历史记录 |

### report.md 的六章解读

1. **种子论文 Top-10** → 该引谁：优先引用这些（已按相关度筛选）
2. **核心研究者 Top-5** → 该联系谁：子图内被引最高的人，含机构/代表作
3. **谁引用谁** → 学派雏形：谁站在谁肩膀上
4. **方法谱系** → 你的方法可能基于什么，带置信度、**需人工核对**
5. **潜在遗漏方向** → 查漏：idea 里哪些概念在图上找不到对应论文
6. **建议行动** → 汇总成可执行建议

### graph.html 的交互

- 节点着色：红=idea、蓝=论文、绿=作者、橙=方法；悬停显示全称
- 布局：力导向引擎跑 300 次稳定后自动冻结（好看且不抖）
- 右上角工具：⏸/▶ 启停布局、🔍 适应视图；窗口 resize 自动重绘
- UI 里可"⛶ 全屏查看图谱"

---

## 五、数据源

统一接口（`datasource.py`），运行时切换（UI 下拉框 + CLI `--data_source` + `/api/run` 三处独立，互不影响）：

| 数据源 | 说明 | 限速 |
|---|---|---|
| **OpenAlex**（默认） | 免费，无需 key，额度每日重置 | 1000 次/天（带 key 可大幅提升） |
| **Semantic Scholar**（备选） | 免费，key 需学校邮箱申请 | key：~1 RPS |

调查口径：**仅英文文献**（`language:en` 过滤）。

限流策略：请求间最小间隔（S2 默认 2.0s）+ 429 时快失败重试（单请求最多 4 次，每次等待 ≤25s），失败请求跳过不阻塞流水线。400 永久错误 fail-fast，避免连环 429。

> 日常优先用 OpenAlex：免费额度大、字段无坑、并发 4 线程比 S2 快约 4 倍。S2 留作备选。

---

## 六、使用方式

### Web UI（推荐）

```powershell
cd academic-social-map
.\start_ui.py        # 自动打开 http://127.0.0.1:8000
```

1. 输入 idea（英文效果最佳），选择数据源，点"🚀 生成学术地图"
2. 实时查看进度日志
3. 完成后在"🌐 网络图谱"和"📄 结构化报告"两个标签页查看
4. "📜 历史记录"列表可随时重新查看之前的结果（自动 5s 内缓存，避免每次重读盘）

### CLI

```powershell
.\.venv\Scripts\python.exe -X utf8 main.py "你的 idea" --out output/xxx
```

### 配置 API key

```powershell
.\.venv\Scripts\python.exe set_api_key.py s2 你的key
.\.venv\Scripts\python.exe set_api_key.py openalex 你的key
.\.venv\Scripts\python.exe set_api_key.py --check            # 查看三个数据源的状态
.\.venv\Scripts\python.exe set_api_key.py --remove s2        # 移除 key
```

key 默认写入 OS 提供的安全存储（Windows Credential Manager / macOS Keychain / Secret Service via `keyring`）。若 keyring 不可用，自动回退到 `KEYS_DIR/*.txt`（默认 `~/.academic-social-map/keys`，可用 `KEYS_DIR` 环境变量覆盖）。读 key 的优先级：环境变量 → keyring → 文件，三层任一层生效即返回；旧的明文 key 文件无需任何迁移即可继续使用。

---

## 七、如何解读与验证

拿一个你熟悉的领域跑一次：如果图里出现的人、机构、方法和你认知一致，说明这次检索锚点选对了。

**验证方法**：如果你熟悉某个领域，跑一次后核对"图里的人/方法和我认知一致吗"。这是项目最初定义的验证方式。

---

## 八、已知限制与风险

1. **方法关系是唯一不"社会事实"的部分**——论文→方法的边由 LLM 从摘要抽取，会错。设计对策：带置信度、人工确认后才视为事实。
2. **实体消歧**——同名作者（如 "J. Wang" 有几百个）。用各数据源自带的作者 ID 缓解。
3. **1 跳以上扩展噪声陡增**——扩展层数被限制在 1 跳，并用"与 idea 的语义相关度"剪枝。
4. **覆盖盲区**——仅英文文献；OpenAlex/S2 对非英语/灰色文献覆盖有限，"社会事实"是"可获取数据中的社会事实"。
5. **免费额度现实**——S2 无 key 共享池限流频繁，key 需学校邮箱；OpenAlex 免费 1000 次/天（key 可提升百倍）。

---

## 九、项目起源

源于桌面文档《文献矩阵项目.md》的项目构想：把"查漏"从单点检索升级为学术社会地图——让 idea 自己找到它在学术网络中的位置。本实现为 MVP：

- **已实现**：种子论文 Top-10、作者引用网络、方法谱系、核心人物 Top-5（带代表作去重）、查漏、Web UI、历史记录、双数据源、回归测试集
- **V2 方向**（未实现）：机构网络、概念层级、社区检测（学派）、Neo4j 存储

---

## 十、测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

覆盖 reasoning（核心人物/查漏/引用网络）、graph_builder、datasource、server（路径安全/并发 409/Pydantic 校验）、config（key 优先级）、visualize（方法节点 P0 回归）、report、extractor、llm。62 个用例，全部不依赖外网。
