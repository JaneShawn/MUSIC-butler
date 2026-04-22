# -*- coding: utf-8 -*-
"""
Music Agent Chat - 统一版对话式音乐助手
集成所有功能：扫描、查询、整理、修复、发现、周报、模型管理
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from pathlib import Path
from dotenv import load_dotenv

# 显式加载 .env 文件
current_dir = Path(__file__).parent
env_path = current_dir / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv()  # 尝试默认位置

import os
import yaml
import json
import re
import subprocess
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class NLPUtils:
    """NLP 工具类 - 处理中文文本的边界情况"""
    
    # 停用词/助词列表（只清理首尾，保留中间）
    STOP_WORDS = {
        '的', '了', '吗', '呢', '吧', '啊', '哦', '嗯', '呗', '嘛',
        '是', '有', '在', '和', '与', '或', '这', '那', '它', '个',
    }
    
    # 歌曲名后缀（需要移除的）—— 按长度降序排列，避免部分匹配
    # ❌ 严禁使用单字后缀（'歌'、'版'、'之'、'的'），会导致歌名被过度裁剪
    # 例："小情歌" → 若含'歌'后缀 → 变成"小情"
    SONG_SUFFIXES = [
        '这首歌的', '这首的', '这个的', '这首歌', '这首', '这个',
        '的歌曲', '的歌', '之歌', '版本', '版',
    ]
    
    # 艺术家名后缀
    ARTIST_SUFFIXES = [
        '唱的歌', '唱的', '的作品', '的歌', '的',
    ]
    
    # 统一情绪关键词映射（用于播放列表、情绪查询）
    EMOTION_KEYWORDS = {
        "快乐": "happy", "开心": "happy", "欢快": "happy", "高兴": "happy",
        "悲伤": "sad", "难过": "sad", "伤感": "sad", "抒情": "sad",
        "治愈": "calm", "安静": "calm", "平静": "calm", "放松": "calm", "舒缓": "calm", "轻松": "calm", "冥想": "calm",
        "燃": "energetic", "激情": "energetic", "热血": "energetic", "运动": "energetic", "嗨": "energetic",
        "浪漫": "romantic", "甜蜜": "romantic", "爱情": "romantic", "心动": "romantic",
        "怀旧": "nostalgic", "经典": "nostalgic", "回忆": "nostalgic", "老歌": "nostalgic",
        "愤怒": "angry", "发泄": "angry", "摇滚": "angry",
        "专注": "focus", "工作": "focus", "学习": "focus",
        "派对": "party", "聚会": "party", "舞曲": "party"
    }
    
    # 发现音乐场景的心情映射（网易云歌单 / 场景）
    MOOD_KEYWORDS = {
        "工作": "work", "办公": "work", "专注": "work",
        "学习": "study", "自习": "study",
        "运动": "workout", "健身": "workout", "跑步": "workout",
        "放松": "relax", "休息": "relax", "休闲": "relax",
        "睡觉": "sleep", "睡眠": "sleep", "助眠": "sleep",
        "派对": "party", "聚会": "party", "嗨": "party",
        "通勤": "commute", "路上": "commute", "开车": "commute"
    }
    
    @classmethod
    def clean_song_name(cls, text: str) -> str:
        """清理歌曲名中的助词和后缀（安全版本：避免过度清理）"""
        if not text:
            return text
        
        original = text.strip()
        if len(original) <= 2:
            return original  # 太短不清理，避免误删
        
        cleaned = original
        
        # 移除首尾停用词（保留至少2个字符）
        while cleaned and len(cleaned) > 2 and cleaned[0] in cls.STOP_WORDS:
            cleaned = cleaned[1:].strip()
        while cleaned and len(cleaned) > 2 and cleaned[-1] in cls.STOP_WORDS:
            cleaned = cleaned[:-1].strip()
        
        # 移除后缀（已按长度降序排列，保留至少2个字符）
        for suffix in cls.SONG_SUFFIXES:
            if cleaned.endswith(suffix) and len(cleaned) - len(suffix) >= 2:
                cleaned = cleaned[:-len(suffix)].strip()
                break  # 只移除第一个匹配的最长后缀
        
        # 再次清理首尾停用词（保留至少2个字符）
        while cleaned and len(cleaned) > 2 and cleaned[0] in cls.STOP_WORDS:
            cleaned = cleaned[1:].strip()
        while cleaned and len(cleaned) > 2 and cleaned[-1] in cls.STOP_WORDS:
            cleaned = cleaned[:-1].strip()
        
        # 安全兜底：清理后的结果不得少于原字符串的50%或2个字
        if len(cleaned) < 2 or len(cleaned) < len(original) * 0.3:
            return original
        
        return cleaned
    
    @classmethod
    def clean_artist_name(cls, text: str) -> str:
        """清理艺术家名中的后缀"""
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
        """标准化用户输入"""
        if not text:
            return text
        
        # 去除多余空格
        text = ' '.join(text.split())
        
        # 中英文标点统一
        text = text.replace('，', ',').replace('。', '.').replace('？', '?').replace('！', '!')
        
        # 去除首尾标点
        text = text.strip('.,!?;:，。！？；：')
        
        return text.strip()

from core.kimi_client import KimiClient
from core.vector_store import EMBEDDING_MODELS
from core.audio_converter import AudioConverter, preview_conversion
from agents import LibrarianAgent, ScoutAgent, CuratorAgent, OrganizerAgent, OrganizeStrategy


class SessionState(Enum):
    """会话状态"""
    IDLE = "idle"
    AWAITING_CONFIRM = "awaiting_confirm"
    AWAITING_PARAMS = "awaiting_params"
    IN_QUERY = "in_query"


@dataclass
class PendingAction:
    """待执行的操作"""
    action_type: str
    params: Dict[str, Any]
    description: str
    requires_confirm: bool = True


@dataclass
class Message:
    """单条消息"""
    role: str
    content: str
    timestamp: str
    intent: Optional[Dict] = None


class ContextManager:
    """上下文管理器"""
    
    def __init__(self, max_history: int = 30, session_file: Optional[Path] = None):
        self.max_history = max_history
        self.session_file = session_file or Path("chat_session.json")
        self.messages: List[Message] = []
        self.state = SessionState.IDLE
        self.pending_action: Optional[PendingAction] = None
        self.last_query_results: List[Dict] = []
        self.session_metadata = {
            "start_time": datetime.now().isoformat(),
            "total_messages": 0,
            "commands_executed": 0
        }
        self._load_session()
    
    def add_message(self, role: str, content: str, intent: Dict = None):
        msg = Message(
            role=role, content=content,
            timestamp=datetime.now().isoformat(),
            intent=intent
        )
        self.messages.append(msg)
        self.session_metadata["total_messages"] += 1
        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history:]
    
    def get_recent(self, n: int = 5) -> List[Message]:
        return self.messages[-n:] if self.messages else []
    
    def get_context_text(self, max_msgs: int = 6) -> str:
        recent = self.get_recent(max_msgs)
        lines = []
        for m in recent:
            prefix = "用户" if m.role == "user" else "助手"
            content = m.content[:100] + "..." if len(m.content) > 100 else m.content
            lines.append(f"{prefix}: {content}")
        return "\n".join(lines)
    
    def resolve_reference(self, text: str) -> Optional[Dict]:
        """解析指代（如'第一首'、'播放第一首'）"""
        if not self.last_query_results:
            return None
        
        num_match = re.search(r'第?(\d+)', text)
        if num_match:
            idx = int(num_match.group(1)) - 1
            if 0 <= idx < len(self.last_query_results):
                return self.last_query_results[idx]
        
        if any(w in text for w in ['第一', '首个']):
            return self.last_query_results[0]
        elif any(w in text for w in ['最后', '末尾']):
            return self.last_query_results[-1] if self.last_query_results else None
        elif any(w in text for w in ['这首', '它', '这个']):
            return self.last_query_results[0] if self.last_query_results else None
        
        return None
    
    def set_pending(self, action: PendingAction):
        self.pending_action = action
        self.state = SessionState.AWAITING_CONFIRM if action.requires_confirm else SessionState.IDLE
    
    def clear_pending(self):
        self.pending_action = None
        self.state = SessionState.IDLE
    
    def set_query_results(self, results: List[Dict]):
        self.last_query_results = results
        self.state = SessionState.IN_QUERY if results else SessionState.IDLE
    
    def _load_session(self):
        if self.session_file.exists():
            try:
                with open(self.session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.messages = [Message(**m) for m in data.get('messages', [])]
                    # 恢复 pending action
                    pending_data = data.get('pending_action')
                    if pending_data:
                        self.pending_action = PendingAction(**pending_data)
                        print(f"[系统] 已恢复会话（{len(self.messages)} 条消息），有待确认操作: {self.pending_action.description}")
                    else:
                        print(f"[系统] 已恢复会话（{len(self.messages)} 条消息）")
            except Exception as e:
                print(f"[系统] 加载会话失败: {e}")
    
    def save_session(self):
        try:
            data = {
                'messages': [asdict(m) for m in self.messages],
                'metadata': self.session_metadata,
                'pending_action': asdict(self.pending_action) if self.pending_action else None
            }
            with open(self.session_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[系统] 保存会话失败: {e}")
    
    def clear(self):
        self.messages = []
        self.pending_action = None
        self.last_query_results = []
        self.state = SessionState.IDLE
        if self.session_file.exists():
            self.session_file.unlink()


class MusicAgentChat:
    """统一版对话式音乐助手"""
    
    def __init__(self):
        print("初始化中...")
        
        script_dir = Path(__file__).parent.resolve()
        config_path = script_dir / "config.yaml"
        
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.context = ContextManager(session_file=script_dir / "chat_session.json")
        
        try:
            self.kimi = KimiClient()
            print("✓ Kimi API 已连接")
        except Exception as e:
            self.kimi = None
            print(f"✗ Kimi API 不可用: {e}")
            print("  提示: 在 .env 文件中设置 KIMI_API_KEY=your_api_key")
        
        self._librarian = None
        self._organizer = None
        self._scout = None
        self._curator = None
        
        # LLM 意图识别缓存（减少重复 API 调用）
        # 缓存版本：修改 prompt 后递增，使旧缓存自动失效
        self._INTENT_CACHE_VERSION = 4
        self._intent_cache: Dict[str, Dict[str, Any]] = {}
        
        # 支持的所有意图白名单（用于验证 LLM 返回）
        self._VALID_INTENTS = {
            "query", "play_by_name", "playlist", "playlist_from_results",
            "batch_select", "show_language_stats", "scan", "analyze", "organize",
            "show_library_stats", "recommend_random", "correct_language",
            "update_song_info", "analyze_emotion", "analyze_single_emotion",
            "detect_single_language", "detect_language_by_audio",
            "generate_lyrics_whisper", "download_lyrics",
            "export_library", "export_language_csv", "import_library",
            "help", "exit", "cancel", "chat", "play", "info", "fix_single"
        }
    
    @property
    def librarian(self):
        if self._librarian is None:
            self._librarian = LibrarianAgent(self.config)
        return self._librarian
    
    @property
    def organizer(self):
        if self._organizer is None:
            self._organizer = OrganizerAgent(self.config, self.librarian)
        return self._organizer
    
    @property
    def scout(self):
        if self._scout is None:
            self._scout = ScoutAgent(self.config)
        return self._scout
    
    @property
    def curator(self):
        if self._curator is None:
            self._curator = CuratorAgent(self.config, self.librarian)
        return self._curator
    
    def understand_intent(self, user_input: str) -> Dict[str, Any]:
        """理解用户意图
        
        采用 LLM 优先的混合策略：
        1. 简单明确的场景（确认/取消/退出/纯数字选择）走硬编码规则，零延迟
        2. 其他所有自然语言输入走 LLM 语义理解，覆盖无限变体
        3. LLM 不可用时 fallback 到硬编码规则
        """
        user_input_lower = user_input.lower()
        
        # === 1. 高优先级硬编码规则（零延迟，无歧义）===
        
        # 待确认的操作
        if self.context.pending_action:
            confirm_words = ['确认', '确定', '是的', '执行', 'ok', 'yes', 'y']
            cancel_words = ['取消', '算了', 'no', 'n']
            
            if any(w in user_input for w in confirm_words):
                return {
                    "intent": self.context.pending_action.action_type,
                    "params": {**self.context.pending_action.params, "from_pending": True}
                }
            elif any(w in user_input for w in cancel_words):
                self.context.clear_pending()
                return {"intent": "cancel"}
        
        # 纯数字且在查询上下文中 = 播放/选择这首歌
        if user_input.strip().isdigit() and self.context.last_query_results:
            idx = int(user_input.strip()) - 1
            if 0 <= idx < len(self.context.last_query_results):
                if self.context.pending_action and self.context.pending_action.action_type == "fix_single":
                    return {
                        "intent": "fix_single", 
                        "params": {
                            "from_query": True, 
                            "force": True,
                            "selected_idx": idx
                        }
                    }
                return {
                    "intent": "play",
                    "params": {"item": self.context.last_query_results[idx]}
                }
        
        # 多选模式：在查询上下文中选择多首歌曲
        # 支持 "1+2"、"1 2 3"、"1,2,3"、"1-3"、"第一首和第二首"、"前两首"、"全部"
        if self.context.last_query_results:
            multi_indices = self._parse_multi_select(user_input, len(self.context.last_query_results))
            if multi_indices is not None and len(multi_indices) > 0:
                return {
                    "intent": "batch_select",
                    "params": {"indices": multi_indices}
                }
        
        # 批量情绪分析（高优先级拦截，避免 LLM 把"分析情绪"误判为 analyze_single_emotion）
        if any(p in user_input for p in ["分析情绪", "情绪分析", "情绪识别"]):
            # 排除 "分析XXX的情绪" 这种明确指定歌名的情况
            import re
            if not re.search(r'分析.+?的.?情绪', user_input):
                force = any(w in user_input for w in ["重新", "强制", "刷新", "更新"])
                return {"intent": "analyze_emotion", "params": {"force": force}}
        
        # === 2. LLM 语义意图识别（覆盖自然语言无限变体）===
        llm_intent = self._llm_understand_intent(user_input)
        if llm_intent:
            return llm_intent
        
        # === 3. Fallback: 硬编码规则（LLM 不可用时兜底）===
        return self._base_intent(user_input)
    
    def _parse_multi_select(self, user_input: str, total_count: int) -> Optional[List[int]]:
        """解析多选索引，支持多种语法
        
        返回选中的0-based索引列表，如果不是多选语法则返回None
        """
        import re
        text = user_input.strip().lower()
        
        # 1. "全部" / "所有" / "都"
        if text in ["全部", "所有", "都", "all"]:
            return list(range(total_count))
        
        # 2. 数字范围 "1-3" / "1到3" / "1~3"
        range_match = re.match(r'^(\d+)[\-~到](\d+)$', text)
        if range_match:
            start = int(range_match.group(1)) - 1
            end = int(range_match.group(2))
            if 0 <= start < end <= total_count:
                return list(range(start, end))
        
        # 3. 加号连接 "1+2" / "1+2+3"
        if '+' in text:
            indices = []
            for part in text.split('+'):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < total_count:
                        indices.append(idx)
            if len(indices) > 1:
                return indices
        
        # 4. 空格或逗号分隔 "1 2 3" / "1,2,3"
        if re.match(r'^[\d\s,、]+$', text):
            indices = []
            for part in re.split(r'[\s,、]+', text):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < total_count:
                        indices.append(idx)
            if len(indices) > 1:
                return indices
        
        # 5. 中文序数 "前两首" / "前3首" / "第一首和第二首"
        if '首' in text or '个' in text:
            # "前两首" / "前3首"
            prefix_match = re.search(r'前(\d+)[首个]', text)
            if prefix_match:
                count = int(prefix_match.group(1))
                if 1 <= count <= total_count:
                    return list(range(count))
            
            # "第一首和第二首" / "第一首、第二首"
            chinese_nums = {
                '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
                '1': 1, '2': 2, '3': 3, '4': 4, '5': 5,
                '6': 6, '7': 7, '8': 8, '9': 9, '10': 10
            }
            indices = []
            # 匹配 "第X首" 或 "第X个"
            for match in re.finditer(r'第([一二三四五六七八九十\d]+)[首个]', text):
                num_str = match.group(1)
                idx = chinese_nums.get(num_str, int(num_str) if num_str.isdigit() else None)
                if idx is not None:
                    idx = idx - 1
                    if 0 <= idx < total_count:
                        indices.append(idx)
            if len(indices) > 1:
                return indices
        
        return None
    
    def _llm_understand_intent(self, user_input: str) -> Optional[Dict[str, Any]]:
        """使用 LLM 理解用户意图，返回结构化结果
        
        采用 Few-shot + 对话历史 + 缓存的混合策略，最大化准确率并减少 API 调用。
        """
        if not self.kimi:
            return None
        
        # 1. 检查缓存（带版本控制，prompt 修改后旧缓存自动失效）
        cache_key = user_input.strip().lower()
        if cache_key in self._intent_cache:
            cached = self._intent_cache[cache_key]
            if cached.get("_cache_version") == self._INTENT_CACHE_VERSION:
                print(f"  [LLM意图识别] '{user_input}' → {cached['intent']} (缓存)")
                return {k: v for k, v in cached.items() if not k.startswith("_")}
        
        # 2. 获取对话历史上下文（帮助 LLM 理解指代和上下文）
        recent_messages = self.context.get_recent(4)
        dialog_history = ""
        if len(recent_messages) >= 2:
            lines = []
            for m in recent_messages[:-1]:  # 排除当前这条（还没加入context）
                prefix = "用户" if m.role == "user" else "助手"
                content = m.content[:80] + "..." if len(m.content) > 80 else m.content
                lines.append(f"{prefix}: {content}")
            if lines:
                dialog_history = "\n最近对话：\n" + "\n".join(lines)
        
        if self.context.last_query_results:
            dialog_history += f"\n用户上次查询了 {len(self.context.last_query_results)} 首歌。"
        
        # 3. 构造带 Few-shot 示例的 system prompt
        system_prompt = """你是一个音乐管理助手的意图识别模块。请分析用户输入，判断其意图。

【核心区分原则】
1. 用户想"找歌/列举歌" → query（无论说的是语言、情绪、歌手还是年代）
2. 用户想看"数字统计"（不问具体是哪首）→ show_language_stats / analyze
3. 用户指定了具体歌名，想"知道这首歌的属性" → detect_single_language / analyze_single_emotion
4. 用户想"修改/纠正"某首歌的属性 → correct_language / update_song_info

