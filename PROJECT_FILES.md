# Music Agent — 项目文件速查手册

> 按目录分类，每个文件一句话说明职责 + 关键细节。

---

## 1. 根目录：入口 & 配置

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `chat_unified.py` | **交互式对话主入口** | `MusicAgentChat` 类封装 graph 调用、文件监控启停、monitor 指令处理，`python chat_unified.py` 启动 |
| `main.py` | CLI 命令行入口 | `python main.py scan/query/web/organize` |
| `config.yaml` | 全局配置文件 | 库路径、RAG 参数（embedding 模型/hybrid 权重/RRF k）、LLM 模型、Organizer/Scout 配置 |
| `.env` | 环境变量 | `KIMI_API_KEY`（Moonshot API key） |
| `requirements.txt` | Python 依赖清单 | langgraph, chromadb, mutagen, streamlit, watchdog 等 |
| `tools_manage_embedding.py` | Embedding 模型管理工具 | 切换/测试/列出可用 embedding 模型 |
| `CLAUDE.md` | Claude Code 项目指引 | 架构说明、文件索引、关键模式（给 AI 看的） |
| `README.md` | 项目 README | 功能概览 |
| `CHANGELOG.md` | 变更日志 | 版本迭代记录 |
| `CHAT_README.md` | 聊天功能说明 | 对话系统使用指引 |
| `EMOTION_ANALYSIS.md` | 情绪分析文档 | 情绪分析功能说明 |
| `FFMPEG_INSTALL.md` | FFmpeg 安装指引 | 音频格式转换依赖 |

---

## 2. graph/ — LangGraph 图计算层（核心调度中枢）

### 图定义 & 基础设施

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `graph/graph.py` | **图拓扑定义 + 编译** | `START → gateway → {librarian/organizer/metadata/respond} → reflect → respond → END`，MemorySaver 做状态持久化 |
| `graph/state.py` | **全局共享状态** | `MusicAgentState` TypedDict，12 个字段：messages/intent/target_agent/task_params/query_results/final_response/memory_context 等 |
| `graph/router.py` | **条件路由函数** | `route_by_intent()` 将 gateway 输出的 intent 映射到对应 Agent 节点名 |
| `graph/kimi_adapter.py` | **Kimi LLM 适配器** | `KimiChatModel` 继承 LangChain `BaseChatModel`，实现消息格式转换、`bind_tools()`、Tool Call ↔ Function Calling 双向映射 |
| `graph/utils.py` | 工具函数 | `load_config()` 读 yaml 并全局缓存、`msg_content()` 提取消息文本 |

### graph/nodes/ — 图节点（每个节点 = 一个处理步骤）

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `graph/nodes/__init__.py` | 节点模块导出 | 汇总所有 node 函数 |
| `graph/nodes/gateway_node.py` | **Gateway 节点** | 调用 `HermesGateway.route()`，路由前注入 Memory + Skill 上下文，输出 intent/target_agent/task_params |
| `graph/nodes/librarian_node.py` | **Librarian 节点** | ReAct agent 挂载 10 个工具；额外直接处理 scan/stats/emotion/play_items 等管理类意图（不走 ReAct） |
| `graph/nodes/organizer_agent.py` | **Organizer 节点** | ReAct agent 挂载 3 个工具（整理/去重/分析），危险操作须先 dry_run 预览 |
| `graph/nodes/metadata_agent.py` | **Metadata 节点** | ReAct agent 挂载 5 个工具（诊断/修复/标签纠正/缓存同步） |
| `graph/nodes/reflect_node.py` | **Reflect 反思节点** | Agent 执行后调用 `ReflectEngine.reflect()`，提取记忆与技能，失败不阻塞主流程 |
| `graph/nodes/respond_node.py` | **Respond 格式化节点** | 处理 help/clear/exit 等简单指令 + 格式化最终回复 + 兜底文案 |

### graph/tools/ — Agent 可调用的工具函数

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `graph/tools/__init__.py` | 工具模块导出 | |
| `graph/tools/library_tools.py` | **Librarian 工具集（10 个）** | search_music / scan_library / get_song_info / get_library_stats / play_song / play_all_songs / play_by_artist / play_by_language / play_by_emotion / play_random |
| `graph/tools/organizer_tools.py` | **Organizer 工具集（3 个）** | organize_files / dedup_files / analyze_structure |
| `graph/tools/metadata_tools.py` | **Metadata 工具集（5 个）** | diagnose_metadata / fix_single_song / fix_metadata_batch / sync_emotion_cache / update_song_tag |

