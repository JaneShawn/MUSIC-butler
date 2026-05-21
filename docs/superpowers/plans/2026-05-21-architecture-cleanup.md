# Architecture Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清理架构冗余：把 `respond_node` 中的业务逻辑归位到正确节点，把监控指令拦截移到 chat 层，删除已被 LangGraph MemorySaver 替代的 `ContextManager` 死代码。

**Architecture:**
- `respond_node` 职责收窄为：只处理 help/clear/exit/cancel 等纯文本回复，以及格式化兜底
- `scan`/`show_language_stats`/`analyze_emotion`/`clear_emotion_cache`/`show_library_stats` 路由到 `librarian_node` 处理
- `monitor` 指令在 `chat_unified.py` 的 `chat()` 方法里提前拦截，不进入 graph
- `ContextManager`、`SessionState`、`PendingAction`、`Message` 从 `chat/context.py` 删除（保留 `NLPUtils`）
- `chat_unified.py` 中的 `self.context = ContextManager(...)` 引用一并删除

**Tech Stack:** Python, LangGraph, LangChain

---

## File Map

| 文件 | 操作 | 说明 |
|------|------|------|
| `graph/router.py` | 修改 | 把 scan/stats/emotion 等路由从 respond 改到 librarian |
| `graph/nodes/librarian_node.py` | 修改 | 新增处理 scan/show_language_stats/analyze_emotion/clear_emotion_cache/show_library_stats 的分支 |
| `graph/nodes/respond_node.py` | 修改 | 删除 scan/stats/emotion/monitor 相关业务逻辑，只保留纯文本指令和兜底 |
| `chat_unified.py` | 修改 | 删除 ContextManager 引用；在 chat() 方法里拦截 monitor 指令 |
| `chat/context.py` | 修改 | 删除 ContextManager、SessionState、PendingAction、Message 类，只保留 NLPUtils |

---

## Task 1: 把 scan/stats/emotion 路由从 respond 改到 librarian

**Files:**
- Modify: `graph/router.py`

- [ ] **Step 1: 修改 router.py 的路由表**

把以下意图从 `respond` 改为 `librarian`：

```python
# graph/router.py
def route_by_intent(state) -> str:
    intent = state.get("intent", "respond")

    routing_map = {
        # Librarian 域
        "query": "librarian",
        "search": "librarian",
        "play_by_name": "librarian",
        "play_by_artist": "librarian",
        "play_all": "librarian",
        "play_random": "librarian",
        "play": "librarian",
        "play_all_results": "librarian",
        "play_all_except": "librarian",
        "batch_select": "librarian",
        "playlist_from_results": "librarian",
        "query_emotion_songs": "librarian",
        "query_language_songs": "librarian",
        "recommend_random": "librarian",
        "scan": "librarian",                  # 从 respond 移来
        "show_language_stats": "librarian",   # 从 respond 移来
        "analyze_emotion": "librarian",       # 从 respond 移来
        "clear_emotion_cache": "librarian",   # 从 respond 移来
        "show_library_stats": "librarian",    # 从 respond 移来

        # Organizer 域
        "organize": "organizer",
        "dedup": "organizer",
        "analyze": "organizer",

        # Metadata 域
        "fix_metadata": "metadata",
        "fix_single": "metadata",
        "diagnose": "metadata",
        "fix_metadata_issues": "metadata",
        "sync_emotion": "metadata",

        # 直接 respond 的简单指令（纯文本，无业务逻辑）
        "help": "respond",
        "clear": "respond",
        "exit": "respond",
        "cancel": "respond",
        "monitor": "respond",         # 临时保留，Task 3 会把它彻底移出 graph
        "list_playlists": "respond",
        "list_models": "respond",
        "switch_model": "respond",
        "current_model": "respond",
        "correct_language": "respond",
        "correct_emotion": "respond",
        "update_song_info": "respond",
        "detect_single_language": "respond",
        "analyze_single_emotion": "respond",
        "playlist": "respond",
        "smart_playlist": "respond",
        "export_library": "respond",
        "import_library": "respond",
        "convert": "respond",
    }

    return routing_map.get(intent, "respond")
```

- [ ] **Step 2: Commit**

