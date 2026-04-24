# Changelog

## [Unreleased] - 近期更新

### 新增
- **播放歌手全集 (`play_by_artist`)**："播放周杰伦的歌"一键播放该歌手全部歌曲，生成 M3U8 直接调用 foobar2000
- **情绪手动纠正体系 (`correct_emotion`)**："标记晴天为快乐的歌"命令式纠正 + "晴天是悲伤的歌"自然语言更新
- **情绪查询三级过滤**：`emotion_cache` (含手动纠正) → `SQLite` → 向量搜索 fallback
- **歌名清洗器 (`_clean_play_name`)**：自动去除《》、歌手名后缀、"的歌"等通用后缀

### 修复
- **Artist 查询子串匹配**："Kanye" 现在能匹配 "Kanye West"，不再要求精确相等
- **Artist 查询误伤**：向量搜索对 `artist:xxx` 语法不可靠，改为内存/DB 精确过滤
- **"播放xxx的歌"误识别为 `play_by_name`**："播放开心的歌"/"播放周杰伦的歌"等现在正确识别为 query/playlist/play_by_artist
- **"分析情绪"被 LLM 误判为 `analyze_single_emotion`**：硬编码高优先级拦截，无歌名时走批量分析
- **指代词解析索引错位**："分析第4首"现在正确取 `last_query_results[3]` 而不是 `[2]`
- **歌名错别字缓存固化**：LLM Prompt 增加约束"必须原样保留用户输入"，缓存版本升级到 v4
- **对话历史污染自动清理**：从 `chat_session.json` 删除错误轮次，防止 LLM 被带偏
- **API 不可用时 fallback 缺失**：硬编码 fallback 新增"播放"兜底逻辑

### 架构改进
- **SQLite 为主数据源**：`music_library_db` 从 JSON 全量读写迁移到 SQLite，支持增量更新、事务、SQL 查询
- **ChromaDB 降级为搜索索引**：重启后从 SQLite 加载完整数据，ChromaDB 仅用于语义搜索，损坏可重建
- **幽灵记录自动清理**：`scan_library()` 同时清理内存 `self.songs`、ChromaDB、SQLite 中文件已不存在的残留记录
- **LLM 意图识别混合架构**：硬编码高优先级 → LLM 语义理解 → fallback 硬编码，支持 few-shot、对话历史、意图缓存、白名单校验

---

## [Initial] - 2026-04-20

- 项目初始化：`music-butler` 私人音乐数据管家
- 核心架构：Agent 体系（Librarian / Curator / Scout / Organizer / MetadataEnhancer）
- 技术栈：Kimi API、ChromaDB 向量搜索、SQLite 持久化、Whisper 音频检测
