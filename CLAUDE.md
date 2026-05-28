# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Music Agent —— 本地音乐库管理 + 多 Agent 对话系统。用户 Jane，约 322 首歌，存储在 `C:\Users\JaneShown\Desktop\music\MUSIC\`。

## 常用命令

```bash
python main.py scan              # 扫描音乐库
python main.py query "周杰伦"    # CLI 搜索
python main.py web               # 启动 Streamlit Web UI (8501)
python main.py organize          # 整理文件
python chat_unified.py           # 交互式对话（主入口）
```

没有可用的测试。`tests/test_librarian.py` 已过时。

## 架构：Hermes（三层主干 + 一圈闭环）

```
Trigger → Gateway → Agent Loop → Reflect ↺
```

### 触发层 — `hermes/trigger.py`

4 个入口统一为 `TriggerEvent(source, user_id, content, context)`：
- `chat_unified.py` → ChatTrigger
- `main.py` → CLITrigger
- `web/app.py` → WebTrigger
- `core/folder_watcher.py` → FSMonitorTrigger

### 网关层 — `hermes/gateway.py` + `graph/nodes/gateway_node.py`

纯 LLM Function Calling 路由（Kimi/Moonshot），分发到 4 个 Agent：
- `dispatch_to_librarian` | `dispatch_to_organizer` | `dispatch_to_metadata` | `respond_directly`

路由前三级加速：Skill 模式匹配（字符串，0ms）→ Memory 注入（SQLite + ChromaDB）→ LLM 路由（~500ms）。`exit/help/clear` 等 12 条 meta 命令直接命中，不走 LLM。

### Agent 层 — 全部 ReAct agent

每个都是 `langgraph.prebuilt.create_react_agent`，使用 `KimiChatModel`（`graph/kimi_adapter.py`，LangChain 兼容的 Kimi 封装）：

| 节点文件 | 工具数 | 职责 |
|---|---|---|
| `graph/nodes/librarian_node.py` | 10 | 搜索、播放、扫描、统计、情绪/语言查询 |
| `graph/nodes/organizer_agent.py` | 3 | 整理、去重、目录分析 |
| `graph/nodes/metadata_agent.py` | 5 | 诊断、修复、标签纠正、情绪同步 |

工具定义在 `graph/tools/` 下：`library_tools.py`、`organizer_tools.py`、`metadata_tools.py`。

### 闭环 — `hermes/reflect.py` + `graph/nodes/reflect_node.py`

每次 Agent 执行后，Reflect 节点提取偏好写入 `hermes/memory.py`（MemoryStore），提取可复用模式写入 `hermes/skill.py`（SkillStore）。下一次 Gateway 路由时注入这些记忆和技能。

### 图拓扑 — `graph/graph.py`

```
START → hermes_gateway → {librarian | organizer | metadata | respond}
       → reflect → respond → END
```

状态定义在 `graph/state.py`（`MusicAgentState` TypedDict），路由函数在 `graph/router.py`。

## 检索栈（4 层递进，命中即短路）

| 层 | 方法 | 数据量 | 延迟 |
|---|---|---|---|
| Skill 匹配 | 字符串模板（9 个内置） | 9 条 | ~0ms |
| Memory | SQLite 精确 + ChromaDB 语义 | 数条~几十条 | ~10ms |
| 音乐搜索 | Dense(ChromaDB/BGE) + BM25 + RRF | 322 首 | ~100ms |
| Gateway | LLM Function Calling (Kimi) | 4 个 dispatch | ~500ms |

**音乐搜索**（`core/vector_store.py` `search()`）：两路并行 —— ChromaDB 语义向量 + BM25 倒排索引 → RRF 融合排序。BM25 索引在 `data/bm25_index.json`，首次初始化后自动构建。

**Memory 检索**（`hermes/memory.py` `query_relevant()`）：SQLite 做关键词精确匹配，ChromaDB collection `hermes_memory` 做语义检索（"台湾男歌手" → "周杰伦"），两路合并去重。

## 关键数据存储

| 路径 | 引擎 | 内容 |
|---|---|---|
| `data/music_library.db` | SQLite | 歌曲元数据 |
| `data/chroma/` | ChromaDB | 音乐库语义向量（collection: `music_library`） |
| `data/bm25_index.json` | JSON | BM25 倒排索引 |
| `data/chroma_memory/` | ChromaDB | Memory 语义向量（collection: `hermes_memory`） |
| `data/hermes_memory.db` | SQLite | 结构化记忆（偏好/事实/纠正） |
| `data/emotion_cache.json` | JSON | 情绪分析缓存（按文件哈希索引） |

## 配置

- `config.yaml` — 库路径、RAG 参数（embedding 模型、hybrid search 权重、RRF k）、LLM 模型
- `.env` — `KIMI_API_KEY`（Moonshot API key）

## 重要模式

- **LibrarianAgent 是单例** — `agents/librarian.py` `get_librarian()`。持有 VectorStore 和 BM25 索引。所有需要访问音乐库的工具和节点都调用它。
- **配置加载** — `graph/utils.py` `load_config()` 读 `config.yaml` 并全局缓存。
- **封面检测** — 使用 `LibrarianAgent.has_embedded_cover()`（按 FLAC/MP3/M4A 分别处理），不要用 `metadata_tools._has_embedded_cover` 的旧版本。
- **元数据诊断** — 对 DB 中标记为 Unknown 的字段会直接从文件 tag 交叉校验，避免误报。

## 已弃用文件（保留供参考，不在当前 graph 中）

- `graph/nodes/intent_router.py` — 旧 L0-L4 四级路由（Hermes Gateway 已替代）
- `graph/nodes/organizer_node.py` — 旧过程式节点（ReAct agent 已替代）
- `graph/nodes/metadata_node.py` — 旧过程式节点（ReAct agent 已替代）
- `chat/tool_registry.py` — 旧 32 工具 FC 注册表（4 agent dispatch 已替代）

## 依赖

`langgraph` + `langchain-core`（图和 Agent 框架）、`chromadb`（向量库）、`mutagen`（音频元数据）、`sentence-transformers`（可选，不可用时回退 ChromaDB 默认 embedding）、`streamlit`（Web UI）、`watchdog`（文件监控）。