【Few-shot 示例】
用户："周杰伦的歌" → {"intent": "query", "params": {"query": "周杰伦的歌"}}
用户："播放晴天" → {"intent": "play_by_name", "params": {"song_name": "晴天"}}
用户："播放周杰伦的歌" → {"intent": "query", "params": {"query": "周杰伦的歌"}}
用户："播放开心的歌" → {"intent": "playlist", "params": {"mode": "emotion", "emotion": "happy"}}
用户："有哪些开心的歌曲" → {"intent": "query", "params": {"query": "开心的歌"}}
用户："有哪些语言" → {"intent": "show_language_stats", "params": {}}
用户："西班牙语歌有哪些" → {"intent": "query", "params": {"query": "西班牙语歌"}}
用户："哪首是西班牙语" → {"intent": "query", "params": {"query": "西班牙语歌"}}
用户："标记BTS为韩语" → {"intent": "correct_language", "params": {"input": "标记BTS为韩语"}}
用户："Supernatural是韩语" → {"intent": "update_song_info", "params": {"song_hint": "Supernatural", "field": "language", "value": "韩语"}}
用户："检测Dynamite是什么语言" → {"intent": "detect_single_language", "params": {"song_name": "Dynamite"}}
用户："分析情绪" → {"intent": "analyze_emotion", "params": {}}
用户："悲伤歌单" → {"intent": "playlist", "params": {"mode": "emotion", "emotion": "sad"}}
用户："扫描音乐库" → {"intent": "scan", "params": {}}
用户："分析我的音乐库" → {"intent": "analyze", "params": {}}
用户："修复踊り子" → {"intent": "fix_single", "params": {"file": "踊り子"}}
用户："修复元数据" → {"intent": "fix_metadata", "params": {}}
用户："退出" → {"intent": "exit", "params": {}}
用户："你好" → {"intent": "chat", "params": {"type": "greeting"}}

支持的意图类型：

=== 搜索/查询类（最常用）===
- query: 用户想搜索、查找、列举歌曲（任何"找歌"需求）
  ✓ "周杰伦的歌"、"悲伤的歌"、"韩语歌"、"90年代摇滚"
  ✓ "哪首是西班牙语"、"西班牙语歌有哪些"、"给我找几首日语歌"
  ✓ "推荐一些安静的歌"、"有没有快乐的歌"
  params: {"query": "用户的搜索意图文本"}

- play_by_name: 按名字播放特定歌曲（必须是具体歌名，不是情绪/场景/歌手描述）
  ✓ "播放晴天"、"听Faded"、"放一首稻香"
  ✗ "播放开心的歌" → playlist（开心是情绪，不是歌名）
  ✗ "播放周杰伦的歌" → query（用户没指定具体歌名）

- playlist: 创建情绪/场景播放列表
  ✓ "悲伤歌单"、"适合跑步的歌"、"工作时听的"

=== 统计/分析类 ===
- show_language_stats: 只看语言数字统计，不问具体是哪首歌
  ✓ "有哪些语言"、"语言分布"、"各种语言各占多少"
  ✗ "西班牙语歌有哪些" → 这是 query（用户想看具体歌名）
  ✗ "哪首是西班牙语" → 这是 query（用户想找具体歌）

- analyze: 分析音乐库整体统计
  ✓ "分析我的音乐库"、"统计一下"、"库里有啥"

- show_library_stats: 查看音乐库统计
  ✓ "查看音乐库"、"库统计"

=== 修改/纠正类（必须包含"标记/纠正/设置/是"等修改动词）===
- correct_language: 纠正某首歌的语言标签
  ✓ "标记BTS为韩语"、"纠正XX的语言为日语"
  ✗ "BTS是韩语" → 这是 update_song_info（陈述句，不是纠正命令）

- update_song_info: 更新歌曲信息（陈述句形式）
  ✓ "Supernatural是韩语"、"Dynamite是快乐的歌"
  ✗ "修复踊り子" → 这是 fix_single（"修复"是修复元数据，不是更新信息）

=== 修复/补全类 ===
- fix_single: 修复某首特定歌曲的元数据（封面、歌手名、歌名、专辑、年份等）
  ✓ "修复踊り子"、"补全这首歌的信息"、"修复这首歌的封面"
  ✗ "Supernatural是韩语" → 这是 update_song_info（不是修复）

- fix_metadata: 批量修复整个音乐库的元数据
  ✓ "修复元数据"、"补全封面"、"修复所有歌曲信息"

=== 检测/分析单曲类（必须明确指定歌名）===
- detect_single_language: 检测某首已知歌名的语言
  ✓ "检测BTS的Dynamite是什么语言"
  ✗ "哪首是西班牙语" → 这是 query（用户没指定歌名，是在找歌）

- analyze_single_emotion: 分析某首已知歌名的情绪（必须用户明确说了歌名，只说"分析情绪"没有歌名 → analyze）
  ✓ "分析晴天的情绪"
  ✗ "分析情绪" → analyze（用户没指定歌名）

=== 其他 ===
- scan: 扫描/更新音乐库
- organize: 整理音乐文件
- recommend_random: 随机推荐
- analyze_emotion: 批量分析情绪
- detect_language_by_audio: 音频检测语言
- generate_lyrics_whisper: AI识别歌词
- download_lyrics: 下载歌词
- export_library: 导出音乐库
- export_language_csv: 导出语言文档
- help: 帮助
- exit: 退出
- chat: 普通闲聊

【绝对规则】
1. "哪首是XX" = query（用户在找歌，不是检测单曲）
2. "XX歌有哪些" = query（用户想看具体歌名列表，不是统计数字）
3. "标记/纠正XX为YY" = correct_language
4. "XX是YY"（没有标记/纠正/修复动词）= update_song_info
5. "修复XX" = fix_single（修复元数据，不是更新属性）
6. play_by_name 的 song_name 必须原样保留用户输入的歌名，不要自动添加歌手名，不要加书名号《》，不要根据对话历史修改字词（用户说"程艾影"就返回"程艾影"，不是"程爱影"）
7. analyze_single_emotion / detect_single_language 必须用户明确说了具体歌名。只说"分析情绪"没有歌名 → analyze_emotion（批量分析）
8. 只返回JSON，不要任何解释文字"""

        user_prompt = f"""{dialog_history}

用户输入："{user_input}"

