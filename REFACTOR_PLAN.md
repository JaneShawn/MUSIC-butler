# 渐进式重构计划

## 现状
- chat_unified.py: 4108 行，62 个方法
- 已创建 chat/context.py（9107 chars，提取了 NLPUtils + ContextManager）

## 第一阶段：低风险拆分（今天可做）

### 1. 完善 chat/context.py
```bash
# 已创建，需要验证
python -c "from chat.context import ContextManager, NLPUtils, SessionState; print('OK')"
```

### 2. 创建 chat/__init__.py
导出公共接口。

### 3. 保留 chat_unified.py 作为入口
不动现有代码，先保证功能正常。

## 第二阶段：核心提取（本周）

### 4. 提取 chat/intent_engine.py
只提取 5 个方法：
- understand_intent
- _parse_multi_select
- _llm_understand_intent
- _check_context
- _base_intent

这些方法依赖：NLPUtils、ContextManager、KimiClient
不依赖：任何 handler

### 5. 提取 chat/playlist_utils.py
提取播放列表相关工具方法：
- _create_m3u8_playlist
- _play_with_foobar2000
- _clean_play_name

这些方法纯工具性，无状态依赖。

## 第三阶段：Handler 分组（下周）

### 6. 按职责分组 Handler

| 文件 | Handler |
|---|---|
| chat/handlers/query.py | handle_query, handle_discover, handle_recommend_random |
| chat/handlers/play.py | handle_play_by_name, handle_play_by_artist, handle_play_all, handle_play, handle_playlist, handle_playlist_from_results, handle_batch_select |
| chat/handlers/analyze.py | handle_analyze, handle_analyze_single_emotion, handle_analyze_emotion, handle_show_language_stats, handle_query_emotion_songs, handle_query_language_songs |
| chat/handlers/manage.py | handle_scan, handle_organize, handle_dedup, handle_fix_metadata, handle_fix_single_metadata, handle_convert, handle_delete_wav |
| chat/handlers/info.py | handle_info, handle_export_library, handle_import_library, handle_show_library_stats, handle_export_language_csv, handle_correct_language, handle_correct_emotion, handle_update_song_info |
| chat/handlers/model.py | handle_list_models, handle_switch_model, handle_current_model, handle_detect_language_by_audio, handle_detect_single_language |
| chat/handlers/chat.py | handle_chat, handle_cancel, handle_clear, handle_help |

### 7. 提取 chat/chat_engine.py
主控类：execute + run + 属性初始化

## 第四阶段：清理（下下周）

### 8. 重构 chat_unified.py 为薄入口
```python
from chat.chat_engine import MusicAgentChat
__all__ = ["MusicAgentChat"]
```

### 9. 删除旧入口
- chat.py
- chat_enhanced.py

---

## 立即可做的事（5分钟）

1. 验证 context.py 语法
2. 创建 chat/__init__.py
3. 删除 chat.py 和 chat_enhanced.py

## 今天可做（1-2小时）

4. 提取 intent_engine.py（5个方法，依赖最少）
5. 提取 playlist_utils.py（3个纯工具方法）

## 本周可做（半天）

6. 按组提取 Handler（分7个文件）
7. 重构 chat_engine.py

## 关键原则

- **每次只拆一组**，拆完验证语法
- **不改方法签名**，避免连锁修改
- **chat_unified.py 最后才删**，保证随时可回退