```bash
cd "c:\Users\JaneShown\Desktop\music\music-agent"
git add graph/router.py
git commit -m "refactor: route scan/stats/emotion intents to librarian_node"
```

---

## Task 2: librarian_node 接管 scan/stats/emotion 业务逻辑

**Files:**
- Modify: `graph/nodes/librarian_node.py`
- Modify: `graph/nodes/respond_node.py`

- [ ] **Step 1: 在 librarian_node.py 中新增分支处理这五个意图**

在 `librarian_node` 函数开头（`agent = _get_agent()` 之前）插入意图分支：

```python
def librarian_node(state: MusicAgentState) -> Dict[str, Any]:
    """Librarian Agent 节点入口"""
    intent = state.get("intent", "query")
    params = state.get("task_params", {})
    messages = state.get("messages", [])
    trace = state.get("agent_trace", [])

    # 管理类意图：直接处理，不走 react agent
    if intent == "scan":
        return _handle_scan(trace)

    if intent == "show_language_stats":
        return _handle_language_stats(trace)

    if intent == "analyze_emotion":
        return _handle_emotion_stats(state, trace)

    if intent == "clear_emotion_cache":
        return _handle_clear_emotion_cache(trace)

    if intent == "show_library_stats":
        return _handle_library_stats(trace)

    # 原有逻辑
    if not messages:
        return {
            "final_response": "请告诉我你想做什么。",
            "agent_trace": trace + ["librarian: no input"],
        }

    user_input = msg_content(messages[-1])
    agent = _get_agent()
    result = agent.invoke({"messages": [("user", user_input)]})

    final_msgs = result.get("messages", [])
    assistant_reply = ""
    for msg in reversed(final_msgs):
        if hasattr(msg, "content") and msg.content:
            assistant_reply = msg.content
            break

    if not assistant_reply:
        assistant_reply = "搜索完成，请在结果中查看。"

    query_results = _extract_query_results(final_msgs)

    return {
        "final_response": assistant_reply,
        "query_results": query_results,
        "agent_trace": trace + ["librarian: done"],
    }
```

- [ ] **Step 2: 在 librarian_node.py 末尾添加四个 handler 函数**