请只返回JSON：{{"intent": "意图名", "params": {{...}}}}"""
        
        try:
            response = self.kimi.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.05,  # 极低温度，最大化确定性
                max_tokens=200
            )
            
            # 提取 JSON
            import json
            content = response.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()
            
            result = json.loads(content)
            
            # 验证必要字段
            if "intent" not in result or not isinstance(result["intent"], str):
                print(f"  [LLM意图识别] 返回格式无效: {content[:100]}")
                return None
            
            intent_name = result["intent"]
            params = result.get("params", {})
            
            # 白名单验证：防止 LLM 返回不存在的 intent
            if intent_name not in self._VALID_INTENTS:
                print(f"  [LLM意图识别] 返回未知意图 '{intent_name}'，fallback 到 chat")
                intent_name = "chat"
                params = {"type": "general"}
            
            # 对于 show_language_stats 但用户具体问了某种语言，转为 query
            if intent_name == "show_language_stats" and params.get("language"):
                intent_name = "query"
                params = {"query": user_input}
            
            result_dict = {"intent": intent_name, "params": params}
            
            # 写入缓存（只缓存非闲聊意图，闲聊变化太多不缓存）
            if intent_name != "chat":
                self._intent_cache[cache_key] = {
                    "_cache_version": self._INTENT_CACHE_VERSION,
                    **result_dict
                }
            
            print(f"  [LLM意图识别] '{user_input}' → {intent_name}")
            return result_dict
                
        except json.JSONDecodeError as e:
            print(f"  [LLM意图识别] JSON解析失败: {e}, 原始响应: {response[:100]}")
        except Exception as e:
            print(f"  [LLM意图识别] 失败: {e}")
        
        return None
    
    def _check_context(self, user_input: str) -> Optional[Dict]:
        """检查上下文中的隐含意图"""
        recent = self.context.get_recent(2)
        if not recent:
            return None
        
        last = recent[-1]
        if not last.intent:
            return None
        
        last_type = last.intent.get('intent')
        
        # 整理后指定策略
        if last_type == 'organize':
            if any(w in user_input for w in ['按流派', '流派']):
                return {"intent": "organize", "params": {"strategy": "genre"}}
            elif any(w in user_input for w in ['按年代', '年代']):
                return {"intent": "organize", "params": {"strategy": "year"}}
            elif any(w in user_input for w in ['平铺', '合并']):
                return {"intent": "organize", "params": {"strategy": "flat"}}
        
        # 查询后细化
        if last_type == 'query':
            if any(w in user_input for w in ['粤语', '广东话']):
                return {"intent": "query", "params": {"query": "粤语歌"}}
            elif any(w in user_input for w in ['国语', '普通话']):
                return {"intent": "query", "params": {"query": "国语歌"}}
            elif any(w in user_input for w in ['英文', '英语']):
                return {"intent": "query", "params": {"query": "英文歌"}}
        
        return None
    
    def _base_intent(self, user_input: str) -> Dict[str, Any]:
        """基础意图识别"""
        user_input_lower = user_input.lower()
        
        # 退出
        if any(w in user_input_lower for w in ["exit", "quit", "退出", "再见"]):
            return {"intent": "exit"}
        
        # 扫描
        if any(w in user_input_lower for w in ["扫描", "scan", "更新"]):
            return {"intent": "scan"}
        
        # 下载歌词文件（优先于分析情绪）
        if any(w in user_input for w in ["生成歌词", "导出歌词", "下载歌词文件"]):
            return {"intent": "download_lyrics"}
        
        # AI识别/提取歌词（使用Whisper）
        # 支持"识别XX歌词"、"提取XX歌词"等变体
        has_recognize = any(w in user_input for w in ["识别", "提取", "听写"])
        has_lyrics = any(w in user_input for w in ["歌词", "lyrics"])
        has_ai = any(w in user_input for w in ["AI", "Whisper", "whisper", "智能"])
        
        if (has_recognize and has_lyrics) or has_ai:
            # 尝试提取歌曲名（识别/提取 + 歌名 + 歌词）
            song_name = None
            for keyword in ["识别", "提取", "听写"]:
                if keyword in user_input:
                    # 提取关键词后面的内容，直到"歌词"
                    parts = user_input.split(keyword, 1)
                    if len(parts) > 1:
                        song_part = parts[1].strip()
                        # 使用NLP工具清理歌曲名
                        song_part = NLPUtils.clean_song_name(song_part)
                        # 额外移除歌词相关后缀
                        for suffix in ["歌词", "lyrics"]:
                            if song_part.endswith(suffix):
                                song_part = song_part[:-len(suffix)].strip()
                        if song_part:
                            song_name = song_part
                            break
            
            return {"intent": "generate_lyrics_whisper", "params": {"song_name": song_name}}
        
        # 询问特定歌曲的情绪（优先于批量分析）
        # 模式1: "XXX是什么情绪"、"XXX这首歌什么情绪"
        # 模式2: "分析XXX情绪"、"分析XXX的歌词情绪"
        # 模式3: "分析XXX"（但排除"分析歌词/歌曲/情绪"等批量关键词）
        song_emotion_patterns = [
            r"(.+?)(这首歌|这首|这个)?是什么情绪",
            r"(.+?)(这首歌|这首|这个)?的情绪是什么",
            r"分析(.+?)情绪",
            r"分析(.+?)的歌词",
        ]
        
        # 特殊处理："分析XXX" 但排除批量分析关键词
        batch_keywords = ["歌词", "歌曲", "情绪", "音乐库", "库"]
        if user_input.startswith("分析"):
            potential_song = user_input[2:].strip()
            # 使用NLP工具清理歌曲名
            potential_song = NLPUtils.clean_song_name(potential_song)
            if potential_song and not any(kw in potential_song for kw in batch_keywords):
                return {"intent": "analyze_single_emotion", "params": {"song_name": potential_song}}
        for pattern in song_emotion_patterns:
            import re
            match = re.search(pattern, user_input)
            if match:
                song_name = match.group(1).strip()
                # 使用NLP工具清理歌曲名
                song_name = NLPUtils.clean_song_name(song_name)
                if song_name and len(song_name) > 1:
                    return {"intent": "analyze_single_emotion", "params": {"song_name": song_name}}
        
        # 随机推荐歌曲并说明理由
        recommend_patterns = [
            r"随机推荐(\d+)首",
            r"推荐(\d+)首歌",
            r"给我推荐(\d+)首",
        ]
        for pattern in recommend_patterns:
            import re
            match = re.search(pattern, user_input)
            if match:
                count = int(match.group(1))
                return {"intent": "recommend_random", "params": {"count": min(count, 20)}}
        
        # 简化版：随机推荐（不指定数量，默认5首）
        if any(phrase in user_input for phrase in ["随机推荐", "推荐几首歌", "给我推荐"]):
            return {"intent": "recommend_random", "params": {"count": 5}}
        
        # 分析歌词（批量分析音乐库）
        if any(w in user_input for w in ["分析歌词", "分析歌曲", "歌词分析"]):
            return {"intent": "analyze_emotion"}
        
        # 分析音乐库情绪（批量）
        if any(w in user_input for w in ["分析情绪", "情绪分析", "情绪识别", "获取歌词"]):
            # 检查是否强制重新分析
            force = any(w in user_input for w in ["重新", "强制", "刷新", "更新"])
            return {"intent": "analyze_emotion", "params": {"force": force}}
        
        # 分析音乐库情绪（必须在通用"分析"之前）
        if any(w in user_input for w in ["分析情绪", "情绪分析", "分析所有歌", "分析全部", "分析歌词", "分析歌曲"]):
            # 检查是否强制重新分析
            force = any(w in user_input for w in ["重新", "强制", "刷新", "更新"])
            return {"intent": "analyze_emotion", "params": {"force": force}}
        
        # 查看语言统计（覆盖各种自然表达）
        language_stats_phrases = [
            "语言统计", "查看语言", "歌曲语言分布", "语言分布",
            "有啥语言", "有什么语言", "语言种类", "查看歌曲语言",
            "语言有哪些", "哪些语言", "歌都是什么语言"
        ]
        if any(phrase in user_input for phrase in language_stats_phrases):
            return {"intent": "show_language_stats"}
        
        # 音频检测语言（只用Whisper，不走文本检测）
        if any(phrase in user_input for phrase in ["音频检测语言", "听歌识语言", "分析音频语言", "用音频检测"]):
            return {"intent": "detect_language_by_audio"}
        
        # 单曲语言检测（排除统计/列举类查询）
        if user_input.startswith(("检测", "识别", "查看")) and "语言" in user_input:
            # 排除明显是统计/分布查询的表达
            stats_keywords = ["统计", "分布", "所有", "全部", "有哪些", "有啥", "种类"]
            if any(kw in user_input for kw in stats_keywords):
                pass  # 不走单曲检测，让后面的逻辑处理
            else:
                # 提取歌曲名，如 "检测BTS语言"、"识别Dynamite语言"
                for keyword in ["检测", "识别", "查看"]:
                    if user_input.startswith(keyword):
                        song_name = user_input[len(keyword):].replace("语言", "").strip()
                        # 排除通用词（不可能是歌曲名）
                        if song_name and song_name not in ["歌曲", "歌", "音乐", "库", "列表"]:
                            return {"intent": "detect_single_language", "params": {"song_name": song_name}}
        
        # 导出完整音乐库文档
        if any(phrase in user_input for phrase in ["导出文档", "生成文档", "导出音乐库", "生成表格", "导出Excel", "导出CSV"]):
            return {"intent": "export_library"}
        
        # 导入音乐库文档
        if any(phrase in user_input for phrase in ["导入文档", "导入音乐库", "更新文档", "加载表格"]):
            return {"intent": "import_library"}
        
        # 查看音乐库统计
        if any(phrase in user_input for phrase in ["音乐库统计", "查看音乐库", "库统计", "查看所有"]):
            return {"intent": "show_library_stats"}
        
        # 导出语言文档（兼容旧版）
        if any(phrase in user_input for phrase in ["导出语言", "生成语言文档"]):
            return {"intent": "export_language_csv"}
        
        # 纠正语言（旧格式：标记 歌手 - 歌名 为 韩语）
        if user_input.startswith(("标记", "纠正", "设置语言")):
            return {"intent": "correct_language", "params": {"input": user_input}}
        
        # 自然语言修改歌曲信息（如"supernatural是韩语歌"、"Dynamite是快乐的歌"）
        # 匹配：歌曲名 + 是/为/改成 + 属性 + 歌
        info_update_patterns = [
            # 语言："supernatural是韩语歌"、"Dynamite是日语"
            (r"(.+?)(?:是|为|改成)\s*(韩语|日语|英语|国语|粤语|中文|英文|韩文|日文)\s*歌?", "language"),
            # 情绪："supernatural是快乐的歌"、"Dynamite是悲伤的歌"
            (r"(.+?)(?:是|为|改成)\s*(快乐|开心|悲伤|治愈|安静|抒情|热血|激情|燃|平静|放松|舒缓|浪漫|甜蜜|怀旧|经典|愤怒|发泄|专注|工作|派对|舞曲)\s*的?歌?", "emotion"),
        ]
        
        for pattern, field_type in info_update_patterns:
            match = re.search(pattern, user_input)
            if match:
                song_hint = match.group(1).strip()
                value = match.group(2).strip()
                return {
                    "intent": "update_song_info",
                    "params": {
                        "song_hint": song_hint,
                        "field": field_type,
                        "value": value
                    }
                }
        
        # 通用分析（统计音乐库）
        if any(w in user_input_lower for w in ["分析", "统计", "查看"]):
            return {"intent": "analyze"}
        
        # 整理
        if any(w in user_input for w in ["整理", "分类", "移动", "归类", "平铺", "合并"]):
            strategy = "artist/album"
            if "平铺" in user_input or "合并" in user_input:
                strategy = "flat"
            elif "流派" in user_input:
                strategy = "genre"
            elif "年代" in user_input:
                strategy = "year"
            
            return {
                "intent": "organize",
                "params": {"strategy": strategy, "confirm": "确认" in user_input},
                "needs_confirm": "确认" not in user_input
            }
        
        # 去重
        if any(w in user_input for w in ["重复", "duplicate", "dup", "去重", "清理重复"]):
            return {
                "intent": "dedup",
                "params": {"confirm": "确认" in user_input or "执行" in user_input},
                "needs_confirm": "确认" not in user_input and "执行" not in user_input
            }
        
        # 查询（排除明确的推荐请求）
        is_recommendation_request = any(w in user_input for w in ["给我推荐", "推荐歌曲", "推荐音乐", "根据我的库"])
        if any(w in user_input for w in ["查询", "搜索", "找", "有哪些"]) or \
           ("推荐" in user_input and not is_recommendation_request):
            return {"intent": "query", "params": {"query": user_input}}
        
        # 播放列表创建（优先级高于发现音乐，因为"工作歌单"可能冲突）
        has_playlist_keyword = any(w in user_input for w in ["播放列表", "歌单", "playlist", "m3u8"])
        has_create_keyword = any(w in user_input for w in ["创建", "生成", "新建", "整理"])
        has_list_keyword = any(w in user_input for w in ["列表", "歌单"])
        
        if has_playlist_keyword or (has_create_keyword and has_list_keyword):
            params = {"mode": "shuffle"}
            
            # 检测情绪关键词
            detected_emotion = None
            for keyword, emotion in NLPUtils.EMOTION_KEYWORDS.items():
                if keyword in user_input:
                    detected_emotion = emotion
                    break
            
            if detected_emotion:
                params["mode"] = "emotion"
                params["emotion"] = detected_emotion
            elif any(w in user_input for w in ["随机", "打乱", "shuffle"]):
                params["mode"] = "shuffle"
            elif any(w in user_input for w in ["智能", "适合"]):
                params["mode"] = "smart"
                for kw in ["创建", "生成", "一个", "歌单", "播放列表"]:
                    user_input = user_input.replace(kw, "")
                params["query"] = user_input.strip()
            
            import re
            duration_match = re.search(r'(\d+)\s*分钟', user_input)
            if duration_match:
                params["max_duration"] = int(duration_match.group(1))
            
            count_match = re.search(r'(\d+)\s*首', user_input)
            if count_match:
                params["max_songs"] = int(count_match.group(1))
            
            return {"intent": "playlist", "params": params}
        
        # 发现新音乐（多种模式）
        is_discover_request = any(w in user_input for w in ["发现", "discover", "新音乐", "新歌", "每周", "周报", "报告"])
        
        mood_keywords = NLPUtils.MOOD_KEYWORDS
        has_mood_keyword = any(kw in user_input for kw in mood_keywords.keys())
        has_music_keyword = any(w in user_input for w in ["歌", "音乐", "听"])  # 排除"歌单"，已在上面处理
        
        explore_keywords = ["小众", "冷门", "独立", "hidden", "indie", "宝藏"]
        has_explore_keyword = any(w in user_input for w in explore_keywords)
        
        has_new_release = any(w in user_input for w in ["新专辑", "新作", "新发行", "最新"])
        
        has_library_recommend = any(w in user_input for w in ["根据我的库", "基于我的", "给我推荐", "推荐歌", "推荐音乐"])
        
        if is_discover_request or (has_mood_keyword and has_music_keyword) or has_explore_keyword or has_new_release or has_library_recommend:
            # 检查是否是特定发现模式
            if any(w in user_input for w in ["相似", "类似", "像"]):
                # 提取艺术家名
                for keyword in ["像", "相似", "类似"]:
                    if keyword in user_input:
                        artist = user_input.split(keyword)[-1].strip()
                        if artist:
                            return {"intent": "discover", "params": {"mode": "similar_artist", "artist": artist}}
            
            # 心情/场景发现
            for keyword, mood in mood_keywords.items():
                if keyword in user_input:
                    return {"intent": "discover", "params": {"mode": "mood", "mood": mood}}
            
            # 追踪特定艺术家新发行
            if any(w in user_input for w in ["最新", "新专辑", "新发行", "新作"]):
                for keyword in ["最新", "新专辑", "新发行", "新作"]:
                    if keyword in user_input:
                        # 尝试提取艺术家名（关键词前面的内容）
                        parts = user_input.split(keyword)
                        if len(parts) > 1 and parts[0].strip():
                            artist = parts[0].strip()
                            return {"intent": "discover", "params": {"mode": "artist_new", "artist": artist}}
            
            # 探索小众音乐
            if any(w in user_input for w in ["小众", "冷门", "独立", "探索", "发掘", "hidden", "indie"]):
                return {"intent": "discover", "params": {"mode": "explore"}}
            
            # 基于库的推荐（个性化）
            if any(w in user_input for w in ["根据我的库", "基于我的", "给我推荐", "推荐歌", "推荐音乐"]) and \
               not any(w in user_input for w in ["修复", "标签", "元数据"]):
                return {"intent": "discover", "params": {"mode": "based_on_library"}}
            
            # 默认：普通发现
            return {"intent": "discover"}
        
        # 创建播放列表（foobar2000 格式）
        if any(w in user_input for w in ["播放列表", "歌单", "playlist", "m3u8"]):
            params = {"mode": "shuffle"}  # 默认随机模式
            
            # 检测模式
            if any(w in user_input for w in ["随机", "打乱", "shuffle"]):
                params["mode"] = "shuffle"
            elif any(w in user_input for w in ["智能", "适合", "根据"]):
                params["mode"] = "smart"
                # 提取描述作为查询
                for kw in ["创建", "生成", "一个"]:
                    user_input = user_input.replace(kw, "")
                params["query"] = user_input.strip()
            
            # 检测时长
            import re
            duration_match = re.search(r'(\d+)\s*分钟', user_input)
            if duration_match:
                params["max_duration"] = int(duration_match.group(1))
            
            # 检测数量
            count_match = re.search(r'(\d+)\s*首', user_input)
            if count_match:
                params["max_songs"] = int(count_match.group(1))
            
            return {"intent": "playlist", "params": params}
        
        # 单曲元数据修复（强制重新识别）
        # 触发词：明确说"单曲/这首歌"，或者"修复 XXX"（XXX看起来像歌名）
        is_single_fix = False
        force = False
        
        if any(w in user_input for w in ["单曲", "单首", "这一首", "这首歌", "重新识别", "强制修复"]):
            is_single_fix = True
            force = any(w in user_input for w in ["重新", "强制", "更新"])
        elif any(w in user_input for w in ["修复", "补全", "更新标签"]):
            # 检查是否是"修复 歌名"或"修复 歌手 歌名"格式
            # 如果输入中有看起来像歌名的部分（包含中文或"-"分隔）
            # 且不是"修复元数据"、"修复标签"这种批量命令
            if not any(batch_word in user_input for batch_word in ["元数据", "标签", "批量", "全部", "所有"]):
                # 提取可能的歌曲名（修复后面的内容）
                for keyword in ["修复", "补全"]:
                    if keyword in user_input:
                        potential_title = user_input.split(keyword)[-1].strip()
                        # 如果提取的内容看起来是歌名（非空、不太短、不太长）
                        if 2 < len(potential_title) < 50 and not potential_title.startswith("http"):
                            is_single_fix = True
                            break
        
        if is_single_fix:
            if any(w in user_input for w in ["修复", "补全", "标签", "元数据", "识别", "更新"]):
                # 检查是否指定了文件名
                import re
                # 尝试提取引号中的文件名
                file_match = re.search(r'["\']([^"\']+)["\']', user_input)
                if file_match:
                    return {"intent": "fix_single", "params": {"file": file_match.group(1), "force": force}}
                # 检查是否在查询结果上下文中
                if self.context.last_query_results:
                    return {"intent": "fix_single", "params": {"from_query": True, "force": force}}
                # 提取歌名作为搜索词
                search_title = user_input
                for kw in ["修复", "补全", "更新标签", "单曲", "这首歌"]:
                    search_title = search_title.replace(kw, "")
                search_title = search_title.strip()
                return {"intent": "fix_single", "params": {"file": search_title, "force": force}}
        
        # 批量修复元数据
        if any(w in user_input for w in ["元数据", "标签", "修复", "补全", "封面", "专辑图"]):
            return {
                "intent": "fix_metadata",
                "params": {"confirm": "确认" in user_input, "rename": "重命名" in user_input, "download_cover": "封面" in user_input or "封面" in user_input},
                "needs_confirm": "确认" not in user_input
            }
        
        # 直接删除 WAV 文件（不转换）
        if any(w in user_input for w in ["删除wav", "删除 wav", "删掉wav", "清理wav"]):
            return {
                "intent": "delete_wav",
                "params": {"confirm": "确认" in user_input or "确定" in user_input},
                "needs_confirm": "确认" not in user_input and "确定" not in user_input
            }
        
        # 格式转换（WAV 转 FLAC）
        if any(w in user_input for w in ["转换", "convert", "转格式", "wav转flac", "wav to flac", "转成flac"]):
            delete_source = "删除" in user_input or "删掉" in user_input or "删除源文件" in user_input
            return {
                "intent": "convert",
                "params": {
                    "format": "flac",
                    "delete_source": delete_source,
                    "confirm": "确认" in user_input
                },
                "needs_confirm": "确认" not in user_input
            }
        
        # Embedding模型管理
        if any(w in user_input for w in ["模型", "embedding", "向量", "检索模型", "语义模型"]):
            if any(w in user_input for w in ["切换", "更换", "换", "使用"]):
                # 提取模型名
                for alias in EMBEDDING_MODELS.keys():
                    if alias.replace("-", "").replace("_", "").lower() in user_input_lower.replace("-", "").replace("_", ""):
                        return {"intent": "switch_model", "params": {"model": alias}}
                return {"intent": "list_models"}
            elif any(w in user_input for w in ["列表", "有哪些", "list"]):
                return {"intent": "list_models"}
            elif any(w in user_input for w in ["当前", "现在", "current"]):
                return {"intent": "current_model"}
        
        # 帮助
        if any(w in user_input for w in ["帮助", "help", "能做什么", "功能"]):
            return {"intent": "help"}
        
        # 清除
        if any(w in user_input for w in ["清除", "清空", "重置"]):
            return {"intent": "clear"}
        
        # 查询本地库中特定情绪的歌曲（优先于闲聊）
        # 检测是否是询问本地情绪歌曲
        is_emotion_query = any(w in user_input for w in ["哪些", "有什么", "推荐", "歌", "歌曲"])
        detected_emotion = None
        
        for keyword, emotion in NLPUtils.EMOTION_KEYWORDS.items():
            if keyword in user_input:
                # 特殊处理：避免"小步舞曲"被匹配为"舞曲"
                if keyword == "舞曲" and "小步舞曲" in user_input:
                    continue
                detected_emotion = emotion
                break
        
        if is_emotion_query and detected_emotion:
            return {"intent": "query_emotion_songs", "params": {"emotion": detected_emotion}}
        
        # 语言查询（如"哪些韩语歌"、"那些是韩语"）
        language_keywords = {
            "韩语": "韩语", "韩文": "韩语", "韩国": "韩语", "korean": "韩语", "kr": "韩语",
            "日语": "日语", "日文": "日语", "日本": "日语", "japanese": "日语", "jp": "日语",
            "英语": "英语", "英文": "英语", "欧美": "英语", "english": "英语", "en": "英语",
            "国语": "国语", "普通话": "国语", "中文": "国语", "mandarin": "国语", "cn": "国语",
            "粤语": "粤语", "广东话": "粤语", "cantonese": "粤语", "hk": "粤语",
        }
        
        is_language_query = any(w in user_input for w in ["哪些", "那些", "有什么", "列出", "显示", "推荐", "找"])
        detected_language = None
        
        for keyword, lang in language_keywords.items():
            if keyword in user_input:
                detected_language = lang
                break
        
        # 匹配"那些是韩语"、"哪些是英语"等
        # 但必须包含查询意图词，避免闲聊误触发（如"我中文不好"）
        if detected_language and is_language_query:
            return {"intent": "query_language_songs", "params": {"language": detected_language}}
        
        # 闲聊
        if any(w in user_input for w in ["你好", "嗨", "hello", "hi", "在吗"]):
            return {"intent": "chat", "params": {"type": "greeting"}}
        
        if any(w in user_input for w in ["无聊", "开心", "难过", "累", "烦"]):
            return {"intent": "chat", "params": {"type": "emotion", "content": user_input}}
        
        return {"intent": "chat", "params": {"type": "general", "content": user_input}}
    
    def execute(self, intent: Dict[str, Any]) -> str:
        """执行操作"""
        handlers = {
            "scan": self.handle_scan,
            "analyze": self.handle_analyze,
            "organize": self.handle_organize,
            "dedup": self.handle_dedup,
            "query": self.handle_query,
            "discover": self.handle_discover,
            "fix_metadata": self.handle_fix_metadata,
            "fix_single": self.handle_fix_single_metadata,
            "convert": self.handle_convert,
            "delete_wav": self.handle_delete_wav,
            "list_models": self.handle_list_models,
            "switch_model": self.handle_switch_model,
            "current_model": self.handle_current_model,
            "help": self.handle_help,
            "chat": self.handle_chat,
            "cancel": self.handle_cancel,
            "clear": self.handle_clear,
            "playlist": self.handle_playlist,
            "play_by_name": self.handle_play_by_name,
            "recommend_random": self.handle_recommend_random,
            "playlist_from_results": self.handle_playlist_from_results,
            "batch_select": self.handle_batch_select,
            "show_language_stats": self.handle_show_language_stats,
            "detect_language_by_audio": self.handle_detect_language_by_audio,
            "detect_single_language": self.handle_detect_single_language,
            "export_library": self.handle_export_library,
            "import_library": self.handle_import_library,
            "show_library_stats": self.handle_show_library_stats,
            "export_language_csv": self.handle_export_language_csv,
            "correct_language": self.handle_correct_language,
            "update_song_info": self.handle_update_song_info,
            "analyze_emotion": self.handle_analyze_emotion,
            "analyze_single_emotion": self.handle_analyze_single_emotion,
            "download_lyrics": self.handle_download_lyrics,
            "generate_lyrics_whisper": self.handle_generate_lyrics_whisper,
            "query_emotion_songs": self.handle_query_emotion_songs,
            "query_language_songs": self.handle_query_language_songs,
            "play": self.handle_play,
            "info": self.handle_info,
        }
        handler = handlers.get(intent.get("intent"), handlers["chat"])
        return handler(intent.get("params", {}))
    
    def handle_scan(self, params: Dict) -> str:
        print("正在扫描音乐库...")
        result = self.librarian.run("scan")
        return f"扫描完成！发现 {result['total_files']} 个文件，索引 {result['total_indexed']} 首歌曲。"
    
    def handle_analyze(self, params: Dict) -> str:
        print("正在分析音乐库...")
        analysis = self.organizer.run("analyze")
        top = analysis.get('top_artists', [])[:5]
        artists = "\n".join([f"  • {a}: {c}首" for a, c in top])
        return f"""音乐库分析：
• 总歌曲: {analysis['total_songs']} 首
• 艺术家: {analysis['artists_count']} 位
• 流派: {analysis['genres_count']} 种

Top 5 艺术家：
{artists}

推荐: {analysis['suggestion']}"""
    
    def handle_organize(self, params: Dict) -> str:
        strategy = params.get("strategy", "artist/album")
        from_pending = params.get("from_pending", False)
        
        if not from_pending:
            print(f"正在规划整理方案 ({strategy})...")
            plan = self.organizer.run("plan", strategy=OrganizeStrategy(strategy))
            preview = self.organizer.preview_plan(plan)["summary"]
            
            self.context.set_pending(PendingAction(
                action_type="organize",
                params={"strategy": strategy, "from_pending": True},
                description=f"按{strategy}整理音乐文件"
            ))
            
            return f"""整理计划预览：
• 总文件: {preview['total_files']} 首
• 将移动: {preview['to_move']} 首
• 将复制: {preview['to_copy']} 首
• 跳过: {preview['skip']} 首
• 冲突: {preview['conflicts']} 首

输入'确认'执行，或'取消'放弃。"""
        
        print("正在执行整理...")
        plan = self.organizer.run("plan", strategy=OrganizeStrategy(strategy))
        result = self.organizer.run("execute", plan=plan, dry_run=False)
        self.context.clear_pending()
        return f"整理完成！成功: {result.executed} 首, 失败: {result.failed} 首"
    
    def handle_dedup(self, params: Dict) -> str:
        """处理重复歌曲"""
        confirm = params.get("confirm", False)
        from_pending = params.get("from_pending", False)
        
        from agents.organizer import OrganizeStrategy
        
        if not from_pending:
            print("🔍 正在分析重复歌曲...")
            plan = self.organizer.run("plan", strategy=OrganizeStrategy.REMOVE_DUPLICATES)
            
            if not plan:
                return "✅ 没有发现重复歌曲！"
            
            dup_plans = [p for p in plan if p.action == "move"]
            keep_plans = [p for p in plan if p.action == "skip" and "重复" in p.reason]
            
            if not dup_plans:
                return "✅ 没有发现重复歌曲！"
            
            preview_text = ""
            shown = 0
            for p in keep_plans[:5]:
                match = p.reason.split("发现 ")[1].split(" 个")[0] if "发现 " in p.reason else "?"
                preview_text += f"\n  • 《{p.song.title}》- {p.song.artist} ({match}个重复)"
                shown += 1
            
            self.context.set_pending(PendingAction(
                action_type="dedup",
                params={"confirm": True, "from_pending": True},
                description=f"清理 {len(dup_plans)} 首重复歌曲"
            ))
            
            more_text = f"\n  ... 还有 {len(keep_plans) - shown} 组" if len(keep_plans) > shown else ""
            
            return f"""📊 重复检测结果：
• 重复组数: {len(keep_plans)} 组
• 重复文件: {len(dup_plans)} 首
• 保留文件: {len(keep_plans)} 首

重复示例:{preview_text}{more_text}

💡 重复文件将被移动到 _duplicates 文件夹（不会删除）

输入'确认'执行去重。"""
        
        print("\n🚀 正在执行去重...")
        plan = self.organizer.run("plan", strategy=OrganizeStrategy.REMOVE_DUPLICATES)
        result = self.organizer.run("execute", plan=plan, dry_run=False)
        self.context.clear_pending()
        
        return f"""✅ 去重完成！
• 已移动: {result.executed} 首重复文件到 _duplicates 文件夹
• 已保留: {len(plan) - result.executed} 首最佳版本
• 失败: {result.failed} 首