---

## 3. hermes/ — 自研路由与自进化架构

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `hermes/__init__.py` | 模块导出 | 导出 Trigger/Gateway/Reflect/Memory/Skill |
| `hermes/trigger.py` | **Trigger 触发层** | `TriggerEvent` 统一事件格式 + 4 种 Trigger（ChatTrigger/CLITrigger/WebTrigger/FSMonitorTrigger），所有输入归一化为同一种结构 |
| `hermes/gateway.py` | **Gateway 网关层** | `HermesGateway` 纯 LLM Function Calling 做 4 路 Agent 分发，每次决策带 `reasoning` 审计字段；三级加速：Skill 模板匹配（0ms）→ 12 条 Meta 命令直接命中 → LLM 路由（~500ms） |
| `hermes/reflect.py` | **Reflect 反思引擎** | 快速路径（规则提取语言/情绪/歌手偏好，不调 LLM）+ 深度路径（LLM 结构化输出 JSON 提取记忆和技能），异常不阻塞主流程 |
| `hermes/memory.py` | **混合记忆存储** | SQLite 做精确关键词匹配 + ChromaDB（collection: `hermes_memory`）做语义检索，两路合并去重；置信度移动平均更新、访问计数追踪 |
| `hermes/skill.py` | **技能沉淀与匹配** | 9 个内置技能模板 + 动态注册；字符串模板匹配（如 `播放{artist}的歌`），按成功次数排序优先级 |

---

## 4. core/ — 底层引擎与数据层

### LLM & API

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `core/kimi_client.py` | **Kimi API 客户端** | httpx 封装，指数退避重试（429 限流 wait=2^attempt），支持 Function Calling；高层业务封装：意图分析、推荐理由生成、周报摘要生成 |

### 检索系统

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `core/vector_store.py` | **向量存储 + 混合检索** | ChromaDB 封装（BGE 中文 Embedding），Dense(ChromaDB) + Sparse(BM25) 双路并行 → RRF 融合排序；Embedding 不可用时自动回退 ChromaDB 默认模型 |
| `core/sparse_retriever.py` | **BM25 倒排索引** | 纯 Python 实现，零外部依赖；中文 2-gram 分词策略；JSON 持久化，支持增量重建 |
| `core/reranker.py` | 检索结果重排序 | 对初步检索结果做精排 |

### 数据库与存储

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `core/music_library_db.py` | **SQLite 音乐库 DB** | 歌曲元数据 CRUD、多条件组合筛选（artist/album/genre/language/emotion）、歌单管理、字段更新、CSV 导入导出 |
| `core/playlist_engine.py` | **智能歌单引擎** | 自然语言创建歌单（LLM 解析意图 → 筛选歌曲 → 生成 M3U8）、动态歌单刷新 |
| `core/playlist_manager.py` | 歌单管理器 | 歌单 CRUD 基础操作 |

### 元数据 & 分析

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `core/emotion_analyzer_simple.py` | **情绪分析器** | 4 维融合——LLM 歌词分析 + LLM 元数据推断（仅凭歌名/艺术家）+ 音频特征（pydub 响度/能量）+ 关键词匹配，加权投票决策；按文件哈希缓存结果 |
| `core/emotion_constants.py` | 情绪常量定义 | 9 种情绪的 key/中文名/关键词映射 |
| `core/language_detector.py` | **语言检测器** | 歌曲语言自动识别（标题+艺术家+文件路径多源判断） |
| `core/language_constants.py` | 语言常量定义 | 支持的语言列表与关键词 |
| `core/audio_language_detector.py` | 音频特征辅助语言检测 | 从音频信号特征推断语言 |
| `core/metadata_fetcher.py` | **元数据读取** | 基于 mutagen 从 FLAC/MP3/M4A 等格式读取 tag（artist/title/album/cover） |
| `core/metadata_scheduler.py` | **元数据调度器** | 批量诊断/修复/同步的编排逻辑，管理修复历史记录 |