```python
def _handle_scan(trace: list) -> Dict[str, Any]:
    try:
        from agents.librarian import get_librarian
        agent = get_librarian()
        result = agent.scan_library()
        total = result.get("total_files", 0)
        new_songs = result.get("new_songs", 0)
        indexed = result.get("total_indexed", 0)
        lines = [
            "🔍 扫描完成！",
            "=" * 30,
            f"  扫描文件: {total} 个",
            f"  新增歌曲: {new_songs} 首",
            f"  已索引总数: {indexed} 首",
        ]
        return {"final_response": "\n".join(lines), "agent_trace": trace + ["librarian: scan done"]}
    except Exception as e:
        return {"final_response": f"⚠️ 扫描失败: {e}", "agent_trace": trace + ["librarian: scan failed"]}


def _handle_language_stats(trace: list) -> Dict[str, Any]:
    from core.music_library_db import get_library_db
    lib_db = get_library_db()
    records = lib_db.list_all()
    stats = {}
    for rec in records:
        lang = rec.language or "未知"
        stats[lang] = stats.get(lang, 0) + 1
    total = sum(stats.values())
    lines = ["📊 歌曲语言分布统计", "=" * 40]
    for lang, count in sorted(stats.items(), key=lambda x: -x[1]):
        bar = "█" * (count * 30 // total if total > 0 else 0)
        lines.append(f"  {lang:6} | {bar:30} | {count}首")
    lines.append("=" * 40)
    lines.append(f"总计: {total} 首")
    return {"final_response": "\n".join(lines), "agent_trace": trace + ["librarian: language_stats done"]}


def _handle_emotion_stats(state: MusicAgentState, trace: list) -> Dict[str, Any]:
    from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
    from agents.librarian import get_librarian
    from core.kimi_client import KimiClient
    from graph.utils import load_config

    agent = get_librarian()
    kimi = None
    try:
        kimi = KimiClient(config=load_config())
    except Exception:
        pass
    analyzer = SimpleEmotionAnalyzer(kimi_client=kimi)

    songs = list(agent.songs.values())
    has_cache = any(
        analyzer._get_file_hash(s.file_path) in analyzer._cache
        for s in songs
    )
    force = state.get("task_params", {}).get("force", False)
    if not has_cache or force:
        songs_to_analyze = [
            {"file_path": s.file_path, "title": s.title, "artist": s.artist, "lyrics": None}
            for s in songs
        ]
        analyzer.batch_analyze(songs_to_analyze, verbose=False)

    emotion_stats = {}
    for song in songs:
        cache_key = analyzer._get_file_hash(song.file_path)
        if cache_key in analyzer._cache:
            emotion = analyzer._cache[cache_key].get("emotion", "unknown")
            emotion_stats[emotion] = emotion_stats.get(emotion, 0) + 1

    if not emotion_stats:
        return {"final_response": "暂无情绪分析结果。", "agent_trace": trace + ["librarian: emotion_stats empty"]}

    emotion_names = {
        'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
        'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
        'angry': '愤怒', 'focus': '专注', 'party': '派对',
    }
    total = sum(emotion_stats.values())
    lines = ["🎭 歌曲情绪分布统计", "=" * 40]
    for emotion, count in sorted(emotion_stats.items(), key=lambda x: -x[1]):
        name = emotion_names.get(emotion, emotion)
        bar = "█" * (count * 30 // total if total > 0 else 0)
        lines.append(f"  {name:6} | {bar:30} | {count}首")
    lines.append("=" * 40)
    lines.append(f"总计: {total} 首")
    return {"final_response": "\n".join(lines), "agent_trace": trace + ["librarian: emotion_stats done"]}


def _handle_clear_emotion_cache(trace: list) -> Dict[str, Any]:
    from pathlib import Path as _P
    cache = _P("data/emotion_cache.json")
    if cache.exists():
        cache.unlink()
        return {"final_response": "✅ 情绪缓存已清除。下次分析情绪时会重新调用 Kimi 分析。",
                "agent_trace": trace + ["librarian: clear_emotion_cache done"]}
    return {"final_response": "📭 没有情绪缓存需要清除。",
            "agent_trace": trace + ["librarian: clear_emotion_cache noop"]}


def _handle_library_stats(trace: list) -> Dict[str, Any]:
    try:
        from agents.librarian import get_librarian
        agent = get_librarian()
        stats = agent.get_stats()
        lines = [
            "📊 音乐库统计",
            "=" * 30,
            f"  总歌曲数: {stats.get('total_songs', 0)}",
            f"  总艺术家: {stats.get('total_artists', 0)}",
            f"  总流派数: {stats.get('total_genres', 0)}",
        ]
        return {"final_response": "\n".join(lines), "agent_trace": trace + ["librarian: library_stats done"]}
    except Exception:
        return {"final_response": "📊 无法获取库统计，请先执行「扫描」。",
                "agent_trace": trace + ["librarian: library_stats failed"]}
```

- [ ] **Step 3: 从 respond_node.py 删除已迁移的业务逻辑**

在 `respond_node.py` 中：
1. 删除 `_handle_scan` 函数（整个函数）
2. 删除 `_show_language_stats` 函数（整个函数）
3. 删除 `_show_emotion_stats` 函数（整个函数）
4. 在 `respond_node` 函数体内，删除以下 if 分支（共5个）：
   - `if intent == "scan":` → `return _handle_scan(trace)` 这一块
   - `if intent == "show_language_stats":` 这一块
   - `if intent == "analyze_emotion":` 这一块
   - `if intent == "clear_emotion_cache":` 这一块
   - `if intent == "show_library_stats":` 这一块

删除后 `respond_node` 函数体从 `if final_response:` 起，直接跳到 `if intent == "help":` 分支。

- [ ] **Step 4: Commit**

```bash
cd "c:\Users\JaneShown\Desktop\music\music-agent"
git add graph/nodes/librarian_node.py graph/nodes/respond_node.py
git commit -m "refactor: move scan/stats/emotion handlers to librarian_node"
```

---

## Task 3: monitor 指令移到 chat 层拦截

**Files:**
- Modify: `chat_unified.py`
- Modify: `graph/router.py`
- Modify: `graph/nodes/respond_node.py`

- [ ] **Step 1: 在 chat_unified.py 的 chat() 方法里添加 monitor 拦截**