💡 重复文件保存在: MUSIC/_duplicates/
你可以手动检查并删除这些文件。"""
    
    def handle_query(self, params: Dict) -> str:
        query = params.get("query", "")
        print(f"正在搜索: {query}")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        results = self.librarian.query(query, top_k=5)
        self.context.set_query_results(results)
        
        if not results:
            return "没有找到匹配的歌曲。"
        
        lines = [f"  {i}. 《{r['song'].title}》- {r['song'].artist}" for i, r in enumerate(results, 1)]
        return f"找到 {len(results)} 首歌曲（输入序号或'第一首'选择）：\n" + "\n".join(lines)
    
    def handle_discover(self, params: Dict) -> str:
        """发现新音乐 - 支持多种模式"""
        mode = params.get("mode", "default")
        
        # 主动发现模式
        if mode != "default":
            from agents.scout import DiscoveryRequest
            
            if mode == "similar_artist":
                artist = params.get("artist", "")
                if not artist:
                    return "请指定艺术家，例如：'发现像陈奕迅的歌'"
                print(f"🔍 正在发现与 {artist} 风格相似的歌曲...")
                request = DiscoveryRequest("similar_artist", {"artist": artist, "top_k": 8}, f"与{artist}相似的歌曲")
                
            elif mode == "mood":
                mood = params.get("mood", "relax")
                mood_names = {"work": "工作", "study": "学习", "workout": "运动", 
                             "relax": "放松", "sleep": "睡眠", "party": "派对", "commute": "通勤"}
                print(f"🎵 正在发现适合{mood_names.get(mood, mood)}时听的歌...")
                request = DiscoveryRequest("mood", {"mood": mood}, f"适合{mood}场景")
                
            elif mode == "artist_new":
                artist = params.get("artist", "")
                if not artist:
                    return "请指定艺术家，例如：'陈奕迅 新专辑'"
                print(f"🆕 正在发现 {artist} 的最新发行...")
                request = DiscoveryRequest("artist_new", {"artist": artist}, f"{artist}的最新歌曲")
                
            elif mode == "explore":
                print("🌟 正在探索小众独立音乐...")
                request = DiscoveryRequest("explore", {}, "小众/冷门音乐")
            
            elif mode == "based_on_library":
                print("📚 正在分析你的音乐库偏好...")
                # 获取用户库中的 top 艺术家
                if not self.librarian.songs:
                    self.librarian.run("scan")
                
                stats = self.librarian.get_stats()
                top_artists = [a[0] for a in stats.get("top_artists", [])[:5]]
                
                if not top_artists:
                    return "你的音乐库还没有足够的歌曲来进行推荐。先添加一些歌曲吧！"
                
                print(f"   根据你喜欢的: {', '.join(top_artists[:3])}")
                request = DiscoveryRequest(
                    "based_on_library", 
                    {"librarian": self.librarian, "top_artists": top_artists},
                    f"基于你的音乐库（Top艺术家: {', '.join(top_artists[:3])}）"
                )
            else:
                return f"未知的发现模式: {mode}"
            
            try:
                candidates = self.scout.run("active", discovery_request=request)
                
                if not candidates:
                    return f"暂时没有符合条件的歌曲，换个条件试试吧！"
                
                print(f"📬 发现 {len(candidates)} 首候选歌曲")
                
                # 主动发现模式不经过策展人评估（因为是你主动要求的）
                rec_lines = []
                for i, song in enumerate(candidates[:8], 1):
                    reason = song.metadata.get("reason", "")
                    rec_lines.append(f"{i}. 《{song.title}》- {song.artist}")
                    if reason:
                        rec_lines.append(f"   💡 {reason}")
                
                return f"""🎵 {request.reason}

发现 {len(candidates)} 首歌曲：
{chr(10).join(rec_lines)}

💡 提示: 可以对我说"播放第3首"来播放"""
                
            except Exception as e:
                return f"发现音乐时出错了: {e}"
        
        # 默认模式：自动发现新发行
        print("🔍 正在发现新音乐...")
        
        try:
            candidates = self.scout.run("all")
            if not candidates:
                return "本周没有发现新音乐，下周再来看看吧！"
            
            print(f"📬 发现 {len(candidates)} 首候选歌曲")
            print("🤖 策展人正在评估...")
            
            recommendations = self.curator.run("evaluate", candidates=candidates)
            
            if not recommendations:
                return "本周没有发现适合你的新音乐，下次再看看！"
            
            # 生成报告
            report = self.curator.run("report", recommendations=recommendations)
            
            # 格式化输出
            rec_lines = []
            for i, rec in enumerate(report['recommendations'][:5], 1):
                badge = "⭐" if rec.get('action') == 'highly_recommend' else "👍"
                rec_lines.append(f"{badge} 《{rec['title']}》- {rec['artist']}")
                rec_lines.append(f"   推荐理由: {rec['reason']}")
            
            return f"""📊 {report['title']}

本周发现: {report['summary']['total_discovered']} 首
强烈推荐: {report['summary']['highly_recommended']} 首
涉及流派: {', '.join(report['summary']['genres'])}

本周推荐:
{chr(10).join(rec_lines)}

💡 更多发现方式：
• "发现像陈奕迅的歌" - 找相似风格
• "工作时的歌" - 按场景发现  
• "小众音乐" - 探索冷门佳作
• "周杰伦 新专辑" - 追踪新发行"""
            
        except Exception as e:
            return f"发现新音乐时出错了: {e}\n可能需要配置 Reddit API 或检查网络连接。"
    
    def handle_fix_metadata(self, params: Dict) -> str:
        confirm = params.get("confirm", False)
        rename = params.get("rename", False)
        download_cover = params.get("download_cover", True)
        from_pending = params.get("from_pending", False)
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        if not from_pending:
            result = self.librarian.fix_metadata(dry_run=True, rename_files=rename, download_cover=False)
            
            if result["incomplete"] == 0:
                return "所有歌曲元数据完整！"
            
            remaining_hint = f"\n• 将分批处理，本次处理 {result.get('processed', result['incomplete'])} 首" if result.get('remaining', 0) > 0 else ""
            
            self.context.set_pending(PendingAction(
                action_type="fix_metadata",
                params={"confirm": True, "rename": rename, "download_cover": download_cover, "from_pending": True},
                description=f"修复元数据{'并下载封面' if download_cover else ''}{'并重命名' if rename else ''}"
            ))
            
            # 分析数据源
            source_stats = result.get('source_stats', {})
            source_details = []
            for key, name in [('qq_music', '🐧 QQ音乐'), ('netease', '☁️ 网易云'), 
                              ('musicbrainz', '🎵 MusicBrainz'), ('llm_parse', '🤖 LLM解析'),
                              ('local_parse', '📄 本地解析')]:
                if source_stats.get(key, 0) > 0:
                    source_details.append(f"{name}: {source_stats[key]}首")
            
            source_text = " | ".join(source_details) if source_details else "未获取到数据源信息"
            
            return f"""元数据检查（预览模式）：
• 总歌曲: {result['total']} 首
• 待修复: {result['incomplete']} 首
• 可识别: {result['fixed']} 首{remaining_hint}

📊 识别来源: {source_text}

💡 说明：
• "可识别"表示能从文件名或在线搜索找到歌曲信息
• 在线搜索优先顺序: QQ音乐 → 网易云 → MusicBrainz
• 实际写入需要确认后才执行
• 仅支持写入 FLAC/MP3/M4A 格式

输入'确认'执行修复，或'取消'放弃。"""
        
        print("正在修复元数据...")
        result = self.librarian.fix_metadata(dry_run=False, rename_files=rename, download_cover=download_cover)
        self.context.clear_pending()
        
        source_stats = result.get('source_stats', {})
        source_display = []
        for key, name in [('local_parse', '本地'), ('llm_parse', 'LLM'), ('qq_music', 'QQ音乐'), 
                          ('netease', '网易云'), ('musicbrainz', 'MusicBrainz')]:
            if source_stats.get(key, 0) > 0:
                source_display.append(f"{name}:{source_stats[key]}")
        
        source_summary = " | ".join(source_display) if source_display else "未知"
        cover_info = f"\n• 嵌入封面: {result.get('covers', 0)} 首" if result.get('covers', 0) > 0 else ""
        remaining_hint = f"\n• 剩余待处理: {result.get('remaining', 0)} 首（再次输入'修复元数据'继续）" if result.get('remaining', 0) > 0 else ""
        
        # 分析写入情况
        written = result.get('written', 0)
        fixed = result.get('fixed', 0)
        skipped = result.get('skipped_write', 0)
        failures = result.get('write_failures', [])
        
        # 构建详细提示
        details = []
        if skipped > 0:
            details.append(f"• 格式不支持跳过: {skipped} 首")
        if failures and written == 0:
            details.append("• 写入失败原因示例:")
            for f in failures[:3]:
                details.append(f"  - {f}")
        
        detail_text = "\n".join(details) if details else ""
        
        if written == 0 and fixed > 0:
            write_hint = f"""
⚠️ 注意：识别成功但未写入文件标签
可能原因：
• 文件格式不支持（仅支持 FLAC/MP3/M4A，不支持 WAV/OGG 等）
• 文件被占用（请关闭音乐播放器）
• 文件权限只读
{detail_text}"""
        elif details:
            write_hint = f"\n{detail_text}"
        else:
            write_hint = ""
        
        return f"""修复完成！
• 本次处理: {result.get('processed', fixed)} 首
• 成功识别: {fixed} 首（从文件名/在线搜索获取信息）
• 写入标签: {written} 首{write_hint}
• 数据来源: {source_summary}{cover_info}{remaining_hint}"""
    
    def handle_fix_single_metadata(self, params: Dict) -> str:
        """修复单曲元数据（指定文件或查询结果中的歌曲）"""
        file_hint = params.get("file")
        from_query = params.get("from_query", False)
        force = params.get("force", False)
        confirm = params.get("confirm", False)
        from_pending = params.get("from_pending", False)
        selected_idx = params.get("selected_idx")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 确定目标歌曲
        target_song = None
        
        # 优先处理 from_pending（确认后的执行）
        if from_pending:
            # 通过 song_id 直接获取歌曲
            song_id = params.get('song_id')
            target_song = self.librarian.songs.get(song_id)
            if not target_song:
                return "❌ 错误：找不到要更新的歌曲，请重新搜索"
        elif selected_idx is not None and self.context.last_query_results:
            # 通过序号选择
            if 0 <= selected_idx < len(self.context.last_query_results):
                target_song = self.context.last_query_results[selected_idx].get('song')
        elif file_hint:
            # 优先精确匹配：从搜索词中提取歌名和歌手
            search_lower = file_hint.lower()
            
            # 1. 先尝试精确匹配（标题或文件名包含搜索词）
            exact_matches = []
            for song_id, song in self.librarian.songs.items():
                file_name = Path(song.file_path).stem.lower()
                title = song.title.lower()
                artist = song.artist.lower()
                
                # 精确包含匹配
                if search_lower in title or search_lower in file_name:
                    # 计算匹配质量（搜索词占标题的比例）
                    match_quality = len(search_lower) / max(len(title), 1)
                    exact_matches.append((song, match_quality, 'title'))
                elif search_lower in artist:
                    exact_matches.append((song, 0.5, 'artist'))  # 歌手匹配权重较低
            
            # 按匹配质量排序
            if exact_matches:
                exact_matches.sort(key=lambda x: x[1], reverse=True)
                target_song = exact_matches[0][0]
                print(f"✓ 精确匹配: {target_song.artist} - {target_song.title}")
            
            # 2. 精确匹配失败，尝试分词匹配（处理"杨千嬅的处处吻"→"杨千嬅"+"处处吻"）
            if not target_song:
                # 尝试提取歌手和歌名
                parts = [p.strip() for p in re.split(r'[的\-\s]', search_lower) if len(p.strip()) > 1]
                
                if len(parts) >= 2:
                    # 可能格式：歌手 + 歌名
                    possible_artist = parts[0]
                    possible_title = parts[-1]
                    
                    for song_id, song in self.librarian.songs.items():
                        artist_match = possible_artist in song.artist.lower().replace(" ", "")
                        title_match = possible_title in song.title.lower().replace(" ", "")
                        
                        if artist_match and title_match:
                            target_song = song
                            print(f"✓ 分词匹配: {target_song.artist} - {target_song.title}")
                            break
            
            # 3. 最后才用RAG向量搜索（容易匹配到相似但不同的歌）
            if not target_song:
                print(f"🔍 正在向量搜索: {file_hint}")
                results = self.librarian.query(file_hint, top_k=5, use_threshold=False)
                
                # 过滤：确保至少有一个关键词匹配（避免匹配到完全不同的歌）
                for result in results:
                    song = result.get('song')
                    if song:
                        # 检查是否有共同词汇
                        search_words = set(search_lower.replace(" ", ""))
                        title_words = set(song.title.lower().replace(" ", ""))
                        artist_words = set(song.artist.lower().replace(" ", ""))
                        
                        # 如果搜索词和标题/歌手有共同字
                        if search_words & title_words or search_words & artist_words:
                            target_song = song
                            print(f"✓ 向量搜索+过滤: {target_song.artist} - {target_song.title}")
                            break
                
                # 还是没找到，用第一个但提示用户
                if not target_song and results:
                    target_song = results[0].get('song')
                    if target_song:
                        print(f"⚠️  最接近的匹配: {target_song.artist} - {target_song.title}（可能不是您要找的歌）")
        elif from_query and self.context.last_query_results:
            # 使用最近一次查询结果的第一首
            target_song = self.context.last_query_results[0].get('song')
        
        if not target_song:
            # 尝试直接用搜索词在线识别（不依赖本地匹配）
            if file_hint and len(file_hint) > 2:
                print(f"🔍 本地未找到匹配，尝试在线识别: {file_hint}")
                from agents.metadata_enhancer import MetadataEnhancer
                enhancer = MetadataEnhancer(kimi_client=self.librarian.kimi if self.librarian.has_llm else None)
                
                metadata = enhancer.search_by_filename(file_hint + ".mp3", download_cover=True)  # 加假扩展名帮助解析
                
                if metadata and metadata.get("title"):
                    # 找到了在线信息，但本地没这首歌，提示用户
                    return f"""🔍 在线识别结果:

搜索词: {file_hint}
识别结果:
• 歌名: {metadata.get('title')}
• 歌手: {metadata.get('artist')}
• 专辑: {metadata.get('album', '未知')}
• 来源: {metadata.get('source', '未知')}

⚠️ 但在本地音乐库中未找到匹配的文件。

可能原因：
• 文件名与搜索词差异较大
• 这首歌不在你的音乐库中

建议：
• 使用'重新识别'列出所有歌曲
• 或检查文件名是否包含歌手和歌名"""
            
            # 交互式选择：列出元数据可疑的歌曲（Unknown 或 force 模式下列出更多）
            if force:
                # 强制模式下，列出所有歌曲供选择
                candidates = list(self.librarian.songs.values())[:20]
                title = "📋 选择要重新识别的歌曲（输入序号）：\n"
            else:
                # 普通模式下，只列出不完整的
                candidates = [s for s in self.librarian.songs.values() 
                             if s.artist == "Unknown" or s.title == "Unknown"]
                title = "📋 找到以下元数据不完整的歌曲（输入序号选择）：\n"
            
            if not candidates:
                return "✅ 所有歌曲元数据都完整！没有需要修复的单曲。\n\n如果现有信息有误，请使用'重新识别'或'强制修复'。"
            
            # 显示候选歌曲
            lines = [title]
            for i, s in enumerate(candidates[:10], 1):
                filename = Path(s.file_path).name
                current = f"[{s.artist} - {s.title}]" if s.artist != "Unknown" else "[Unknown]"
                lines.append(f"  {i}. {filename} {current}")
            
            # 保存到上下文供后续选择
            self.context.set_query_results([{"song": s} for s in candidates[:10]])
            
            hint = "输入序号（如'1'）选择歌曲" if force else "输入序号（如'1'）选择要修复的歌曲"
            return "\n".join(lines) + f"\n\n{hint}，或输入'取消'放弃。"
        
        # 找到了目标歌曲
        filename = Path(target_song.file_path).name
        
        # 显示找到了哪首歌（特别是模糊匹配的情况）
        if file_hint and file_hint not in filename:
            print(f"💡 搜索 '{file_hint}' 找到: {target_song.artist} - {target_song.title}")
        
        # 如果不是从pending来的，先进行识别并让用户确认
        if not from_pending:
            print(f"🔍 正在识别: {filename}")
            
            # 使用 metadata_enhancer 搜索
            from agents.metadata_enhancer import MetadataEnhancer
            enhancer = MetadataEnhancer(kimi_client=self.librarian.kimi if self.librarian.has_llm else None)
            
            metadata = enhancer.search_by_filename(filename, download_cover=True)
            
            if not metadata or not metadata.get("title"):
                return f"❌ 未能识别歌曲信息: {filename}\n\n你可以：\n• 检查文件名是否包含歌手和歌名\n• 尝试手动修改文件名后重新扫描\n• 或使用批量修复功能'修复元数据'"
            
            # 保存识别结果到 pending action（同时保存 cover_url 以便确认后重新下载）
            self.context.set_pending(PendingAction(
                action_type="fix_single",
                params={
                    "song_id": target_song.id,
                    "title": metadata.get('title'),
                    "artist": metadata.get('artist'),
                    "album": metadata.get('album', ''),
                    "year": metadata.get('year', 0),
                    "genre": metadata.get('genre', ''),
                    "cover_path": metadata.get('cover_path'),
                    "cover_url": metadata.get('cover_url'),  # 保存URL以便重新下载
                    "source": metadata.get('source'),
                    "from_pending": True
                },
                description=f"修复单曲元数据: {metadata.get('artist')} - {metadata.get('title')}"
            ))
            
            # 显示对比
            has_cover_path = metadata.get('cover_path') is not None
            has_cover_url = metadata.get('cover_url') is not None
            
            if has_cover_path:
                cover_status = "✅ 已下载"
            elif has_cover_url:
                cover_status = "⏳ 将在确认后下载"
            else:
                cover_status = "❌ 无封面数据"
            
            comparison = f"""📀 识别结果对比:

文件名: {filename}

当前信息:
• 歌名: {target_song.title}
• 歌手: {target_song.artist}
• 专辑: {target_song.album or '未知'}
• 封面: {'✅ 有' if False else '❌ 无'}

