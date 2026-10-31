# 学术社会地图 · Academic Social Map

> 输入一段研究 idea，自动构建它所处学术社区的地图：谁在做、谁引用谁、方法谱系、该引谁、该找谁。

![界面截图](docs/screenshot.png)

图里的每一条边（谁引用谁、谁和谁合著）都来自 **OpenAlex / Semantic Scholar 的真实元数据**，不是大模型编的。LLM 只负责两件事：理解 idea 该搜什么、从摘要里抽方法名（带置信度，需人工确认）。

## 它会产出什么

每次运行在 `runs/<job_id>/` 下生成四个文件：

| 文件 | 内容 |
|---|---|
| `graph.html` | 可交互研究者网络图（力导向布局，可搜索、点节点看详情） |
| `graph.json` | 图数据（节点 / 边 / 全部属性），可程序化复用 |
| `report.md` | 六章结构化报告 |
| `meta.json` | 元数据（idea、时间、数据源、耗时），支撑历史记录 |

报告的六章：

1. **种子论文 Top-10** —— 该引谁
2. **核心研究者 Top-5** —— 该联系谁（含机构、代表作）
3. **谁引用谁** —— 学派雏形
4. **方法谱系** —— 方法 → 论文，带置信度
5. **潜在遗漏方向** —— idea 里哪些概念在图里找不到对应论文
6. **建议行动**

## 流水线

```
① LLM 理解 idea → ② 检索种子论文 → ③ 1 跳引用扩展 → ④ 方法抽取 → ⑤ 推理分析 → ⑥ 输出
```

| 步 | 做什么 | 文件 |
|---|---|---|
| ① | 抽方法/概念 + 生成 3 条检索 query | `extractor.py` |
| ② | 多 query 检索 + 标题优先排序取 Top-10 | `main.py` |
| ③ | 引用链 1 跳扩展 + 合著者，按相关度剪枝 | `graph_builder.py` |
| ④ | 高被引论文摘要 → 方法名（≤3/篇） | `extractor.py` |
| ⑤ | 核心人物 / 引用网 / 方法谱系 / 查漏 | `reasoning.py` |
| ⑥ | Markdown 报告 + 交互图谱 | `report.py` + `visualize.py` |

## 快速开始

需要 Python 3.11+（开发环境为 3.13）。

```bash
git clone <this-repo>
cd academic-social-map

# 1) 建虚拟环境并安装（版本已全部 pin 在 requirements.lock）
python -m venv .venv
# Windows:
.venv\Scripts\pip install -r requirements.lock
# macOS / Linux:
.venv/bin/pip install -r requirements.lock

# 2) 配 LLM key（方法抽取需要；DeepSeek 为主，MiniMax 为备）
python set_api_key.py deepseek sk-your-key
python set_api_key.py --check

# 3) 启动 Web UI（自动打开 http://127.0.0.1:8000）
python start_ui.py
```

命令行方式：

```bash
python -X utf8 main.py "your research idea" --out output/demo --data-source openalex
```

> Windows 下如果用系统 Python 跑出中文乱码，加 `-X utf8`。

## 配置

| 环境变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` / `MINIMAX_API_KEY` | LLM key（二者至少一个） |
| `DEEPSEEK_MODEL` / `MINIMAX_MODEL` | 模型名，有默认值 |
| `OPENALEX_API_KEY` / `S2_API_KEY` | 数据源 key（OpenAlex 可不填） |
| `DATASOURCE` | `openalex`（默认）或 `s2` |
| `KEYS_DIR` | 明文 key 回退目录，默认 `~/.academic-social-map/keys` |
| `OPENALEX_MAILTO` | 填了会放进 User-Agent，OpenAlex 给更宽松的限流 |

key 的读取顺序：**环境变量 → 系统 keyring → `KEYS_DIR` 下的明文文件**。`set_api_key.py` 默认写入 keyring（Windows Credential Manager / macOS Keychain / Secret Service），写入失败才回退到文件。

完整说明见 [docs/README.md](docs/README.md)，更新日志见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。

## 数据源

| 数据源 | 默认 | 限速 | 备注 |
|---|---|---|---|
| OpenAlex | ✅ | 免费额度约 1000 次/天（key 可提升） | 免费、字段稳定、比 S2 快约 4 倍 |
| Semantic Scholar | | 共享池约 1 req/s（key 可放宽） | 需要学校邮箱申请 key，作为备选 |

调查口径：仅英文文献（`language:en`）。

## 测试

```bash
python -m pytest tests/ -q
```

62 个用例，全部离线，不依赖外网。

## 项目结构

```
academic-social-map/
├── static/index.html   # Web UI 单页
├── docs/               # 说明文档、CHANGELOG、截图
├── tests/              # 62 个回归用例
├── config.py           # key 加载（env → keyring → 文件）+ 数据源选择
├── llm.py              # LLM 客户端（DeepSeek 主 / MiniMax 备）
├── datasource.py       # 数据源门面（运行时切换 + 限流）
├── openalex.py / s2.py # 两个数据源后端
├── extractor.py        # LLM 结构化抽取（方法 / 概念 / query）
├── graph_builder.py    # 图谱构建（引用链 1 跳扩展）
├── reasoning.py        # 推理（核心人物 / 引用网 / 方法谱系 / 查漏）
├── visualize.py        # 交互式图谱渲染（pyvis）
├── report.py           # 六章 Markdown 报告
├── main.py             # 流水线入口（CLI）
├── server.py           # FastAPI 服务
├── start_ui.py         # 一键启动 UI
└── set_api_key.py      # 配置 / 检查 / 移除 API key
```

## 已知限制

- **方法边是唯一非“社会事实”的部分**：论文 → 方法由 LLM 从摘要抽取，会错。所以每条都带置信度，需人工核对原文。
- **实体消歧**：同名作者（如 “J. Wang”）仅靠数据源自带 author ID 缓解，仍可能认错。
- **1 跳以上噪声陡增**：目前只扩 1 跳，并用相关度剪枝；仍会带进沾边分支。
- **覆盖盲区**：仅英文文献；OpenAlex / S2 对非英语与灰色文献覆盖有限。
- **免费额度**：OpenAlex 约 1000 次/天；S2 共享池限流较紧。

## 安全

- API key 存系统 keyring，仓库内不含任何 key；`.env`、`.keys/`、`runs/`、`output/` 均已加入 `.gitignore`。
- 服务端对路径做白名单校验（防目录穿越），对 PDF / DOI 做 scheme 白名单（防 `javascript:` / `data:`）。
- idea 通过 POST body 提交，不进 URL 与访问日志。
- 这是一个本地单用户工具，默认只监听 `127.0.0.1`，没有鉴权；**不要直接暴露到公网**。

## License

[MIT](LICENSE) © 2026 GoPeter-Fantasy