把 `chat()` 方法替换为：

```python
def chat(self, user_input: str) -> str:
    """单轮对话：传入用户输入，返回助手回复。"""
    # monitor 指令在 chat 层直接处理，不进入 graph
    monitor_result = self._handle_monitor_command(user_input)
    if monitor_result is not None:
        return monitor_result

    config = {"configurable": {"thread_id": self.thread_id}}
    result = self.graph.invoke(
        {"messages": [HumanMessage(content=user_input)]},
        config=config,
    )

    response = result.get("final_response", "")
    if not response:
        msgs = result.get("messages", [])
        for m in reversed(msgs):
            content = m.content if hasattr(m, 'content') else m.get("content", "")
            if content and (hasattr(m, 'type') and m.type == 'ai' or m.get('role') == 'assistant'):
                response = content
                break

    return response or "处理完成。"
```

- [ ] **Step 2: 在 chat_unified.py 中添加 _handle_monitor_command 方法**

在 `MusicAgentChat` 类里，`chat()` 方法之前添加：

```python
def _handle_monitor_command(self, user_input: str) -> str | None:
    """处理监控指令，返回回复字符串；不是监控指令则返回 None。"""
    start_words = ["开启监控", "启动监控", "打开监控", "开始监控"]
    stop_words = ["关闭监控", "停止监控", "关掉监控"]
    status_words = ["监控状态", "监控"]

    if any(w in user_input for w in stop_words):
        if hasattr(self, '_watcher') and self._watcher.is_running:
            self._watcher.stop()
            return "🔍 文件监控已停止。"
        return "🔍 文件监控未在运行。"

    if any(w in user_input for w in start_words):
        if hasattr(self, '_watcher') and self._watcher.is_running:
            return "🔍 文件监控已在运行中。"
        self._start_watcher()
        return "🔍 文件监控已启动。"

    if user_input.strip() in status_words:
        running = hasattr(self, '_watcher') and self._watcher.is_running
        if running:
            return "🔍 文件监控运行中。输入「关闭监控」停止。"
        return "🔍 文件监控未启动。输入「开启监控」自动监听音乐库目录。"

    return None
```

- [ ] **Step 3: 从 router.py 删除 monitor 路由条目**

在 `graph/router.py` 的 `routing_map` 中删除这一行：
```python
"monitor": "respond",
```

- [ ] **Step 4: 从 respond_node.py 删除 monitor 相关代码**

1. 删除文件顶部的 `_watcher = None` 全局变量
2. 删除 `respond_node` 函数体中的 `if intent == "monitor":` 分支（调用 `_handle_monitor` 的那一块）
3. 删除文件末尾的 `_handle_monitor` 函数（整个函数，约50行）
4. 删除 `from core.folder_watcher import FolderWatcher` 这行 import（如果只在 `_handle_monitor` 里用到）

- [ ] **Step 5: Commit**

```bash
cd "c:\Users\JaneShown\Desktop\music\music-agent"
git add chat_unified.py graph/router.py graph/nodes/respond_node.py
git commit -m "refactor: move monitor commands to chat layer, out of graph"
```

---

## Task 4: 删除 ContextManager 死代码

**Files:**
- Modify: `chat/context.py`
- Modify: `chat_unified.py`

- [ ] **Step 1: 清理 chat/context.py，只保留 NLPUtils**

把 `chat/context.py` 的内容替换为：