新识别信息:
• 歌名: {metadata.get('title')}
• 歌手: {metadata.get('artist')}
• 专辑: {metadata.get('album', '未知')}
• 封面: {cover_status}
• 来源: {metadata.get('source', '未知')}"""
            
            # 检查是否一致
            is_different = (target_song.title != metadata.get('title') or 
                           target_song.artist != metadata.get('artist'))
            
            if is_different:
                comparison += "\n\n⚠️  注意：新识别信息与当前标签不一致！"
            
            comparison += "\n\n💡 确认后将同时写入元数据标签和专辑封面（如可用）"
            comparison += "\n输入'确认'执行，或'取消'放弃。"
            
            return comparison
        
        # 从 pending 来，执行实际写入（现在 song_id 查找已经在前面处理了）
        self.context.clear_pending()
        
        print(f"📝 正在写入: {target_song.artist} - {target_song.title}")
        
        # 更新歌曲对象
        target_song.title = params.get('title')
        target_song.artist = params.get('artist')
        if params.get('album'):
            target_song.album = params.get('album')
        if params.get('year'):
            target_song.year = params.get('year')
        if params.get('genre'):
            target_song.genre = params.get('genre')
        
        print(f"   新信息: {target_song.artist} - {target_song.title}")
        
        # 执行修复
        ext = Path(target_song.file_path).suffix.lower()
        if ext in ['.flac', '.mp3', '.m4a', '.mp4']:
            # 获取封面路径，如果没有但URL存在，尝试重新下载
            cover_path = params.get('cover_path')
            cover_url = params.get('cover_url')
            
            if not cover_path and cover_url:
                print(f"   [重新下载封面] ...")
                from agents.metadata_enhancer import MetadataEnhancer
                enhancer = MetadataEnhancer()
                cover_path = enhancer._download_cover(cover_url, target_song.album or target_song.title)
                if cover_path:
                    print(f"   [封面下载成功]")
                else:
                    print(f"   [封面下载失败]")
            
            has_cover = cover_path is not None
            
            if self.librarian._write_metadata_to_file(target_song, cover_path):
                result_lines = [
                    "✅ 元数据已成功写入！",
                    "",
                    f"• {target_song.artist} - {target_song.title}",
                    f"• 专辑: {target_song.album or '未知'}",
                ]
                
                if has_cover:
                    result_lines.append("🖼️ 专辑封面已嵌入")
                else:
                    result_lines.append("💡 未找到专辑封面（QQ音乐/网易云可能没有封面数据）")
                
                return "\n".join(result_lines)
            else:
                return "⚠️ 更新内存信息成功，但写入文件失败，请检查文件权限"
        else:
            return f"⚠️ 格式 {ext} 不支持写入标签，建议转换为 FLAC 格式\n输入'转换 wav 到 flac'进行转换"
    
    def handle_convert(self, params: Dict) -> str:
        """处理音频格式转换（WAV 转 FLAC）"""
        output_format = params.get("format", "flac")
        delete_source = params.get("delete_source", False)
        confirm = params.get("confirm", False)
        from_pending = params.get("from_pending", False)
        
        # 初始化转换器
        converter = AudioConverter()
        
        # 检查 ffmpeg
        if not converter.check_ffmpeg():
            return converter.get_ffmpeg_install_help()
        
        library_path = self.config.get("library", {}).get("path", ".")
        
        if not from_pending:
            # 预览模式
            print("🔍 扫描可转换的音频文件...")
            preview = preview_conversion(library_path)
            
            if not preview['convertible']:
                return "✅ 没有发现需要转换的文件（没有 WAV/AIFF 格式文件）"
            
            files = preview['convertible']
            file_list = "\n".join([f"  • {Path(f['source']).name} ({f['size_mb']}MB)" for f in files[:5]])
            more = f"\n  ... 还有 {len(files) - 5} 个文件" if len(files) > 5 else ""
            
            # 设置待执行操作
            self.context.set_pending(PendingAction(
                action_type="convert",
                params={
                    "format": output_format,
                    "delete_source": delete_source,
                    "confirm": True,
                    "from_pending": True
                },
                description=f"将 {len(files)} 个文件转换为 {output_format.upper()}{' 并删除源文件' if delete_source else ''}"
            ))
            
            delete_hint = "\n⚠️  注意：转换后将删除原始 WAV 文件" if delete_source else ""
            
            return f"""🎵 音频格式转换预览

可转换文件: {len(files)} 个
总大小: {preview['total_size_mb']} MB
预计转换后: ~{round(preview['total_size_mb'] * 0.6)} MB (FLAC 压缩)
预计节省: {preview['estimated_savings_mb']} MB

示例文件:
{file_list}{more}{delete_hint}

转换好处：
• 节省磁盘空间（FLAC 比 WAV 小 30-50%）
• 支持完整的元数据标签
• 支持专辑封面嵌入
• 音质完全无损

输入'确认转换'执行，或'取消'放弃。"""
        
        # 执行转换
        print("\n🚀 开始转换...")
        
        # 扫描文件
        files = converter.scan_convertible_files(library_path)
        tasks = converter.generate_conversion_plan(files, f".{output_format}")
        
        if not tasks:
            self.context.clear_pending()
            return "❌ 没有找到可转换的文件"
        
        # 执行批量转换
        total = len(tasks)
        success = 0
        failed = 0
        
        print(f"共 {total} 个文件需要转换\n")
        
        for i, task in enumerate(tasks, 1):
            print(f"[{i}/{total}] {Path(task.source_path).name}...", end=" ", flush=True)
            
            if converter.convert_file(task):
                print("✅")
                success += 1
            else:
                print(f"❌ {task.error}")
                failed += 1
        
        # 如果需要，删除源文件
        delete_result = None
        if delete_source and success > 0:
            print(f"\n🗑️  正在删除源文件...")
            delete_result = converter.delete_source_files(tasks, dry_run=False)
        
        self.context.clear_pending()
        
        # 构建结果消息
        result_msg = f"""✅ 转换完成！
• 总计: {total} 个文件
• 成功: {success} 个
• 失败: {failed} 个"""
        
        if delete_result:
            result_msg += f"\n• 已删除源文件: {delete_result['deleted']} 个"
            if delete_result['errors'] > 0:
                result_msg += f"\n• 删除失败: {delete_result['errors']} 个"
        
        result_msg += """\n\n💡 提示：
转换后的 FLAC 文件已保存在原目录。
建议运行'修复元数据'补全歌曲信息。"""
        
        return result_msg
    
    def handle_delete_wav(self, params: Dict) -> str:
        """直接删除 WAV 文件（不转换）"""
        confirm = params.get("confirm", False)
        from_pending = params.get("from_pending", False)
        
        library_path = self.config.get("library", {}).get("path", ".")
        
        # 扫描 WAV 文件
        from core.audio_converter import AudioConverter
        converter = AudioConverter()
        wav_files = converter.scan_convertible_files(library_path)
        
        if not wav_files:
            return "✅ 没有发现 WAV 文件"
        
        if not from_pending:
            # 预览模式
            total_size = sum(Path(f).stat().st_size for f in wav_files)
            file_list = "\n".join([f"  • {Path(f).name}" for f in wav_files[:5]])
            more = f"\n  ... 还有 {len(wav_files) - 5} 个文件" if len(wav_files) > 5 else ""
            
            self.context.set_pending(PendingAction(
                action_type="delete_wav",
                params={"confirm": True, "from_pending": True},
                description=f"删除 {len(wav_files)} 个 WAV 文件（释放 {round(total_size/1024/1024)} MB 空间）"
            ))
            
            return f"""🗑️ 删除 WAV 文件预览

发现 WAV 文件: {len(wav_files)} 个
总大小: {round(total_size/1024/1024)} MB

文件列表:
{file_list}{more}

⚠️  警告：此操作将永久删除文件，无法恢复！
如果文件中有珍贵的音乐，建议先转换为 FLAC 格式。

输入'确认删除'执行删除，或'取消'放弃。
输入'转换 wav 到 flac'可先转换再删除。"""
        
        # 执行删除
        print(f"\n🗑️  正在删除 {len(wav_files)} 个 WAV 文件...")
        deleted = 0
        failed = 0
        errors = []
        
        for i, file_path in enumerate(wav_files, 1):
            print(f"  [{i}/{len(wav_files)}] {Path(file_path).name}...", end=" ")
            try:
                Path(file_path).unlink()
                print("已删除")
                deleted += 1
            except Exception as e:
                print(f"失败: {e}")
                failed += 1
                errors.append(f"{Path(file_path).name}: {e}")
        
        self.context.clear_pending()
        
        result = f"""✅ 删除完成！
• 总计: {len(wav_files)} 个文件
• 已删除: {deleted} 个
• 失败: {failed} 个"""
        
        if errors and failed > 0:
            result += f"\n\n错误详情:\n" + "\n".join(errors[:3])
        
        return result
    
    def handle_list_models(self, params: Dict) -> str:
        """列出可用的Embedding模型"""
        from core.vector_store import _check_sentence_transformers
        
        has_st = _check_sentence_transformers()
        
        lines = ["📋 可用Embedding模型：\n"]
        
        if not has_st:
            lines.append("⚠️  sentence-transformers 未安装，当前使用ChromaDB默认embedding")
            lines.append("    查询功能可用，但中文语义理解效果可能稍差\n")
            lines.append("💡 如需高质量中文检索，请安装：")
            lines.append("   pip install sentence-transformers\n")
        
        lines.append(f"{'别名':<20} {'模型名称':<45} {'状态'}")
        lines.append("-" * 80)
        
        current = self.config.get("rag", {}).get("embedding_model", "bge-small-zh")
        
        descriptions = {
            "bge-small-zh": "中文轻量，速度快，推荐" if has_st else "需安装 sentence-transformers",
            "bge-large-zh": "中文高精度，质量更好" if has_st else "需安装 sentence-transformers",
            "bge-base-zh": "平衡选择" if has_st else "需安装 sentence-transformers",
            "paraphrase-multilingual": "多语言支持" if has_st else "需安装 sentence-transformers",
            "all-MiniLM": "英文轻量（不推荐中文）" if has_st else "需安装 sentence-transformers",
        }
        
        for alias, model_name in EMBEDDING_MODELS.items():
            status = "✓ 当前使用" if alias == current else ""
            if not has_st:
                status = "✗ 需安装依赖"
            desc = descriptions.get(alias, "")
            lines.append(f"{alias:<20} {model_name:<45} {status}")
            if desc:
                lines.append(f"  └─ {desc}")
        
        if has_st:
            lines.append(f"\n💡 使用方式：输入'切换模型 bge-large-zh'")
        else:
            lines.append(f"\n⚠️  当前使用ChromaDB内置embedding，无需切换")
            lines.append("   安装 sentence-transformers 后可使用高质量中文模型")
        
        return "\n".join(lines)
    
    def handle_switch_model(self, params: Dict) -> str:
        """切换Embedding模型"""
        from core.vector_store import _check_sentence_transformers
        
        # 检查是否安装了 sentence-transformers
        if not _check_sentence_transformers():
            return """❌ 无法切换模型

sentence-transformers 未安装，当前使用ChromaDB默认embedding。

如需使用高质量中文模型，请安装：
   pip install sentence-transformers

安装后可使用：
   • bge-small-zh (推荐) - 中文轻量，速度快
   • bge-large-zh - 中文高精度，质量更好
   • bge-base-zh - 平衡选择

当前状态：使用ChromaDB默认embedding（无需额外安装，查询功能正常）"""
        
        model_alias = params.get("model", "bge-small-zh")
        
        if model_alias not in EMBEDDING_MODELS:
            return f"❌ 未知模型: {model_alias}\n可用模型: {', '.join(EMBEDDING_MODELS.keys())}"
        
        # 更新配置
        self.config["rag"]["embedding_model"] = model_alias
        
        # 保存到配置文件
        try:
            config_path = Path(__file__).parent / "config.yaml"
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 替换配置中的模型名称
            import re
            content = re.sub(
                r'(embedding_model:\s*)"[^"]+"',
                f'\\1"{model_alias}"',
                content
            )
            
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(content)
            
            return f"""✅ 已切换到模型: {model_alias}
📦 {EMBEDDING_MODELS[model_alias]}

⚠️  重要：更换模型后需要重建向量数据库
请按以下步骤操作：
1. 退出当前会话
2. 运行: python tools_manage_embedding.py reset
3. 重新运行本程序，输入'扫描'重建索引

原因：不同模型生成的向量不兼容，必须重新计算"""
            
        except Exception as e:
            return f"❌ 保存配置失败: {e}\n但当前会话已切换，重启后失效。"
    
    def handle_current_model(self, params: Dict) -> str:
        """显示当前使用的模型"""
        from core.vector_store import _check_sentence_transformers
        
        has_st = _check_sentence_transformers()
        
        # 获取向量库统计
        stats = self.librarian.vector_store.get_stats()
        
        if not has_st:
            return f"""📊 当前Embedding配置：
• 模式: ChromaDB默认embedding
• 状态: ⚠️ sentence-transformers 未安装
• 已索引歌曲: {stats.get('document_count', 0)} 首

💡 说明：
当前使用ChromaDB内置的embedding算法，无需额外安装依赖。
查询功能完全可用，但中文语义理解效果可能不如专用模型。

如需高质量中文检索，请安装：
   pip install sentence-transformers

安装后可使用 bge-small-zh 等中文优化模型。"""
        
        current = self.config.get("rag", {}).get("embedding_model", "bge-small-zh")
        model_full = EMBEDDING_MODELS.get(current, current)
        
        return f"""📊 当前Embedding配置：
• 模型别名: {current}
• 模型全称: {model_full}
• 运行设备: {stats.get('device', 'cpu')}
• 向量维度: 根据模型而定（约384-1024维）
• 已索引歌曲: {stats.get('document_count', 0)} 首

💡 要切换模型，输入: 切换模型 bge-large-zh"""
    
    def handle_recommend_random(self, params: Dict) -> str:
        """随机推荐歌曲并说明理由"""
        import random
        
        count = params.get("count", 5)
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        if not self.librarian.songs:
            return "音乐库为空"
        
        # 随机选择歌曲
        all_songs = list(self.librarian.songs.values())
        selected = random.sample(all_songs, min(count, len(all_songs)))
        
        print(f"🎲 随机选择了 {len(selected)} 首歌曲，正在生成推荐理由...")
        
        # 保存到上下文，支持"播放第X首"
        self.context.last_query_results = [{"song": s} for s in selected]
        
        # 使用LLM生成推荐理由
        recommendations = []
        for i, song in enumerate(selected, 1):
            reason = self._generate_recommendation_reason(song)
            recommendations.append(f"{i}. 《{song.title}》- {song.artist}\n   💡 {reason}")
        
        return f"""
🎯 为你随机推荐 {len(selected)} 首歌：

{chr(10).join(recommendations)}

💿 输入"播放第X首"或"1/2/3"直接播放，"播放全部"生成歌单
"""
    
    def _generate_recommendation_reason(self, song) -> str:
        """生成歌曲推荐理由"""
        # 尝试获取情绪信息
        emotion_desc = ""
        try:
            from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
            analyzer = SimpleEmotionAnalyzer()
            cache_key = analyzer._get_file_hash(song.file_path)
            if cache_key in analyzer._cache:
                emotion = analyzer._cache[cache_key].get('emotion', '')
                emotion_names = {
                    'happy': '充满活力', 'sad': '深情动人', 'energetic': '热血沸腾',
                    'calm': '宁静治愈', 'romantic': '浪漫甜蜜', 'nostalgic': '怀旧经典',
                    'angry': '情绪宣泄', 'focus': '专注沉浸', 'party': '欢快派对'
                }
                emotion_desc = emotion_names.get(emotion, '')
        except:
            pass
        
        # 基于元数据生成理由
        reasons = []
        
        if emotion_desc:
            reasons.append(f"{emotion_desc}的风格")
        
        if song.genre:
            reasons.append(f"经典的{song.genre}")
        
        if song.year:
            current_year = 2024
            if current_year - int(song.year) > 20:
                reasons.append(f"{song.year}年的怀旧之作")
            elif current_year - int(song.year) < 5:
                reasons.append(f"近年新发行")
        
        if song.artist:
            reasons.append(f"{song.artist}的代表作品")
        
        # 保底理由
        if not reasons:
            reasons = ["独特的音乐魅力", "值得细细品味"]
        
        # 如果有LLM，用LLM生成更好的理由
        if self.kimi and len(reasons) > 0:
            try:
                prompt = f"""歌曲：《{song.title}》- {song.artist}
风格：{song.genre or '未知'}
情绪：{emotion_desc or '未知'}

用1句话（20字以内）推荐这首歌，要文艺、有感染力："""
                
                response = self.kimi.chat([{"role": "user", "content": prompt}])
                if response and len(response) < 50:
                    return response.strip('"')
            except:
                pass
        
        return "，".join(reasons[:2])
    
    def _create_m3u8_playlist(self, songs: List, playlist_name: str) -> Path:
        """创建 M3U8 播放列表文件
        
        关键：M3U8 中的路径必须是相对于 M3U8 文件所在目录的，
        这样 foobar2000 才能正确解析。
        """
        from pathlib import Path
        playlist_dir = Path(self.config.get("library", {}).get("path", ".")) / "Playlists"
        playlist_dir.mkdir(exist_ok=True)
        
        playlist_path = playlist_dir / f"{playlist_name}.m3u8"
        
        import os
        lines = ["#EXTM3U", f"#PLAYLIST:{playlist_name}"]
        for song in songs:
            # 路径必须是相对于 M3U8 文件所在目录的（不是相对于 library_path）
            # 用 os.path.relpath 处理兄弟目录关系（如 Playlists/../MUSIC/xxx）
            try:
                rel_path = os.path.relpath(song.file_path, playlist_dir)
                # Windows 反斜杠转为正斜杠（M3U8 标准用正斜杠）
                rel_path = rel_path.replace(os.sep, '/')
            except ValueError:
                # 不同盘符，只能用绝对路径
                rel_path = song.file_path
            
            duration = getattr(song, 'duration', 240) or 240
            lines.append(f"#EXTINF:{int(duration)},{song.artist} - {song.title}")
            lines.append(rel_path)
        
        playlist_path.write_text("\n".join(lines), encoding='utf-8')
        return playlist_path
    
    def handle_playlist_from_results(self, params: Dict) -> str:
        """将上次查询结果生成播放列表并播放"""
        if not self.context.last_query_results:
            return "没有可播放的歌曲列表"
        
        results = self.context.last_query_results
        songs = [item.get('song') for item in results if item.get('song')]
        
        if not songs:
            return "列表中没有有效歌曲"
        
        timestamp = datetime.now().strftime("%m%d_%H%M")
        playlist_name = f"推荐歌单_{timestamp}_{len(songs)}首"
        playlist_path = self._create_m3u8_playlist(songs, playlist_name)
        
        # 调用foobar2000播放
        foobar_result = self._play_with_foobar2000(str(playlist_path))
        
        if foobar_result:
            return f"""
