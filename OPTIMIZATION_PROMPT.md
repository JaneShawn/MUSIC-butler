# MUSIC-butler 项目优化 Prompt

## 项目现状

- **语言**: Python 3.11
- **核心**: LLM Agent 音乐管家，基于 Kimi API + ChromaDB + SQLite
- **代码规模**: ~4000行主文件 + 14个core模块 + 7个agents
- **GitHub**: github.com/JaneShawn/music-butler

## 当前问题清单（按优先级排序）

### P0 - 架构问题
1. `chat_unified.py` 4000+行，包含意图识别、20+个handler、上下文管理、播放逻辑，需要拆分
2. 三个入口文件（chat.py / chat_enhanced.py / chat_unified.py）混乱，应统一
3. `core/` 中 `audio_fingerprint.py` 和 `local_llm.py` 疑似死代码，未在项目中引用

### P0 - 数据债务
4. SQLite 907条记录 vs 实际405个文件，502条幽灵记录
5. `language` 字段全空（0/907），每次查询都要现场检测
6. `emotion` 字段全空（0/907），emotion_cache.json 不存在

### P1 - 代码质量
7. 日志系统混乱：print 和 logging 混用，没有统一日志级别
8. 错误处理薄弱：大量 API 调用（Kimi/网易云/QQ音乐）没有 try-except 兜底
9. 类型注解不完整：很多函数参数和返回值没有类型提示
10. 配置管理松散：config.yaml 没有完整利用，很多硬编码常量散落在代码中

### P1 - 测试与文档
11. 测试覆盖率极低：只有一个 `test_librarian.py`
12. 文档分散：README.md / CHAT_README.md / EMOTION_ANALYSIS.md / FFMPEG_INSTALL.md 内容过时

### P2 - 功能完善
13. `sentence-transformers` 未安装，ChromaDB 用默认 embedding，向量搜索精度低
14. `openai-whisper` 未安装，音频语言检测（第6层兜底）不可用
15. Web 界面（streamlit）与主程序脱节，未同步最新功能

---

## 优化 Prompt（复制给 Kimi 执行）

```
你是一个资深 Python 架构师。请帮我优化 music-butler 项目。

项目地址: github.com/JaneShawn/music-butler
技术栈: Python 3.11, Kimi API, ChromaDB, SQLite, Prompt Engineering

### 第一步：架构拆分
把 chat_unified.py (~4000行) 按职责拆分为：
1. `chat/intent_engine.py` - 意图识别（understand_intent, _llm_understand_intent, _parse_multi_select）
2. `chat/handlers.py` - 所有 handler（handle_query, handle_play_by_name, handle_playlist...）
3. `chat/context.py` - 上下文管理（ContextManager, SessionState, PendingAction）
4. `chat/chat_engine.py` - 主控（execute, run）
5. `chat/__init__.py` - 对外暴露 MusicAgentChat

保持向后兼容：chat_unified.py 保留为入口文件，内部 import 新模块。

### 第二步：数据修复
1. 运行 scan_library() 清理幽灵记录（同时清理内存+ChromaDB+SQLite）
2. 批量语言检测：遍历所有歌曲，把 language 写入 SQLite（复用 LanguageDetector 6层体系）
3. 批量情绪分析：遍历所有歌曲，生成 emotion_cache.json（复用 SimpleEmotionAnalyzer）

### 第三步：代码质量提升
1. 统一日志：用 `logging` 替代所有 `print`，建立 `core/logger.py`
2. 错误处理：给所有外部 API 调用（Kimi/网易云/QQ音乐）加 try-except + 重试机制
3. 类型注解：给核心函数（尤其是 DB 层和 Agent 层）补全类型提示
4. 配置集中：把散落在代码中的常量（相似度阈值、top_k、缓存版本号等）收归 config.yaml

### 第四步：测试覆盖
1. 给 `core/music_library_db.py` 写单元测试
2. 给 `core/language_detector.py` 写单元测试
3. 给 `agents/librarian.py` 的 query/scan 方法写集成测试

### 输出要求
- 每步修改后给出 git diff 摘要
- 标注哪些改动是 breaking change（需要用户注意的）
- 给出测试验证命令
```

---

## 手动执行清单（不想用AI的话）

### 立即可做（5分钟）
- [ ] 删除 `chat.py` 和 `chat_enhanced.py`（已被 chat_unified.py 取代）
- [ ] 检查 `audio_fingerprint.py` 和 `local_llm.py` 是否被引用，如无则删除
- [ ] 运行 `python main.py` 输入"扫描"清理幽灵记录

### 今天可做（1-2小时）
- [ ] 创建 `chat/` 目录，把 chat_unified.py 拆成 4 个文件
- [ ] 补全 config.yaml：把相似度阈值、缓存版本号、top_k 等常量收进去
- [ ] 用 `logging` 替代 `agents/librarian.py` 中的 print

### 本周可做（半天）
- [ ] 批量语言检测：写脚本遍历 songs，调用 LanguageDetector，结果写入 SQLite
- [ ] 批量情绪分析：写脚本遍历 songs，调用 SimpleEmotionAnalyzer，生成 emotion_cache.json
- [ ] 给 `music_library_db.py` 写 pytest 单元测试

### 长期优化
- [ ] 安装 sentence-transformers 提升向量搜索精度
- [ ] 安装 openai-whisper 启用音频语言检测
- [ ] 同步 Web 界面（streamlit）与主程序功能

---

## 预期收益

| 优化项 | 收益 |
|---|---|
| 拆分 chat_unified.py | 代码可维护性提升，新功能开发效率提升 |
| 清理幽灵记录 | 查询结果更准确，避免播放不存在的文件 |
| 补全 language | 语言查询从"现场检测400首"变为"O(1)索引查询"，速度提升100倍 |
| 补全 emotion | 情绪查询从"向量搜索盲猜"变为"精确标签匹配"，准确率大幅提升 |
| 统一日志 | 排查问题效率提升，支持日志级别控制 |
| 错误处理 | API 不可用时程序不崩溃，用户体验更稳定 |
