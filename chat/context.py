# -*- coding: utf-8 -*-
"""
Chat Context - 会话上下文管理
"""
import json
import re
from pathlib import Path
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