🎵 正在播放全部 {len(songs)} 首歌！

📋 {playlist_name}
💾 {playlist_path}
🎧 {foobar_result}

💡 歌单已保存，下次可直接在foobar2000中打开
"""
        else:
            return f"""
✅ 播放列表已创建！

📋 {playlist_name}
🎵 {len(songs)} 首歌曲
💾 {playlist_path}

💡 未找到foobar2000，请手动导入播放列表
"""
    
    def handle_batch_select(self, params: Dict) -> str:
        """将用户多选的结果生成播放列表并播放"""
        indices = params.get("indices", [])
        
        if not self.context.last_query_results:
            return "没有可播放的歌曲列表"
        
        if not indices:
            return "没有选择任何歌曲"
        
        results = self.context.last_query_results
        selected = []
        for idx in indices:
            if 0 <= idx < len(results):
                song = results[idx].get('song')
                if song:
                    selected.append(song)
        
        if not selected:
            return "选择的位置没有有效歌曲"
        
        timestamp = datetime.now().strftime("%m%d_%H%M")
        playlist_name = f"自选歌单_{timestamp}_{len(selected)}首"
        playlist_path = self._create_m3u8_playlist(selected, playlist_name)
        
        # 调用foobar2000播放
        foobar_result = self._play_with_foobar2000(str(playlist_path))
        
        # 构建选中歌曲列表
        song_list = "\n".join([f"  {i+1}. {s.artist} - {s.title}" for i, s in enumerate(selected)])
        
        if foobar_result:
            return f"""
🎵 正在播放选中的 {len(selected)} 首歌！

📋 {playlist_name}
{song_list}
💾 {playlist_path}
🎧 {foobar_result}

💡 歌单已保存，下次可直接在foobar2000中打开
"""
        else:
            return f"""
✅ 播放列表已创建！

📋 {playlist_name}
{song_list}
🎵 {len(selected)} 首歌曲
💾 {playlist_path}

💡 未找到foobar2000，请手动导入播放列表
"""
    
    def handle_show_language_stats(self, params: Dict) -> str:
        """显示语言统计"""
        from core.language_detector import detector
        
        if not self.librarian.songs:
            return "请先扫描音乐库"
        
        # 检测所有歌曲（使用缓存）
        print("正在统计语言分布...")
        for song in self.librarian.songs.values():
            detector.detect(song.title, song.artist, song.file_path)
        
        stats = detector.get_stats()
        total = sum(stats.values())
        
        lines = ["📊 歌曲语言分布统计", "=" * 40]
        for lang, count in stats.items():
            bar = "█" * (count * 30 // total if total > 0 else 0)
            lines.append(f"  {lang:6} | {bar:30} | {count}首")
        lines.append("=" * 40)
        lines.append(f"总计: {total} 首")
        lines.append("")
        lines.append("💡 操作命令:")
        lines.append("  有哪些韩语歌 - 查询韩语歌曲")
        lines.append("  标记 IU - Blueming 为 韩语 - 纠正语言")
        lines.append("  导出语言 - 导出CSV批量编辑")
        
        return "\n".join(lines)
    
    def handle_detect_single_language(self, params: Dict) -> str:
        """检测单首歌曲的语言（详细版）"""
        from core.language_detector import detect_language
        from core.audio_language_detector import detect_audio_language
        
        song_name = params.get("song_name", "")
        if not song_name:
            return "请告诉我歌曲名称，例如：检测BTS语言"
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 查找歌曲
        matched = []
        for song in self.librarian.songs.values():
            if song_name.lower() in song.title.lower() or \
               song_name.lower() in f"{song.artist} {song.title}".lower():
                matched.append(song)
        
        if not matched:
            return f"未找到包含 '{song_name}' 的歌曲"
        
        if len(matched) > 1:
            songs_list = "\n".join([f"  {i+1}. {s.artist} - {s.title}" for i, s in enumerate(matched[:10])])
            return f"找到多首匹配歌曲，请输入序号选择：\n{songs_list}\n\n或直接说：检测 BTS - Dynamite 语言"
        
        song = matched[0]
        
        print(f"🔍 检测歌曲语言: {song.artist} - {song.title}")
        print("-" * 50)
        
        # 1. 快速检测（文本分析）
        print("\n[1/3] 快速检测（歌手名+网易云API）...")
        lang, source, conf = detect_language(song.title, song.artist, song.file_path)
        print(f"  结果: {lang} (来源: {source}, 置信度: {conf:.2f})")
        
        # 2. 音频检测（Whisper）
        print("\n[2/3] 音频检测（分析歌曲内容）...")
        audio_lang, audio_conf = detect_audio_language(song.file_path)
        if audio_lang:
            print(f"  结果: {audio_lang} (置信度: {audio_conf:.2f})")
        else:
            print("  音频检测失败")
        
        # 3. 综合结论
        print("\n[3/3] 综合判断...")
        print("-" * 50)
        
        # 确定最终语言（优先音频识别，更准）
        final_lang = audio_lang if audio_lang and audio_conf > conf else lang
        final_conf = max(audio_conf if audio_lang else 0, conf)
        
        # 保存到数据库（自动）
        from core.language_detector import detector
        detector.manual_set(song.artist, song.title, final_lang)
        
        # 如果两种方法一致
        if audio_lang and lang == audio_lang:
            return f"""
🎵 {song.artist} - {song.title}

✅ 检测结果: **{lang}**

📊 分析详情:
  • 文本分析: {lang} ({conf:.0%})
  • 音频识别: {audio_lang} ({audio_conf:.0%})

💾 已自动保存到语言数据库！

💡 可用命令:
  • 导出语言 - 生成可编辑文档
  • 有哪些{lang}歌 - 查询同类歌曲
  • 标记 {song.artist} - {song.title} 为 日语 - 如需纠正
"""
        
        # 如果不一致，提示用户
        return f"""
🎵 {song.artist} - {song.title}

⚠️ 检测结果不一致（已保存为: {final_lang}）:

📊 分析详情:
  • 文本分析: {lang} ({conf:.0%})
  • 音频识别: {audio_lang or '失败'} ({audio_conf:.0%} if audio_lang else 0)

💾 已自动保存到语言数据库！

🤔 建议:
  • 当前以{audio_lang or lang}为准（保存在数据库中）
  • 如需纠正: 标记 {song.artist} - {song.title} 为 正确语言
  • 导出语言 - 批量查看和编辑所有结果
"""
    
    def handle_export_library(self, params: Dict) -> str:
        """导出完整音乐库文档"""
        from core.music_library_db import get_library_db
        
        if not self.librarian.songs:
            return "请先扫描音乐库"
        
        print("正在生成音乐库文档...")
        
        # 先更新所有歌曲到数据库
        lib_db = get_library_db()
        for song in self.librarian.songs.values():
            # 如果数据库中没有，添加基础信息
            if not lib_db.get_record(song.artist, song.title):
                lib_db.update_or_create(
                    file_path=song.file_path,
                    title=song.title,
                    artist=song.artist,
                    album=song.album,
                    genre=song.genre,
                    year=str(song.year) if song.year else "",
                    duration=str(song.duration) if song.duration else ""
                )
        
        # 导出CSV
        csv_path = lib_db.export_to_csv()
        
        if not csv_path:
            return "导出失败，请检查日志"
        
        stats = lib_db.get_stats()
        
        return f"""
✅ 音乐库文档已生成！

📁 文件位置: {csv_path}

📊 音乐库概况:
  • 总歌曲: {stats['total']} 首
  • 已识别语言: {len(stats['languages'])} 种
  • 有歌词: {stats['lyrics_count']} 首

📝 可编辑字段:
  • 语言（英语/国语/粤语/日语/韩语）
  • 情绪（快乐/悲伤/平静等）
  • 用户备注（自由填写）
  • 播放次数

💡 使用方法:
  1. 用Excel打开 CSV 文件
  2. 修改想调整的字段
  3. 保存后输入: 导入文档
  4. 或者直接输入: 导入音乐库

📌 文档会自动更新，每次扫描后都可用 导出文档 获取最新版本
"""
    
    def handle_import_library(self, params: Dict) -> str:
        """导入音乐库文档"""
        from core.music_library_db import get_library_db
        
        lib_db = get_library_db()
        updated = lib_db.import_from_csv()
        
        if updated > 0:
            return f"""
✅ 成功导入 {updated} 条修改！

📊 更新后的音乐库:
  • 总记录: {len(lib_db.records)} 首

💡 现在可以用以下命令查询:
  • 有哪些韩语歌
  • 有哪些快乐的歌
  • 导出文档 - 查看完整表格
"""
        else:
            return """
⚠️ 没有需要导入的修改

💡 请先用Excel编辑导出的文档，再执行导入
步骤:
  1. 导出文档
  2. Excel编辑
  3. 保存CSV
  4. 导入文档
"""
    
    def handle_show_library_stats(self, params: Dict) -> str:
        """显示音乐库完整统计"""
        from core.music_library_db import get_library_db
        
        if not self.librarian.songs:
            return "请先扫描音乐库"
        
        lib_db = get_library_db()
        stats = lib_db.get_stats()
        
        lines = [
            "📊 音乐库完整统计",
            "=" * 50,
            f"总歌曲: {stats['total']} 首",
            "",
            "🌍 语言分布:"
        ]
        
        for lang, count in list(stats['languages'].items())[:8]:
            bar = "█" * (count * 30 // stats['total'] if stats['total'] > 0 else 0)
            lines.append(f"  {lang:8} | {bar:30} | {count}首")
        
        if len(stats['languages']) > 8:
            lines.append(f"  ... 还有 {len(stats['languages']) - 8} 种语言")
        
        lines.extend([
            "",
            "🎭 情绪分布:",
        ])
        
        for emotion, count in list(stats['emotions'].items())[:5]:
            lines.append(f"  {emotion}: {count}首")
        
        lines.extend([
            "",
            f"🎵 有歌词: {stats['lyrics_count']} 首",
            "",
            "💡 操作命令:",
            "  导出文档 - 生成完整Excel表格",
            "  有哪些韩语歌 - 按语言查询",
            "  音频检测语言 - 用AI听歌识语言"
        ])
        
        return "\n".join(lines)
    
    def handle_detect_language_by_audio(self, params: Dict) -> str:
        """只用音频检测语言（Whisper）"""
        from core.audio_language_detector import AudioLanguageDetector
        
        if not self.librarian.songs:
            return "请先扫描音乐库"
        
        total = len(self.librarian.songs)
        print(f"🎵 开始音频语言检测（只用Whisper分析歌曲内容）")
        print(f"   共 {total} 首歌曲，预计需要 {total * 5 // 60} 分钟...")
        print(f"   ⚠️  此过程较慢，但准确度最高！\n")
        
        detector = AudioLanguageDetector()
        results = {}
        
        for i, song in enumerate(self.librarian.songs.values(), 1):
            print(f"[{i}/{total}] {song.artist} - {song.title}")
            lang, conf = detector.detect(song.file_path)
            if lang:
                results[lang] = results.get(lang, 0) + 1
                print(f"      → {lang} ({conf:.2f})")
            
            # 每10首显示进度
            if i % 10 == 0:
                print(f"\n  进度: {i}/{total} ({i*100//total}%)\n")
        
        # 显示结果
        lines = ["\n📊 音频检测结果", "=" * 40]
        for lang, count in sorted(results.items(), key=lambda x: -x[1]):
            lines.append(f"  {lang}: {count}首")
        lines.append("=" * 40)
        lines.append(f"总计: {sum(results.values())} 首")
        lines.append("")
        lines.append("✅ 检测结果已缓存到 data/audio_language_cache.json")
        lines.append("💡 现在可以用 '有哪些韩语歌' 查询了")
        
        return "\n".join(lines)
    
    def handle_export_language_csv(self, params: Dict) -> str:
        """导出语言到CSV"""
        from core.language_detector import detector
        import csv
        from datetime import datetime
        
        if not self.librarian.songs:
            return "请先扫描音乐库"
        
        # 确保所有歌曲都有检测结果
        for song in self.librarian.songs.values():
            detector.detect(song.title, song.artist, song.file_path)
        
        # 导出CSV
        csv_path = Path("data/songs_language.csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['artist', 'title', 'language', 'source', 'confidence', 'notes'])
            for key, item in detector.cache.items():
                writer.writerow([
                    item['artist'], item['title'], item['language'],
                    item['source'], item['confidence'], ''
                ])
        
        return f"""
✅ 已导出到: {csv_path}

📊 {len(detector.cache)} 首歌曲

📝 编辑方法:
1. 用Excel打开
2. 修改 language 列
3. 保存后对我说：导入语言

💡 或者直接说:
   标记 BTS - Dynamite 为 韩语
