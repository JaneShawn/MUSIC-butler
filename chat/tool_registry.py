"""
[DEPRECATED] ToolRegistry — Function Calling 工具定义（OpenAI 兼容格式）。

Phase 2 起不再使用。架构已变更：
  旧: intent_router → LLM FC (32 个细粒度 tool) → 选 intent
  新: HermesGateway → LLM FC (4 个 agent dispatch) → 选 agent → agent 内部 ReAct 选 tool

各 Agent 的工具现在定义在 graph/tools/ 下：
  - library_tools.py  (librarian, 10 tools)
  - organizer_tools.py (organizer, 3 tools)
  - metadata_tools.py  (metadata, 5 tools)

保留此文件仅作参考。
"""
from typing import Dict, Any


class ToolRegistry:
    """32 个 Function Calling 工具定义，供 KimiClient.chat_completion() 使用。"""

    @staticmethod
    def build_system_prompt() -> str:
        # [可修改] system prompt — 改了这里会影响 LLM 对所有请求的理解和路由行为。
        # 描述越详细，LLM 越准确，但 token 消耗也越大。
        return """你是一个音乐管理助手 Music Agent，帮助用户管理本地音乐库。

你可以：搜索歌曲、按语言/情绪筛选、播放歌曲、创建歌单、扫描整理音乐库、
修复元数据、发现新音乐、分析情绪、下载歌词、导出/导入音乐库、管理实时监控。

当用户有明确的操作意图时，调用对应的工具。不确定时可以先回答或反问用户。
优先用工具完成任务，而不是用文字描述你能做什么。"""

    @staticmethod
    def get_tools() -> list:
        # [可修改] 工具数组 — 新增/删除/修改工具在这里改。
        # 每个工具的定义直接影响 LLM 如何理解和路由用户请求。
        # 警告：删工具前确保 execute() handlers 里没有对应的 key，否则运行时报错。
        return [
            # === 搜索/查询 ===
            {
                "type": "function",
                "function": {
                    "name": "query",
                    "description": "模糊搜索音乐库。用户想找歌但没有明确限定语言或情绪时使用。例如：'周杰伦的歌'、'90年代摇滚'、'有什么好听的歌'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query_text": {"type": "string", "description": "用户的完整搜索意图原文"},
                        },
                        "required": ["query_text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_language_songs",
                    "description": "列出/播放所有特定语言的歌曲。例如：'播放所有国语歌'、'粤语歌有哪些'、'所有英文歌'。当用户说'播放所有X语歌'时，play=true",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "language": {
                                "type": "string",
                                "description": "语言名称",
                                # [可修改] 语言列表 — 加新语言在这里加，同时更新 LANGUAGE_ALIAS
                                "enum": ["国语", "英语", "粤语", "日语", "韩语", "法语", "德语", "西班牙语"],
                            },
                            "play": {
                                "type": "boolean",
                                "description": "用户是否要求直接播放（而非仅列出）。包含'播放'/'放'/'听'等动词时为true",
                            },
                        },
                        "required": ["language"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_emotion_songs",
                    "description": "列出/播放所有特定情绪的歌曲。例如：'所有开心的歌'、'有哪些安静的歌'、'播放全部悲伤的歌'。当用户说'播放所有X的歌'时，play=true",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "emotion": {
                                "type": "string",
                                "description": "情绪名称",
                                # [可修改] 情绪列表 — 加新情绪在这里加，同时更新 emotion_names 字典
                                "enum": ["happy", "sad", "calm", "energetic", "romantic", "nostalgic", "angry", "focus", "party"],
                            },
                            "play": {
                                "type": "boolean",
                                "description": "用户是否要求直接播放（而非仅列出）。包含'播放'/'放'/'听'等动词时为true",
                            },
                        },
                        "required": ["emotion"],
                    },
                },
            },
            # === 播放 ===
            {
                "type": "function",
                "function": {
                    "name": "play_by_name",
                    "description": "按歌名播放特定歌曲。用户指定了具体歌名时使用。例如：'播放晴天'、'听稻香'。注意：'播放开心的歌'是情绪筛选，不是歌名",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "song_name": {"type": "string", "description": "歌曲名，保留用户原话"},
                        },
                        "required": ["song_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "play_by_artist",
                    "description": "播放某歌手的所有歌曲。例如：'播放周杰伦的歌'、'放陈奕迅的歌'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "artist": {"type": "string", "description": "歌手/艺术家名"},
                        },
                        "required": ["artist"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "play_all",
                    "description": "播放音乐库中全部歌曲。例如：'播放全部歌曲'、'播放所有歌'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "play_random",
                    "description": "随机播放指定数量的歌曲，可按情绪和语言筛选。例如：'随机播放五首悲伤的中文歌'、'随机播放十首开心的歌'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "count": {"type": "integer", "description": "播放数量"},
                            "emotion": {"type": "string", "description": "情绪英文名，如 happy/sad/calm/energetic/romantic/nostalgic"},
                            "language": {"type": "string", "description": "语言名，如国语/英语/粤语/日语/韩语"},
                        },
                        "required": ["count"],
                    },
                },
            },
            # === 歌单 ===
            {
                "type": "function",
                "function": {
                    "name": "playlist",
                    "description": "创建情绪/场景歌单。例如：'悲伤歌单'、'适合跑步听的歌'、'工作时听的'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mode": {"type": "string", "enum": ["emotion", "mood", "genre"], "description": "歌单模式"},
                            "emotion": {"type": "string", "description": "情绪关键词(emotion模式下)"},
                            "mood": {"type": "string", "description": "场景关键词(mood模式下)"},
                        },
                        "required": ["mode"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "smart_playlist",
                    "description": "用自然语言创建智能歌单。例如：'创建歌单 适合下雨的国语慢歌'、'来个跑步听的歌单'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "用户对歌单的自然语言描述"},
                            "name": {"type": "string", "description": "歌单名称(可选)"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_playlists",
                    "description": "查看已保存的智能歌单。例如：'查看歌单'、'我的歌单'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            # === 统计/分析 ===
            {
                "type": "function",
                "function": {
                    "name": "show_language_stats",
                    "description": "查看语言分布统计。例如：'有哪些语言'、'语言分布'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "show_library_stats",
                    "description": "查看音乐库整体统计。例如：'库里有几首歌'、'查看音乐库'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "analyze",
                    "description": "分析音乐库整体统计和构成。例如：'分析我的音乐库'、'统计一下'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            # === 元数据修改 ===
            {
                "type": "function",
                "function": {
                    "name": "correct_language",
                    "description": "纠正某首歌的语言标签。例如：'标记BTS为韩语'、'纠正XX的语言为日语'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input": {"type": "string", "description": "用户完整的纠正指令原文"},
                        },
                        "required": ["input"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "correct_emotion",
                    "description": "纠正某首歌的情绪标签。例如：'标记晴天为快乐的歌'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input": {"type": "string", "description": "用户完整的纠正指令原文"},
                        },
                        "required": ["input"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "update_song_info",
                    "description": "更新歌曲信息（陈述句形式）。例如：'Supernatural是韩语'、'Dynamite是快乐的歌'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "song_hint": {"type": "string", "description": "歌曲名或关键词"},
                            "field": {"type": "string", "enum": ["language", "emotion", "genre", "artist", "album"], "description": "要更新的字段"},
                            "value": {"type": "string", "description": "新值"},
                        },
                        "required": ["song_hint", "field", "value"],
                    },
                },
            },
            # === 修复/补全 ===
            {
                "type": "function",
                "function": {
                    "name": "fix_single",
                    "description": "修复某首特定歌曲的元数据（封面、歌手名等）。例如：'修复踊り子'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string", "description": "歌曲文件名或路径中的关键词"},
                        },
                        "required": ["file"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fix_metadata",
                    "description": "批量修复整个音乐库的元数据。例如：'修复元数据'、'补全封面'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            # === 检测/分析单曲 ===
            {
                "type": "function",
                "function": {
                    "name": "detect_single_language",
                    "description": "检测某首指定歌名的语言。例如：'检测Dynamite是什么语言'。必须有明确歌名",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "song_name": {"type": "string", "description": "要检测的歌曲名"},
                        },
                        "required": ["song_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "analyze_single_emotion",
                    "description": "分析某首指定歌名的情绪。例如：'分析晴天的情绪'。必须有明确歌名",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "song_name": {"type": "string", "description": "要分析的歌曲名"},
                        },
                        "required": ["song_name"],
                    },
                },
            },
            # === 维护/工具 ===
            {
                "type": "function",
                "function": {
                    "name": "scan",
                    "description": "扫描/更新音乐库。例如：'扫描音乐库'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "organize",
                    "description": "整理音乐文件。例如：'整理音乐'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "dedup",
                    "description": "清理重复歌曲。例如：'去重'、'清理重复'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "convert",
                    "description": "转换音频格式。例如：'转换wav到flac'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "download_lyrics",
                    "description": "下载歌词。例如：'下载歌词'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_lyrics_whisper",
                    "description": "AI识别歌词（必须指定歌名）。例如：'识别晴天歌词'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "song_name": {"type": "string", "description": "要识别歌词的歌曲名"},
                        },
                        "required": ["song_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "export_library",
                    "description": "导出音乐库为CSV。例如：'导出音乐库'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "import_library",
                    "description": "从CSV导入音乐库。例如：'导入音乐库'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            # === 诊断/修复（v2） ===
            {
                "type": "function",
                "function": {
                    "name": "diagnose",
                    "description": "诊断元数据完整性。例如：'诊断元数据'、'有哪些歌曲信息不全'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fix_metadata_issues",
                    "description": "一键修复元数据问题。例如：'一键修复'、'修复元数据问题'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sync_emotion",
                    "description": "同步情绪缓存到数据库。例如：'同步情绪缓存'",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    @staticmethod
    def get_tool_names() -> set:
        """返回所有已注册工具的名称集合，供白名单校验使用。"""
        return {t["function"]["name"] for t in ToolRegistry.get_tools()}