### 文件管理

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `core/folder_watcher.py` | **文件系统监控** | 基于 watchdog 监听目录，文件新增/删除/变更自动触发扫描入库 |
| `core/audio_converter.py` | 音频格式转换 | FLAC/WAV/APE → MP3 |
| `core/audio_fingerprint.py` | 音频指纹 | 辅助去重（基于音频内容而非文件名） |
| `core/logging_config.py` | 日志配置 | 统一日志格式与级别 |

---

## 5. agents/ — 能力 Agent 实现

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `agents/__init__.py` | 模块导出 | |
| `agents/base_agent.py` | Agent 基类 | 定义 run/scan 等通用接口 |
| `agents/librarian.py` | **Librarian 单例** | 持有 VectorStore + BM25 索引，提供 query()/scan()/get_stats() 等核心能力；所有节点和工具通过 `get_librarian()` 获取唯一实例 |
| `agents/organizer.py` | OrganizerAgent | 文件整理策略（artist/album、genre/artist 等）、预览与执行、去重检测 |
| `agents/metadata_enhancer.py` | MetadataEnhancer | 在线搜索补全元数据（调用外部 API + Kimi LLM） |
| `agents/qq_music.py` | QQ 音乐 API 对接 | 歌词/元数据的外部数据源 |

---

## 6. web/ — Web UI

| 文件 | 一句话 | 关键细节 |
|---|---|---|
| `web/app.py` | **Streamlit Web 界面** | 5 个页面：首页（统计+扫描+监控开关）、音乐库（多维筛选+详情展开+单曲编辑+歌单管理）、整理（预览/执行）、智能歌单（自然语言创建+管理）、元数据诊断（诊断/修复/历史） |

---

## 7. data/ — 持久化数据

| 路径 | 引擎 | 内容 |
|---|---|---|
| `data/music_library.db` | SQLite | 歌曲元数据（artist/title/album/genre/language/emotion/play_count 等） |
| `data/chroma/` | ChromaDB | 音乐库语义向量（collection: `music_library`），BGE embedding |
| `data/chroma_memory/` | ChromaDB | 记忆语义向量（collection: `hermes_memory`） |
| `data/bm25_index.json` | JSON | BM25 倒排索引持久化文件 |
| `data/emotion_cache.json` | JSON | 情绪分析缓存，按文件哈希索引 |
| `data/hermes_memory.db` | SQLite | 结构化记忆（preference/fact/correction/pattern） |

---

## 快速定位指南

| 你想... | 去看 |
|---|---|
| 理解整体架构 | [CLAUDE.md](CLAUDE.md) → [graph/graph.py](graph/graph.py) |
| 看 LLM 怎么被调用的 | [core/kimi_client.py](core/kimi_client.py) → [graph/kimi_adapter.py](graph/kimi_adapter.py) |
| 看意图路由怎么做的 | [hermes/gateway.py](hermes/gateway.py) → [graph/nodes/gateway_node.py](graph/nodes/gateway_node.py) |
| 看 Agent 怎么用工具的 | [graph/nodes/librarian_node.py](graph/nodes/librarian_node.py) → [graph/tools/library_tools.py](graph/tools/library_tools.py) |
| 看自进化怎么实现的 | [hermes/reflect.py](hermes/reflect.py) → [hermes/memory.py](hermes/memory.py) → [hermes/skill.py](hermes/skill.py) |
| 看混合检索怎么做的 | [core/vector_store.py](core/vector_store.py) → [core/sparse_retriever.py](core/sparse_retriever.py) |
| 看情绪分析怎么做的 | [core/emotion_analyzer_simple.py](core/emotion_analyzer_simple.py) |
| 看 Web UI 怎么构建的 | [web/app.py](web/app.py) |
| 看一个完整的对话请求怎么流转 | [chat_unified.py](chat_unified.py) → [graph/nodes/gateway_node.py](graph/nodes/gateway_node.py) → [graph/nodes/librarian_node.py](graph/nodes/librarian_node.py) → [graph/nodes/reflect_node.py](graph/nodes/reflect_node.py) → [graph/nodes/respond_node.py](graph/nodes/respond_node.py) |