"""
    
    def handle_correct_language(self, params: Dict) -> str:
        """纠正语言"""
        from core.language_detector import detector
        import re
        
        text = params.get("input", "")
        
        # 匹配: "标记 BTS - Dynamite 为 韩语"
        match = re.search(r"(?:标记|纠正|设置语言)\s+(.+?)\s+(?:为|是|=)\s*(\S+)", text)
        if not match:
            return """格式错误！请使用:
  标记 BTS - Dynamite 为 韩语
  纠正 IU - Blueming 为 韩语"""
        
        song_info = match.group(1).strip()
        language = match.group(2).strip()
        
        # 解析
        if " - " in song_info:
            artist, title = song_info.rsplit(" - ", 1)
        else:
            return "格式错误！请使用 '艺术家 - 标题' 格式"
        
        detector.manual_set(artist.strip(), title.strip(), language)
        return f"✅ 已设置: {artist} - {title} = {language}"
    
    def handle_update_song_info(self, params: Dict) -> str:
        """自然语言方式更新歌曲信息（如'supernatural是韩语歌'、'kanye west的歌全都是英文的'）"""
        from core.music_library_db import get_library_db
        from core.language_detector import detector
        
        song_hint = params.get("song_hint", "")
        field = params.get("field", "")
        value = params.get("value", "")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 保存原始 hint 用于判断批量意图
        original_hint = song_hint
        
        # 清理批量词后缀（如 "kanye west的歌全都" → "kanye west"）
        batch_suffixes = ["的歌全都", "的歌全部", "的歌所有", "的都", "的歌", "全都", "全部", "所有"]
        has_batch_suffix = False
        for suffix in batch_suffixes:
            if song_hint.endswith(suffix):
                song_hint = song_hint[:-len(suffix)].strip()
                has_batch_suffix = True
                break
        
        # 查找匹配的歌曲
        matched_songs = []
        hint_lower = song_hint.lower()
        
        for song in self.librarian.songs.values():
            # 匹配标题或文件名
            title_match = hint_lower in song.title.lower()
            file_match = hint_lower in Path(song.file_path).stem.lower()
            # 也尝试匹配 歌手 - 歌名 格式
            full_match = hint_lower in f"{song.artist} - {song.title}".lower()
            
            if title_match or file_match or full_match:
                matched_songs.append(song)
        
        # 如果没找到，尝试用 hint 作为 artist 名模糊匹配
        if not matched_songs:
            artist_matched = []
            for song in self.librarian.songs.values():
                if song_hint.lower() in song.artist.lower() or song.artist.lower() in song_hint.lower():
                    artist_matched.append(song)
            if artist_matched:
                matched_songs = artist_matched
                has_batch_suffix = True  # 按 artist 匹配视为批量意图
            else:
                return f"❌ 未找到包含 '{original_hint}' 的歌曲\n\n提示：你可以说 '标记 歌手 - 歌名 为 {value}' 来精确指定"
        
        # 判断是否批量：有批量后缀，或所有匹配歌曲属于同一歌手且数量较多
        same_artist = len(set(s.artist for s in matched_songs)) == 1
        is_batch = has_batch_suffix or (same_artist and len(matched_songs) > 1)
        
        if len(matched_songs) > 1 and not is_batch:
            # 多首不同歌手，显示列表
            songs_list = "\n".join([f"  {i+1}. {s.artist} - {s.title}" for i, s in enumerate(matched_songs[:10])])
            return f"找到多首匹配歌曲：\n{songs_list}\n\n请使用更精确的歌名，或者说：\n标记 歌手 - 歌名 为 {value}"
        
        song = matched_songs[0]
        lib_db = get_library_db()
        
        # 标准化值
        if field == "language":
            # 统一语言名称
            lang_map = {
                "韩文": "韩语", "韩": "韩语", "korean": "韩语", "kr": "韩语",
                "日文": "日语", "日": "日语", "japanese": "日语", "jp": "日语",
                "英文": "英语", "英": "英语", "english": "英语", "en": "英语",
                "中文": "国语", "普通话": "国语", "国语": "国语", "mandarin": "国语",
                "粤语": "粤语", "广东话": "粤语", "cantonese": "粤语",
            }
            normalized_value = lang_map.get(value.lower(), value)
            
            # 批量更新模式
            if is_batch and len(matched_songs) > 1:
                updated = 0
                artist_name = matched_songs[0].artist
                for s in matched_songs:
                    detector.manual_set(s.artist, s.title, normalized_value)
                    lib_db.update_language(s.artist, s.title, normalized_value, 'manual')
                    updated += 1
                return f"✅ 已批量设置 {artist_name} 的 {updated} 首歌曲为 {normalized_value}"
            
            # 单首更新
            detector.manual_set(song.artist, song.title, normalized_value)
            
            # 更新音乐库数据库（SQLite 即时写入）
            lib_db.update_language(song.artist, song.title, normalized_value, 'manual')
            
            return f"✅ 已设置语言: {song.artist} - {song.title} = {normalized_value}"
        
        elif field == "emotion":
            # 标准化情绪名称
            emotion_map = {
                "快乐": "happy", "开心": "happy", "欢快": "happy",
                "悲伤": "sad", "难过": "sad", "治愈": "sad", "安静": "sad", "抒情": "sad",
                "热血": "energetic", "激情": "energetic", "燃": "energetic",
                "平静": "calm", "放松": "calm", "舒缓": "calm",
                "浪漫": "romantic", "甜蜜": "romantic",
                "怀旧": "nostalgic", "经典": "nostalgic",
                "愤怒": "angry", "发泄": "angry",
                "专注": "focus", "工作": "focus",
                "派对": "party", "舞曲": "party",
            }
            normalized_value = emotion_map.get(value, value)
            
            # 更新音乐库数据库（SQLite 即时写入）
            lib_db.update_emotion(song.artist, song.title, normalized_value, '1.0')
            
            emotion_names = {
                'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
                'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
                'angry': '愤怒', 'focus': '专注', 'party': '派对'
            }
            display_emotion = emotion_names.get(normalized_value, normalized_value)
            
            return f"✅ 已设置情绪: {song.artist} - {song.title} = {display_emotion}"
        
        return f"❌ 未知字段: {field}"
    
    def _clean_play_name(self, name: str) -> str:
        """清洗歌名：去除书名号、歌手名后缀/前缀、通用后缀如'的歌'"""
        import re
        name = name.strip()
        # 去除书名号《》
        if name.startswith("《") and name.endswith("》"):
            name = name[1:-1]
        # 去除尾部 " - 歌手名" 如 "程艾影 - 赵雷"
        name = re.sub(r'\s*[-–—]\s*\S+\s*$', '', name)
        # 去除头部 "歌手名 - " 如 "赵雷 - 程艾影"
        name = re.sub(r'^\S+\s*[-–—]\s*', '', name)
        # 去除通用后缀："的歌"、"这首歌"、"的歌曲"
        for suffix in ["的歌曲", "这首歌", "的歌"]:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        return name.strip()
    
    def handle_play_by_name(self, params: Dict) -> str:
        """通过歌名播放歌曲"""
        raw_name = params.get("song_name", "")
        if not raw_name:
            return "请告诉我歌曲名称"
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 清洗歌名（去除书名号、歌手名后缀等）
        song_name = self._clean_play_name(raw_name)
        
        # 查找匹配的歌曲（三级递进）
        matched_songs = []
        
        # L1: 精确子串匹配
        for song in self.librarian.songs.values():
            if song_name.lower() in song.title.lower() or \
               song_name.lower() in f"{song.artist} - {song.title}".lower():
                matched_songs.append(song)
        
        # L2: 模糊匹配（L1 无结果时，容错同音字/形近字）
        if not matched_songs and len(song_name) >= 2:
            from difflib import SequenceMatcher
            best_matches = []
            for song in self.librarian.songs.values():
                title_sim = SequenceMatcher(None, song_name.lower(), song.title.lower()).ratio()
                full_sim = SequenceMatcher(None, song_name.lower(), f"{song.artist} {song.title}".lower()).ratio()
                max_sim = max(title_sim, full_sim)
                if max_sim >= 0.6:
                    best_matches.append((max_sim, song))
            
            if best_matches:
                best_matches.sort(key=lambda x: x[0], reverse=True)
                matched_songs = [s for _, s in best_matches[:5]]
        
        # L3: 降级处理（处理 "播放xxx的歌" 被误识别为 play_by_name 的情况）
        if not matched_songs:
            # 检测是否包含情绪关键词，直接转 playlist
            emotion_keywords = {
                '开心': 'happy', '快乐': 'happy', '悲伤': 'sad', '难过': 'sad',
                '安静': 'calm', '平静': 'calm', '浪漫': 'romantic', '激情': 'energetic',
                '燃': 'energetic', '热血': 'energetic', '怀旧': 'nostalgic', '经典': 'nostalgic',
                '愤怒': 'angry', '专注': 'focus', '工作': 'focus', '派对': 'party', '嗨': 'party',
            }
            detected_emotion = None
            for kw, emo in emotion_keywords.items():
                if kw in raw_name:
                    detected_emotion = emo
                    break
            
            if detected_emotion:
                return self.handle_playlist({"mode": "emotion", "emotion": detected_emotion})
            
            # 否则降级为 query 搜索
            query_results = self.librarian.query(raw_name, top_k=5)
            if query_results:
                self.context.set_query_results(query_results)
                lines = [f"  {i}. 《{r['song'].title}》- {r['song'].artist}" for i, r in enumerate(query_results, 1)]
                return f"找到 {len(query_results)} 首相关歌曲（输入序号或'第一首'选择）：\n" + "\n".join(lines)
            return f"未找到包含 '{raw_name}' 的歌曲"
        
        if len(matched_songs) == 1:
            song = matched_songs[0]
            return self._play_song(song)
        else:
            # 多首匹配，显示列表让用户选择
            songs_text = "\n".join([f"{i+1}. {s.artist} - {s.title}" for i, s in enumerate(matched_songs[:10])])
            self.context.last_query_results = [{"song": s} for s in matched_songs]
            return f"找到 {len(matched_songs)} 首相关歌曲，请输入序号播放：\n{songs_text}"
    
    def _play_song(self, song) -> str:
        """播放指定歌曲"""
        foobar_result = self._play_with_foobar2000(song.file_path)
        
        if foobar_result:
            return f"🎵 正在播放: {song.artist} - {song.title}\n{foobar_result}"
        else:
            return f"🎵 {song.artist} - {song.title}\n文件: {song.file_path}\n\n💡 未找到 foobar2000，请手动播放或配置播放器路径"
    
    def handle_play(self, params: Dict) -> str:
        item = params.get("item", {})
        song = item.get('song', item)
        return self._play_song(song)
    
    def _play_with_foobar2000(self, file_path: str) -> Optional[str]:
        """调用 foobar2000 播放指定文件"""
        # 常见安装路径
        foobar_paths = [
            r"C:\Program Files\foobar2000\foobar2000.exe",
            r"C:\Program Files (x86)\foobar2000\foobar2000.exe",
            shutil.which("foobar2000"),  # PATH 中
        ]
        
        foobar_exe = None
        for path in foobar_paths:
            if path and os.path.exists(path):
                foobar_exe = path
                break
        
        if not foobar_exe:
            return None
        
        try:
            # /immediate - 立即播放，如果 foobar2000 未运行会启动它
            subprocess.Popen(
                [foobar_exe, "/immediate", file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False
            )
            return f"📱 已通过 foobar2000 播放"
        except Exception as e:
            return f"⚠️ 调用播放器失败: {e}"
    
    def handle_info(self, params: Dict) -> str:
        item = params.get("item", {})
        song = item.get('song', item)
        return f"""📀 {song.title}
👤 艺术家: {song.artist}
💿 专辑: {song.album or '未知'}
🎵 流派: {song.genre or '未知'}
📅 年份: {song.year or '未知'}
📁 文件: {song.file_path}"""
    
    def handle_cancel(self, params: Dict) -> str:
        if self.context.pending_action:
            desc = self.context.pending_action.description
            self.context.clear_pending()
            return f"已取消: {desc}"
        return "没有待执行的操作。"
    
    def handle_clear(self, params: Dict) -> str:
        count = len(self.context.messages)
        self.context.clear()
        return f"会话已重置（清除了 {count} 条消息）。"
    
    def handle_analyze_single_emotion(self, params: Dict) -> str:
        """分析单首歌曲的情绪"""
        from core.lyrics_fetcher import LyricsFetcher
        
        song_name = params.get("song_name", "")
        
        # 处理指代词："第x首"、"这首歌"、"它" —— 从上次查询结果中解析
        target_song = None
        if song_name in ["这首歌", "它", "这首", "当前播放的歌", "刚才那首"] or \
           (song_name and song_name.startswith("第") and "首" in song_name):
            if self.context.last_query_results:
                idx = self._parse_multi_select(song_name, len(self.context.last_query_results))
                if idx and len(idx) == 1:
                    # _parse_multi_select 返回的是 0-based 索引，直接使用
                    target_song = self.context.last_query_results[idx[0]].get("song")
                elif not idx and self.context.last_query_results:
                    target_song = self.context.last_query_results[0].get("song")
        
        # 如果没有通过指代词解析到歌曲，正常搜索
        if not target_song:
            if not song_name:
                return "请告诉我歌曲名称（如「分析晴天的情绪」）"
            
            if not self.librarian.songs:
                self.librarian.run("scan")
            
            # 查找匹配的歌曲
            matched_songs = []
            for song in self.librarian.songs.values():
                if song_name.lower() in song.title.lower() or \
                   song_name.lower() in f"{song.artist} - {song.title}".lower():
                    matched_songs.append(song)
            
            if not matched_songs:
                return f"未找到包含 '{song_name}' 的歌曲"
            
            target_song = matched_songs[0]
        
        song = target_song
        
        try:
            from core.emotion_analyzer_simple import SimpleEmotionAnalyzer as AudioEmotionAnalyzer
        except ImportError:
            return "情绪分析模块加载失败"
        
        # 传入Kimi客户端以启用LLM歌词分析
        analyzer = AudioEmotionAnalyzer(kimi_client=self.kimi)
        fetcher = LyricsFetcher(lyrics_dir="data/lyrics")
        
        # 获取歌词（先检查本地，再尝试网易云）
        lyrics = fetcher._from_lyrics_dir(song.title, song.artist)
        if not lyrics:
            # 尝试从网易云获取
            lyrics = fetcher.fetch(song.title, song.artist, song.file_path)
        
        if not lyrics:
            return f"《{song.title}》暂无歌词，无法分析情绪\n建议：先运行「下载歌词」或「识别歌词」"
        
        # 分析情绪（强制重新分析，显示详细日志）
        print(f"正在分析《{song.title}》的情绪...")
        print(f"  歌词长度: {len(lyrics)}字符")
        print(f"  歌词前100字: {lyrics[:100].replace(chr(10), ' ')}...")
        
        # 清除这首歌曲的缓存，强制重新分析
        cache_key = analyzer._get_file_hash(song.file_path)
        if cache_key in analyzer._cache:
            del analyzer._cache[cache_key]
            print(f"  已清除旧缓存，重新分析...")
        
        result = analyzer.analyze(song.file_path, lyrics=lyrics, title=song.title, artist=song.artist, verbose=True)
        
        if not result:
            return f"《{song.title}》情绪分析失败"
        
        emotion = result.emotion if hasattr(result, 'emotion') else result.get("emotion", "unknown")
        confidence = result.confidence if hasattr(result, 'confidence') else result.get("confidence", 0)
        
        # 置信度转换：如果是小数(0-1)转为百分比
        if confidence < 1:
            confidence_pct = int(confidence * 100)
        else:
            confidence_pct = int(confidence)
        
        emotion_names = {
            'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
            'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
            'angry': '愤怒', 'focus': '专注', 'party': '派对'
        }
        emotion_cn = emotion_names.get(emotion, emotion)
        
        return f"""
🎵 《{song.title}》 - {song.artist}

💭 情绪分析结果: **{emotion_cn}**
📊 置信度: {confidence_pct}%

"""
    
    def handle_analyze_emotion(self, params: Dict) -> str:
        """分析音乐库情绪（集成到聊天界面）"""
        try:
            from core.emotion_analyzer_simple import SimpleEmotionAnalyzer as AudioEmotionAnalyzer
        except ImportError:
            return "情绪分析模块加载失败"
        
        from core.lyrics_fetcher import LyricsFetcher
        import os
        
        # 检查是否强制重新分析
        force_reanalyze = params.get("force", False)
        cache_file = Path("data/emotion_cache.json")
        
        if force_reanalyze and cache_file.exists():
            print("🗑️  清除历史情绪缓存...")
            os.remove(cache_file)
            print("✅ 缓存已清除，将重新分析所有歌曲")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        total = len(self.librarian.songs)
        if total == 0:
            return "音乐库为空"
        
        print(f"[1/3] 准备分析 {total} 首歌曲...")
        
        # 初始化（使用专用歌词目录）
        analyzer = AudioEmotionAnalyzer(kimi_client=self.kimi)
        lyrics_fetcher = LyricsFetcher(lyrics_dir="data/lyrics")
        
        # 准备歌曲数据
        songs_data = []
        for song in self.librarian.songs.values():
            songs_data.append({
                'file_path': song.file_path,
                'title': song.title,
                'artist': song.artist,
                'lyrics': None
            })
        
        total_songs = len(songs_data)
        print(f"[2/3] 正在获取 {total_songs} 首歌曲的歌词...")
        print("      (检查: data/lyrics/ 目录 → 网易云API → 缓存)")
        
        # 获取歌词（分批处理，每批50首）
        batch_size = 50
        lyrics_results = {}
        
        for i in range(0, total_songs, batch_size):
            batch = songs_data[i:i+batch_size]
            batch_lyrics = lyrics_fetcher.batch_fetch(batch)
            lyrics_results.update(batch_lyrics)
            
            if (i + batch_size) % 50 == 0 or (i + batch_size) >= total_songs:
                print(f"      歌词进度: {min(i+batch_size, total_songs)}/{total_songs}")
        
        for song in songs_data:
            if song['file_path'] in lyrics_results:
                song['lyrics'] = lyrics_results[song['file_path']]
        
        lyrics_count = len(lyrics_results)
        print(f"      获取到 {lyrics_count} 首歌词 ({lyrics_count/total_songs*100:.1f}%)")
        
        # 分析情绪
        print(f"[3/3] 正在分析 {total_songs} 首歌曲的情绪...")
        print("      (显示前3首详细分析过程)")
        emotion_stats = {}
        analyzed = 0
        
        for i, song in enumerate(songs_data):
            try:
                # 前3首显示详细日志
                verbose = (i < 3)
                if verbose:
                    print(f"\n  --- 歌曲 {i+1}: {song['title']} ---")
                
                result = analyzer.analyze(
                    song['file_path'],
                    song['lyrics'],
                    song['title'],
                    song['artist'],
                    verbose=verbose
                )
                emotion_stats[result.emotion] = emotion_stats.get(result.emotion, 0) + 1
                analyzed += 1
                
                if analyzed % 50 == 0:
                    print(f"      情绪分析进度: {analyzed}/{total_songs}")
            except Exception as e:
                print(f"      [错误] {song.get('title', '')}: {e}")
        
        print("\n  --- 详细日志结束 ---\n")
        
        # 显示统计
        lines = [f"\n📊 情绪分布统计（共{analyzed}首）", "=" * 40]
        emotion_names = {
            'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
            'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
            'angry': '愤怒', 'focus': '专注', 'party': '派对'
        }
        
        for emotion, count in sorted(emotion_stats.items(), key=lambda x: -x[1]):
            name = emotion_names.get(emotion, emotion)
            bar = "█" * (count * 20 // analyzed if analyzed > 0 else 0)
            lines.append(f"  {name:6} | {bar:20} | {count}首")
        
        lines.append("=" * 40)
        
        # 显示歌词覆盖情况
        no_lyrics = analyzed - lyrics_count
        if no_lyrics > 0:
            lines.append(f"\n💡 其中 {lyrics_count}首有歌词，{no_lyrics}首无歌词")
            lines.append("   无歌词歌曲：依赖音频+歌名推断（可能不够准）")
            lines.append("   改善方法：放置.lrc歌词文件到歌曲目录")
        
        lines.append(f"\n✅ 已分析 {analyzed} 首歌曲并缓存")
        lines.append("现在可以创建情绪播放列表了！")
        
        return "\n".join(lines)
    
    def handle_download_lyrics(self, params: Dict) -> str:
        """批量下载歌词文件到专用目录 (data/lyrics/)"""
        from core.lyrics_fetcher import LyricsFetcher
        from pathlib import Path
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        total = len(self.librarian.songs)
        if total == 0:
            return "音乐库为空"
        
        print(f"准备为 {total} 首歌曲下载歌词...")
        print("歌词将保存到: data/lyrics/")
        print("(使用网易云API，可能需要几分钟)\n")
        
        fetcher = LyricsFetcher(lyrics_dir="data/lyrics")
        
        # 准备歌曲列表
        songs_data = []
        for song in self.librarian.songs.values():
            songs_data.append({
                'file_path': song.file_path,
                'title': song.title,
                'artist': song.artist
            })
        
        # 批量获取歌词
        downloaded = 0
        failed = 0
        skipped = 0
        
        for i, song in enumerate(songs_data, 1):
            file_path = song['file_path']
            title = song['title']
            artist = song['artist']
            
            # 检查专用歌词目录是否已有
            if fetcher._from_lyrics_dir(title, artist):
                skipped += 1
                continue
            
            # 获取歌词
            try:
                lyrics = fetcher.fetch(title, artist, file_path)
                if lyrics:
                    # 保存到专用歌词目录
                    if fetcher.save_to_lyrics_dir(title, artist, lyrics):
                        downloaded += 1
                        print(f"✓ {title} - {artist}")
                    else:
                        failed += 1
                        print(f"✗ {title} - 保存失败")
                else:
                    failed += 1
                    print(f"✗ {title} - 未找到歌词")
            except Exception as e:
                failed += 1
                print(f"✗ {title} - 错误: {e}")
            
            if i % 20 == 0:
                print(f"\n进度: {i}/{total} (成功:{downloaded} 失败:{failed} 跳过:{skipped})\n")
        
        return f"""歌词下载完成！

📊 统计：
• 总歌曲: {total} 首
• 下载成功: {downloaded} 首
• 已存在跳过: {skipped} 首  
• 未找到: {failed} 首

💾 歌词文件 (.lrc) 保存位置: data/lyrics/
✅ 下次情绪分析将自动使用这些歌词，无需重新下载
💡 可用 foobar2000 等播放器显示歌词（需配置歌词路径）
"""
    
    def _recognize_single_song(self, song, generator, fetcher) -> str:
        """识别单首歌曲的歌词"""
        from core.lyrics_generator import LyricsGenerator
        
        print(f"\n🎵 识别歌曲: {song.artist} - {song.title}")
        print("🤖 使用模型: Whisper large (约1.5GB，准确率最高)")
        print("📄 输出格式: 标准LRC (带精确时间戳)")
        print("⏳ 识别中，请稍候...\n")
        
        try:
            lyrics = generator.generate(song.file_path, method="whisper")
            if lyrics:
                # 保存
                if generator.save_lyrics(song.file_path, lyrics):
                    # 显示前10行
                    preview_lines = lyrics.split('\n')[:12]
                    preview = '\n'.join(preview_lines)
                    return f"""
🎤 AI歌词识别成功！

📍 歌曲: {song.artist} - {song.title}
💾 保存路径: data/lyrics/{song.artist} - {song.title}.lrc