```python
# -*- coding: utf-8 -*-
"""
Chat Context - NLP 工具类
ContextManager 已由 LangGraph MemorySaver 替代，此文件只保留 NLPUtils。
"""
from core.emotion_constants import EMOTION_KEYWORDS, MOOD_KEYWORDS


class NLPUtils:
    """NLP 工具类 - 处理中文文本的边界情况"""

    STOP_WORDS = {
        '的', '了', '吗', '呢', '吧', '啊', '哦', '嗯', '呗', '嘛',
        '是', '有', '在', '和', '与', '或', '这', '那', '它', '个',
    }

    SONG_SUFFIXES = [
        '这首歌的', '这首的', '这个的', '这首歌', '这首', '这个',
        '的歌曲', '的歌', '之歌', '版本', '版',
    ]

    ARTIST_SUFFIXES = [
        '唱的歌', '唱的', '的作品', '的歌', '的',
    ]

    EMOTION_KEYWORDS = EMOTION_KEYWORDS
    MOOD_KEYWORDS = MOOD_KEYWORDS

    @classmethod
    def clean_song_name(cls, text: str) -> str:
        if not text:
            return text
        original = text.strip()
        if len(original) <= 2:
            return original
        cleaned = original
        while cleaned and len(cleaned) > 2 and cleaned[0] in cls.STOP_WORDS:
            cleaned = cleaned[1:].strip()
        while cleaned and len(cleaned) > 2 and cleaned[-1] in cls.STOP_WORDS:
            cleaned = cleaned[:-1].strip()
        for suffix in cls.SONG_SUFFIXES:
            if cleaned.endswith(suffix) and len(cleaned) - len(suffix) >= 2:
                cleaned = cleaned[:-len(suffix)].strip()
                break
        while cleaned and len(cleaned) > 2 and cleaned[0] in cls.STOP_WORDS:
            cleaned = cleaned[1:].strip()
        while cleaned and len(cleaned) > 2 and cleaned[-1] in cls.STOP_WORDS:
            cleaned = cleaned[:-1].strip()
        if len(cleaned) < 2 or len(cleaned) < len(original) * 0.3:
            return original
        return cleaned

    @classmethod
    def clean_artist_name(cls, text: str) -> str:
        if not text:
            return text
        text = text.strip()
        for suffix in sorted(cls.ARTIST_SUFFIXES, key=len, reverse=True):
            if text.endswith(suffix):
                text = text[:-len(suffix)].strip()
                break
        return text

    @classmethod
    def normalize_input(cls, text: str) -> str:
        if not text:
            return text
        text = ' '.join(text.split())
        text = text.replace('，', ',').replace('。', '.').replace('？', '?').replace('！', '!')
        text = text.strip('.,!?;:，。！？；：')
        return text.strip()
```

- [ ] **Step 2: 删除 chat_unified.py 中的 ContextManager 引用**

在 `MusicAgentChat.__init__` 方法中，找到并删除这三行：

```python
# 上下文兼容（旧代码引用 self.context 时不报错）
from chat.context import ContextManager
self.context = ContextManager(session_file=current_dir / "chat_session.json")
```

- [ ] **Step 3: 确认没有其他地方引用 ContextManager**

```bash
cd "c:\Users\JaneShown\Desktop\music\music-agent"
grep -r "ContextManager" --include="*.py" .
grep -r "chat_session.json" --include="*.py" .
grep -r "self\.context\." --include="*.py" .
```

如果有其他引用，逐一删除。如果没有，继续下一步。

- [ ] **Step 4: Commit**

```bash
cd "c:\Users\JaneShown\Desktop\music\music-agent"
git add chat/context.py chat_unified.py
git commit -m "refactor: remove ContextManager dead code, keep NLPUtils"
```

---

## Task 5: 验证整体功能

- [ ] **Step 1: 检查没有语法错误**

```bash
cd "c:\Users\JaneShown\Desktop\music\music-agent"
python -c "from graph.graph import music_graph; print('graph OK')"
python -c "from chat_unified import MusicAgentChat; print('chat OK')"
```

期望输出：
```
graph OK
chat OK
```

- [ ] **Step 2: 确认路由覆盖完整（没有意图丢失）**

```bash
cd "c:\Users\JaneShown\Desktop\music\music-agent"
python -c "
from graph.router import route_by_intent
tests = [
    ('scan', 'librarian'),
    ('show_language_stats', 'librarian'),
    ('analyze_emotion', 'librarian'),
    ('clear_emotion_cache', 'librarian'),
    ('show_library_stats', 'librarian'),
    ('help', 'respond'),
    ('query', 'librarian'),
    ('fix_metadata', 'metadata'),
    ('organize', 'organizer'),
]
for intent, expected in tests:
    result = route_by_intent({'intent': intent})
    status = 'OK' if result == expected else f'FAIL (got {result})'
    print(f'  {intent}: {status}')
"
```

期望全部输出 OK。

- [ ] **Step 3: Final commit**

```bash
cd "c:\Users\JaneShown\Desktop\music\music-agent"
git log --oneline -5
```

确认4个 commit 都在历史里。