📝 歌词预览:
```
{preview}
...
```
"""
                else:
                    return "识别成功但保存失败"
            else:
                return "❌ 识别失败（可能是纯音乐或音频不清晰）"
        except Exception as e:
            return f"❌ 识别错误: {e}"

    def handle_generate_lyrics_whisper(self, params: Dict) -> str:
        """使用Whisper AI识别未找到歌词的歌曲"""
        from core.lyrics_generator import LyricsGenerator, install_whisper_hint
        from core.lyrics_fetcher import LyricsFetcher
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        total = len(self.librarian.songs)
        if total == 0:
            return "音乐库为空"
        
        # 初始化生成器
        generator = LyricsGenerator()
        fetcher = LyricsFetcher(lyrics_dir="data/lyrics")
        
        if not generator.whisper_available:
            install_whisper_hint()
            return "请先安装Whisper: pip install openai-whisper"
        
        # 检查是否指定了特定歌曲
        target_song_name = params.get("song_name", "")
        if target_song_name:
            # 查找匹配的歌曲
            matched_songs = []
            for song in self.librarian.songs.values():
                if target_song_name.lower() in song.title.lower() or \
                   target_song_name.lower() in f"{song.artist} - {song.title}".lower():
                    matched_songs.append(song)
            
            if matched_songs:
                print(f"找到 {len(matched_songs)} 首匹配歌曲")
                # 只处理第一首匹配的
                song = matched_songs[0]
                return self._recognize_single_song(song, generator, fetcher)
            else:
                return f"未找到包含 '{target_song_name}' 的歌曲"
        
        # 找出没有歌词的歌曲
        print("正在检查哪些歌曲需要识别歌词...")
        songs_without_lyrics = []
        
        for song in self.librarian.songs.values():
            # 检查专用歌词目录
            if not fetcher._from_lyrics_dir(song.title, song.artist):
                # 检查网易云是否有
                if not fetcher.fetch(song.title, song.artist, song.file_path):
                    songs_without_lyrics.append({
                        'file_path': song.file_path,
                        'title': song.title,
                        'artist': song.artist
                    })
        
        if not songs_without_lyrics:
            return "所有歌曲都已有歌词！"
        
        print(f"\n找到 {len(songs_without_lyrics)} 首没有歌词的歌曲")
        print("将使用AI语音识别生成歌词...")
        print("🤖 使用模型: Whisper large (约1.5GB，准确率最高)")
        print("📄 输出格式: 标准LRC (带精确时间戳)")
        print("⚠️ 注意：首次使用需下载模型，识别速度较慢\n")
        
        # 限制数量（避免太长）
        to_process = songs_without_lyrics[:20]  # 最多处理20首
        
        recognized = 0
        failed = 0
        
        for i, song in enumerate(to_process, 1):
            print(f"\n[{i}/{len(to_process)}] 识别: {song['title']} - {song['artist']}")
            
            try:
                lyrics = generator.generate(song['file_path'], method="whisper")
                if lyrics:
                    # 保存
                    if generator.save_lyrics(song['file_path'], lyrics):
                        recognized += 1
                        print(f"  ✓ 识别成功，保存到 data/lyrics/")
                    else:
                        failed += 1
                        print(f"  ✗ 保存失败")
                else:
                    failed += 1
                    print(f"  ✗ 识别失败（可能是纯音乐或无法识别）")
            except Exception as e:
                failed += 1
                print(f"  ✗ 错误: {e}")
        
        return f"""
🎤 AI歌词识别完成！

📊 统计：
• 需要识别的歌曲: {len(songs_without_lyrics)} 首
• 本次处理: {len(to_process)} 首（限制20首）
• 识别成功: {recognized} 首
• 识别失败: {failed} 首

💡 识别的歌词已保存到 data/lyrics/
💡 建议检查识别结果，AI可能有错误
💡 剩余 {len(songs_without_lyrics) - len(to_process)} 首可再次运行此命令

使用方法:
    1. 安装Whisper: pip install openai-whisper
    2. 确保已安装ffmpeg
    3. 重新运行"识别歌词"
"""
    
    def handle_query_emotion_songs(self, params: Dict) -> str:
        """查询本地库中特定情绪的歌曲"""
        emotion = params.get("emotion", "happy")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 加载情绪分析器
        try:
            from core.emotion_analyzer_simple import SimpleEmotionAnalyzer as AudioEmotionAnalyzer
        except ImportError:
            return "情绪分析模块加载失败"
        
        analyzer = AudioEmotionAnalyzer()
        
        # 查找缓存中该情绪的歌曲
        emotion_names = {
            'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
            'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
            'angry': '愤怒', 'focus': '专注', 'party': '派对'
        }
        emotion_name = emotion_names.get(emotion, emotion)
        
        matching_songs = []
        
        for song in self.librarian.songs.values():
            cache_key = analyzer._get_file_hash(song.file_path)
            if cache_key in analyzer._cache:
                cached = analyzer._cache[cache_key]
                if cached.get('emotion') == emotion:
                    matching_songs.append({
                        'title': song.title or Path(song.file_path).stem,
                        'artist': song.artist or 'Unknown',
                        'confidence': cached.get('confidence', 0)
                    })
        
        if not matching_songs:
            return f"暂无标记为「{emotion_name}」的歌曲。\n请先运行「分析情绪」来分析你的音乐库。"
        
        # 按置信度排序
        matching_songs.sort(key=lambda x: x['confidence'], reverse=True)
        
        # 显示结果
        lines = [f"🎵 你的音乐库中有 {len(matching_songs)} 首「{emotion_name}」的歌曲：", ""]
        
        for i, song in enumerate(matching_songs[:15], 1):  # 最多显示15首
            conf_emoji = "⭐" if song['confidence'] > 0.7 else ""
            lines.append(f"{i}. 《{song['title']}》- {song['artist']} {conf_emoji}")
        
        if len(matching_songs) > 15:
            lines.append(f"\n...还有 {len(matching_songs) - 15} 首")
        
        lines.append(f"\n💡 可以对我说「创建一个{emotion_name}的播放列表」生成foobar2000歌单")
        
        return "\n".join(lines)
    
    def handle_query_language_songs(self, params: Dict) -> str:
        """查询本地库中特定语言的歌曲"""
        language = params.get("language", "韩语")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 使用language_detector检测语言
        from core.language_detector import detector
        
        matching_songs = []
        
        for song in self.librarian.songs.values():
            lang, source, conf = detector.detect(song.title, song.artist, song.file_path)
            if lang == language:
                matching_songs.append({
                    'title': song.title or Path(song.file_path).stem,
                    'artist': song.artist or 'Unknown',
                    'source': source,
                    'confidence': conf
                })
        
        if not matching_songs:
            return f"暂无检测到「{language}」歌曲。"
        
        # 按置信度排序
        matching_songs.sort(key=lambda x: x['confidence'], reverse=True)
        
        # 显示结果
        lines = [f"🎵 你的音乐库中有 {len(matching_songs)} 首「{language}」歌曲：", ""]
        
        for i, song in enumerate(matching_songs[:20], 1):  # 最多显示20首
            conf_emoji = "⭐" if song['confidence'] > 0.8 else ""
            lines.append(f"{i}. 《{song['title']}》- {song['artist']} {conf_emoji}")
        
        if len(matching_songs) > 20:
            lines.append(f"\n...还有 {len(matching_songs) - 20} 首")
        
        lines.append(f"\n💡 提示：可以对我说「标记 歌手 - 歌名 为 英语」来纠正语言")
        
        return "\n".join(lines)
    
    def handle_playlist(self, params: Dict) -> str:
        """创建 foobar2000 格式的播放列表"""
        from core.playlist_manager import PlaylistGenerator
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        if not self.librarian.songs:
            return "音乐库为空，请先添加歌曲。"
        
        mode = params.get("mode", "shuffle")
        query = params.get("query", "")
        emotion = params.get("emotion", "")
        max_duration = params.get("max_duration", 0)
        max_songs = params.get("max_songs", 0)
        
        print(f"正在生成播放列表...")
        print(f"  模式: {mode}")
        if query:
            print(f"  描述: {query}")
        if emotion:
            emotion_names = {"happy": "快乐", "sad": "悲伤", "energetic": "激情", 
                           "calm": "平静", "romantic": "浪漫", "nostalgic": "怀旧",
                           "angry": "愤怒", "focus": "专注", "party": "派对"}
            print(f"  情绪: {emotion_names.get(emotion, emotion)}")
        if max_duration:
            print(f"  时长: {max_duration}分钟")
        
        try:
            # 初始化情绪分析器（自动选择完整版或轻量版）
            try:
                from core.emotion_analyzer import AudioEmotionAnalyzer
            except ImportError:
                from core.emotion_analyzer_simple import SimpleEmotionAnalyzer as AudioEmotionAnalyzer
            
            emotion_analyzer = AudioEmotionAnalyzer(kimi_client=self.kimi)
            generator = PlaylistGenerator(self.librarian, emotion_analyzer=emotion_analyzer)
            
            criteria = {
                "mode": mode,
                "query": query,
                "emotion": emotion,
                "max_duration": max_duration,
                "description": query if mode == "smart" else (f"情绪: {emotion}" if emotion else "智能生成")
            }
            
            playlist = generator.generate(criteria)
            
            # 应用数量限制
            if max_songs > 0 and len(playlist.songs) > max_songs:
                playlist.songs = playlist.songs[:max_songs]
                playlist.total_duration = sum(s.get('duration', 240) for s in playlist.songs)
            
            # 保存到播放列表目录
            playlist_dir = Path(self.config.get("library", {}).get("path", ".")) / "Playlists"
            filepath = playlist.save(str(playlist_dir), use_relative_path=True)
            
            # 计算时长显示
            total_min = int(playlist.total_duration / 60)
            hours = total_min // 60
            mins = total_min % 60
            duration_str = f"{hours}小时{mins}分钟" if hours > 0 else f"{mins}分钟"
            
            # 情绪模式特殊提示
            emotion_hint = ""
            if mode == "emotion":
                emotion_desc = {
                    "happy": "充满正能量的快乐歌曲",
                    "sad": "温柔治愈适合静静聆听",
                    "energetic": "燃向高能激发活力",
                    "calm": "平静舒缓放松身心",
                    "romantic": "浪漫甜蜜适合二人世界",
                    "nostalgic": "经典怀旧唤起回忆",
                    "angry": "激烈发泄释放情绪",
                    "focus": "专注工作学习背景",
                    "party": "嗨翻全场派对必备"
                }
                
                # 检查是否使用了真实的情绪分析
                analyzed_count = len([s for s in playlist.songs if 'emotion_confidence' in s])
                if analyzed_count >= 3:
                    method_hint = f"（基于{analyzed_count}首歌曲的音频+歌词分析）"
                else:
                    method_hint = "（基于语义搜索，建议运行情绪分析工具）"
                
                emotion_hint = f"\n🎭 情绪标签: {emotion_desc.get(emotion, emotion)} {method_hint}"
            
            # 自动调用 foobar2000 播放
            foobar_result = self._play_with_foobar2000(str(filepath))
            
            if foobar_result:
                play_hint = f"\n🎧 {foobar_result}"
            else:
                play_hint = f"""\n💡 使用说明：
1. 打开 foobar2000
2. File → Load Playlist
3. 选择此文件即可导入"""
            
            return f"""✅ 播放列表已创建！

📋 {playlist.name}
🎵 {len(playlist.songs)} 首歌曲
⏱️ 总时长: {duration_str}
💾 保存位置: {filepath}{emotion_hint}{play_hint}

提示：播放列表使用相对路径，只要保持文件夹结构不变，移动播放列表文件也能正常播放。
"""
        except Exception as e:
            return f"创建播放列表时出错: {e}"
    
    def handle_chat(self, params: Dict) -> str:
        chat_type = params.get("type", "general")
        content = params.get("content", "")
        
        if self.kimi:
            try:
                return self._generate_response(chat_type, content)
            except:
                pass
        return self._preset_response(chat_type, content)
    
    def _generate_response(self, chat_type: str, content: str) -> str:
        """使用Kimi生成回复"""
        system = """你是友好幽默的音乐助手Music Agent。特点：
1. 热爱音乐，了解各种风格
2. 像朋友一样轻松聊天
3. 回答简短自然，30-80字
4. 记住对话上下文，保持连贯
5. ⚠️ 重要：你不知道用户的音乐库里有什么歌，也绝不能编造任何具体数字（如"你有375首英语歌"）。如果用户询问具体统计，请引导用户使用正确的命令。"""
        
        context = self.context.get_context_text(4)
        pending = f"\n[待确认操作: {self.context.pending_action.description}]" if self.context.pending_action else ""
        
        prompt = f"""对话上下文：
{context}{pending}

用户说：{content}

请自然友好地回复（简短）："""
        
        return self.kimi.generate(prompt, system=system, temperature=0.8, max_tokens=150) or self._preset_response(chat_type, content)
    
    def _preset_response(self, chat_type: str, content: str) -> str:
        import random
        
        if chat_type == "greeting":
            return random.choice([
                "你好！今天想听什么歌？",
                "嗨！需要我帮你整理音乐库吗？",
                "欢迎！今天音乐心情如何？"
            ])
        elif chat_type == "emotion":
            if any(w in content for w in ["无聊", "烦"]):
                return "来首歌提提神？要我推荐一些节奏感强的歌吗？"
            elif any(w in content for w in ["难过", "郁闷"]):
                return "抱抱~ 听点舒缓的音乐可能会好一些。"
            elif any(w in content for w in ["开心", "高兴"]):
                return "太好了！开心的时候最适合听歌了！"
            elif "累" in content:
                return "辛苦了！来点轻音乐放松一下？"
            return "音乐是最好的情绪调节剂~"
        else:
            return random.choice([
                "有趣的话题！你的音乐库需要整理一下吗？",
                "最近有听什么好歌吗？",
                "需要我帮你扫描一下音乐库吗？"
            ])
    
    def handle_help(self, params: Dict) -> str:
        return """Music Agent Chat - 功能列表

【基本操作】
• "扫描" - 扫描音乐库，建立索引
• "分析" - 统计歌曲、艺术家、流派分布
• "帮助" - 显示此帮助
• "清除会话" - 重置对话历史

【文件整理】
• "整理音乐" - 按艺术家/专辑分类（预览→确认）
• "平铺所有歌曲" - 合并到一个文件夹
• "按流派整理" - 按音乐风格分类
• "按年代整理" - 按年份分类
• "清理重复" - 检测并移动重复文件

【智能查询】
• "周杰伦的歌" - 搜索特定歌手
• "推荐适合下雨听的" - 按场景/情绪
• "有哪些粤语歌" - 按语言筛选
• 查询后可输入: 1 | 第一首 | 播放第一首

【元数据修复】
• "修复元数据" - 批量修复所有歌曲
• "修复元数据并下载封面" - 批量修复+封面
• "修复这首歌" - 修复查询结果中的歌曲
• "重新识别" / "强制修复" - 强制重新识别（无视现有标签）
• "确认修复" - 执行修复操作
💡 建议：如果现有标签错误，用"重新识别"强制更新

【格式转换】
• "转换 wav 到 flac" - 批量转换格式
• "转换并删除源文件" - 转换后删除 WAV
• "删除 wav" - 直接删除所有 WAV 文件（⚠️ 不转换）
• "确认转换" / "确认删除" - 执行操作
💡 WAV→FLAC 可节省 30-50% 空间，同时支持元数据标签

【发现新音乐】
• "发现新音乐" / "生成周报" - 自动发现本周新歌并评估是否适合你
• "给我推荐" / "推荐歌曲" - 基于你的音乐库偏好推荐
• "发现像陈奕迅的歌" - 找相似风格的歌曲
• "工作时的歌" / "学习音乐" / "运动歌单" - 按场景发现
• "小众音乐" / "冷门独立" - 探索不为人知的好歌
• "周杰伦 新专辑" - 追踪特定艺术家的最新发行

【播放列表】
• "创建一个播放列表" - 随机生成（foobar2000格式）
• "创建一个30分钟的播放列表" - 指定时长
• "创建一个适合工作的50首歌单" - 智能生成
• "随机播放列表" - 完全随机打乱
• 播放列表保存到 /Playlists 目录，支持 foobar2000

【情绪播放列表】🎭
• "创建一个快乐的播放列表" / "开心歌单" - 快乐正能量
• "创建一个悲伤的播放列表" / "治愈歌单" - 安静治愈
• "创建一个激情的播放列表" / "燃向歌单" - 热血高能
• "创建一个平静的播放列表" / "放松歌单" - 舒缓放松
• "创建一个浪漫的播放列表" - 甜蜜情歌
• "创建一个怀旧的播放列表" - 经典金曲
• "创建一个专注的播放列表" - 工作学习背景音
• "创建一个派对的播放列表" - 嗨翻全场
• "分析情绪" / "分析歌词" / "分析歌曲" - 分析音乐库情绪分布（自动获取歌词）
• "生成歌词" / "下载歌词文件" - 从网易云批量下载歌词
• "识别XX歌词" / "提取XX歌词" / "AI识别" - 使用Whisper识别任意歌曲歌词（需安装）
• "哪些是比较浪漫的" / "推荐悲伤的歌" - 查询本地库中该情绪的歌曲

【模型管理】
• "当前模型" - 查看使用的Embedding模型
• "列出模型" - 显示所有可用模型
• "切换模型 bge-large-zh" - 更换语义模型

【退出】输入: 退出 | 再见 | bye"""
    
    def run(self):
        """启动对话"""
        print("\n" + "="*55)
        print("🎵 Music Agent Chat - 智能音乐助手")
        print("="*55 + "\n")
        
        if self.context.messages:
            print(f"[系统] 已恢复会话（{len(self.context.messages)} 条消息）")
            print("[系统] 输入'清除会话'重新开始\n")
        
        print("你好！我是你的音乐助手。今天想怎么管理音乐库？")
        print("💡 输入'帮助'查看所有功能\n")
        
        while True:
            try:
                user_input = input("\nJane: ").strip()
                if not user_input:
                    continue
                
                if user_input.lower() in ["exit", "quit", "退出", "再见", "bye", "q","886"]:
                    print("\n再见！享受音乐！🎶")
                    self.context.save_session()
                    break
                
                # 理解意图
                intent = self.understand_intent(user_input)
                
                # 记录用户消息
                self.context.add_message("user", user_input, intent)
                
                # 执行并回复
                response = self.execute(intent)
                print(f"\n助手: {response}")
                
                # 记录助手消息
                self.context.add_message("assistant", response)
                
                # 定期保存
                if len(self.context.messages) % 5 == 0:
                    self.context.save_session()
                
            except KeyboardInterrupt:
                print("\n\n再见！🎶")
                self.context.save_session()
                break
            except Exception as e:
                print(f"\n出错了: {e}")

if __name__ == "__main__":
    chat = MusicAgentChat()
    chat.run()