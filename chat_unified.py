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

from chat.context import NLPUtils
from core.emotion_constants import EMOTION_KEYWORDS, EMOTION_ALIAS, EMOTION_NAMES
from core.language_constants import LANGUAGE_ALIAS
from core.kimi_client import KimiClient
from core.vector_store import EMBEDDING_MODELS
from core.audio_converter import AudioConverter, preview_conversion
from agents import LibrarianAgent, ScoutAgent, CuratorAgent, OrganizerAgent, OrganizeStrategy
from chat.tool_registry import ToolRegistry
from chat.handlers import (
    FixHandlers, DiscoverHandlers, PlayHandlers, AnalyzeHandlers,
    ManageHandlers, OpsHandlers, InfoHandlers,
)


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



class MusicAgentChat(FixHandlers, DiscoverHandlers, PlayHandlers, AnalyzeHandlers,
                      ManageHandlers, OpsHandlers, InfoHandlers):
    """统一版对话式音乐助手"""

    # L0: 绝对命令 — O(1) 哈希匹配，零延迟零 token
    _COMMAND_MAP = {
        "扫描": "scan", "scan": "scan",
        "帮助": "help", "help": "help", "功能": "help", "能做什么": "help",
        "退出": "exit", "exit": "exit", "再见": "exit", "quit": "exit",
        "清除": "clear", "清空": "clear",
        "播放全部": "play_all", "全部播放": "play_all",
    }

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
        self._playlist_engine = None
        self._metadata_scheduler = None
        self._folder_watcher = None

        # LLM 意图识别缓存（减少重复 API 调用）
        # 缓存版本：修改 prompt 后递增，使旧缓存自动失效
        self._INTENT_CACHE_VERSION = 6
        self._intent_cache: Dict[str, Dict[str, Any]] = {}
        
        # 有效意图白名单：ToolRegistry + 内部/硬编码意图（自动同步，不会漂移）
        self._VALID_INTENTS = ToolRegistry.get_tool_names() | {
            "play", "info", "exit", "cancel", "help", "chat",
            "play_all", "batch_select", "playlist_from_results",
            "play_all_results", "play_all_except",
            "analyze_emotion", "detect_language_by_audio",
            "export_language_csv", "delete_wav", "clear",
            "list_models", "switch_model", "current_model",
            "monitor", "delete_playlist", "refresh_playlist",
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

    @property
    def playlist_engine(self):
        if self._playlist_engine is None:
            from core.playlist_engine import SmartPlaylistEngine
            self._playlist_engine = SmartPlaylistEngine(
                librarian=self.librarian, kimi_client=self.kimi
            )
        return self._playlist_engine

    @property
    def metadata_scheduler(self):
        if self._metadata_scheduler is None:
            from core.metadata_scheduler import MetadataScheduler
            self._metadata_scheduler = MetadataScheduler(librarian=self.librarian)
        return self._metadata_scheduler

    @property
    def folder_watcher(self):
        if self._folder_watcher is None:
            from core.folder_watcher import FolderWatcher
            library_path = self.config.get("library", {}).get("path", "")
            music_dir = str(Path(library_path + "/MUSIC")) if library_path else "../MUSIC"
            album_dir = str(Path(library_path + "/ALBUM")) if library_path else "../ALBUM"
            self._folder_watcher = FolderWatcher(watch_dirs=[music_dir, album_dir])
            self._folder_watcher.set_librarian(self.librarian)
        return self._folder_watcher

    def understand_intent(self, user_input: str) -> Dict[str, Any]:
        """理解用户意图

        采用 L0 + FC 混合策略：
        L0. 绝对命令走 O(1) 哈希匹配，零延迟零 token
        1. 确认/取消/数字选择等硬编码规则，零延迟
        2. 其他自然语言走 FC 语义理解
        3. FC 不可用时 fallback 到精简后的硬编码规则
        """
        user_input_stripped = user_input.strip()

        # === L0: 绝对命令（O(1) 哈希匹配，零延迟零 token）===
        cmd = self._COMMAND_MAP.get(user_input_stripped)
        if cmd:
            return {"intent": cmd, "params": {}}

        self._last_user_input = user_input
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
        
        # 查询结果上下文指令（有结果时才生效，零延迟零 token）
        if self.context.last_query_results:
            results = self.context.last_query_results
            n = len(results)
            u = user_input_stripped

            # "播放" / "播" → 播放全部
            if u in ("播放", "播"):
                return {"intent": "play_all_results"}

            # "随机来一首" / "随机一首" / "随机播放" / "来一首随机的"
            if u in ("随机来一首", "随机一首", "随机播放", "随机来一个", "随机播", "来一首随机的"):
                import random
                return {"intent": "play", "params": {"item": random.choice(results)}}

            # "除了第3首都播放" / "除了3都播放" / "除了3都播"
            m = re.match(r'除了第?(\d+)首?(?:都[播放]?|全部播放)?$', u)
            if m:
                exclude = int(m.group(1)) - 1
                if 0 <= exclude < n:
                    keep = [results[i] for i in range(n) if i != exclude]
                    return {"intent": "play_all_except", "params": {"songs": keep, "excluded": exclude}}

        # 批量情绪分析（高优先级拦截，避免 LLM 把"分析情绪"误判为 analyze_single_emotion）
        if any(p in user_input for p in ["分析情绪", "情绪分析", "情绪识别"]):
            # 排除 "分析XXX的情绪" 这种明确指定歌名的情况
            if not re.search(r'分析.+?的.?情绪', user_input):
                force = any(w in user_input for w in ["重新", "强制", "刷新", "更新"])
                return {"intent": "analyze_emotion", "params": {"force": force}}

        # 监控控制（高优先级，零延迟）
        if any(w in user_input for w in ["开启监控", "启动监控", "打开监控", "开始监控"]):
            return {"intent": "monitor", "params": {"action": "start"}}
        if any(w in user_input for w in ["关闭监控", "停止监控", "关掉监控"]):
            return {"intent": "monitor", "params": {"action": "stop"}}
        if any(w in user_input for w in ["监控状态", "查看监控"]):
            return {"intent": "monitor", "params": {"action": "status"}}

        # 元数据诊断/修复
        if any(w in user_input for w in ["诊断元数据", "元数据诊断", "检查元数据"]):
            return {"intent": "diagnose", "params": {}}
        if any(w in user_input for w in ["同步情绪缓存", "同步情绪"]):
            return {"intent": "sync_emotion", "params": {}}
        if any(w in user_input for w in ["一键修复", "修复元数据问题", "批量修复元数据"]):
            return {"intent": "fix_metadata_issues", "params": {}}

        # 查看歌单
        if any(w in user_input for w in ["查看歌单", "我的歌单", "歌单列表"]):
            return {"intent": "list_playlists", "params": {}}

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
        """使用 Kimi Function Calling 识别用户意图，返回结构化结果。

        相比较旧的 prompt+JSON 解析方案的优势：
        - 工具名和参数由 API 级别保证（不会返回不存在的 intent 名）
        - 参数 enum 约束保证值合法（如 language 只能是 国语/英语/粤语...）
        - 无需维护 200+ 行 few-shot prompt
        """
        if not self.kimi:
            return None

        # 1. 检查缓存（带版本控制）
        cache_key = user_input.strip().lower()
        if cache_key in self._intent_cache:
            cached = self._intent_cache[cache_key]
            if cached.get("_cache_version") == self._INTENT_CACHE_VERSION:
                print(f"  [FC意图识别] '{user_input}' -> {cached['intent']} (cache)")
                return {k: v for k, v in cached.items() if not k.startswith("_")}

        # 2. 获取对话历史
        recent_msgs = self.context.get_recent(4)
        dialog_lines = []
        if len(recent_msgs) >= 2:
            for m in recent_msgs[:-1]:
                prefix = "User" if m.role == "user" else "Assistant"
                content = m.content[:80] + "..." if len(m.content) > 80 else m.content
                dialog_lines.append(f"{prefix}: {content}")
        if self.context.last_query_results:
            dialog_lines.append(
                f"(User's last query returned {len(self.context.last_query_results)} songs)"
            )
        dialog_history = "\n".join(dialog_lines)

        # 3. 构造消息并调用 Function Calling
        try:
            messages = [{"role": "system", "content": ToolRegistry.build_system_prompt()}]
            if dialog_history:
                messages.append({"role": "user", "content": f"Dialog history:\n{dialog_history}"})
            messages.append({"role": "user", "content": user_input})

            response = self.kimi.chat_completion(
                messages=messages,
                tools=ToolRegistry.get_tools(),
                tool_choice="auto",
                temperature=0.1,
                max_tokens=300,
            )

            tool_calls = response.get("tool_calls")
            if not tool_calls or len(tool_calls) == 0:
                result_dict = {"intent": "chat", "params": {"type": "general", "content": user_input}}
                print(f"  [FC意图识别] '{user_input}' -> chat (no tool call)")
                return result_dict

            # 解析第一个 tool call
            tc = tool_calls[0]
            func = tc.get("function", {})
            intent_name = func.get("name", "chat")
            try:
                params = json.loads(func.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                params = {}

            # 校验 tool name 是否在注册表中（防御性检查）
            valid_tool_names = ToolRegistry.get_tool_names()
            if intent_name not in valid_tool_names:
                print(f"  [FC意图识别] tool '{intent_name}' not in registry ({len(valid_tool_names)} tools), fallback to chat")
                intent_name = "chat"
                params = {"type": "general"}

            result_dict = {"intent": intent_name, "params": params}

            if intent_name != "chat":
                self._intent_cache[cache_key] = {
                    "_cache_version": self._INTENT_CACHE_VERSION,
                    **result_dict,
                }

            print(f"  [FC意图识别] '{user_input}' -> {intent_name}")
            return result_dict

        except Exception as e:
            print(f"  [FC意图识别] failed: {e}")
            return None
    
    def _base_intent(self, user_input: str) -> Dict[str, Any]:
        """基础意图识别——LLM不可用时的生存兜底，只保留核心功能。"""
        user_input_lower = user_input.lower()

        # 退出
        if any(w in user_input_lower for w in ["exit", "quit", "退出", "再见"]):
            return {"intent": "exit"}

        # 扫描
        if any(w in user_input_lower for w in ["扫描", "scan", "更新"]):
            return {"intent": "scan"}

        # 帮助
        if any(w in user_input for w in ["帮助", "help", "能做什么", "功能"]):
            return {"intent": "help"}

        # 清除
        if any(w in user_input for w in ["清除", "清空", "重置"]):
            return {"intent": "clear"}

        # 播放全部
        if any(phrase in user_input for phrase in ["播放全部", "播放所有", "全部播放", "所有歌曲"]):
            return {"intent": "play_all", "params": {}}

        # 播放/听/放 指定歌曲或歌手
        if any(w in user_input for w in ["播放", "听", "放", "来首", "给我放"]):
            for prefix in ["播放", "听", "放", "放一首", "来一首", "给我放", "来首"]:
                if user_input.startswith(prefix):
                    potential = user_input[len(prefix):].strip()
                    if potential and len(potential) > 1:
                        if potential.endswith(("的歌", "歌曲")):
                            for suffix in ["的歌", "歌曲"]:
                                if potential.endswith(suffix):
                                    potential = potential[:-len(suffix)]
                                    break
                            return {"intent": "play_by_artist", "params": {"artist": potential}}
                        return {"intent": "play_by_name", "params": {"song_name": potential}}
            return {"intent": "query", "params": {"query": user_input}}

        # 情绪查询（高频，必须在通用query之前）
        is_emotion_query = any(w in user_input for w in ["哪些", "有什么", "推荐", "歌", "歌曲"])
        detected_emotion = None
        for keyword, emotion in NLPUtils.EMOTION_KEYWORDS.items():
            if keyword in user_input:
                if keyword == "舞曲" and "小步舞曲" in user_input:
                    continue
                detected_emotion = emotion
                break
        if is_emotion_query and detected_emotion:
            return {"intent": "query_emotion_songs", "params": {"emotion": detected_emotion}}

        # 语言查询（高频，必须在通用query之前）
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
        if detected_language and is_language_query:
            return {"intent": "query_language_songs", "params": {"language": detected_language}}

        # 查询/搜索（通用兜底，放在情绪/语言查询之后）
        if any(w in user_input for w in ["查询", "搜索", "找", "有哪些"]) or \
           ("推荐" in user_input and not any(w in user_input for w in ["给我推荐", "推荐歌曲", "推荐音乐", "根据我的库"])):
            return {"intent": "query", "params": {"query": user_input}}

        # Embedding模型管理（FC tools未覆盖，唯一入口）
        if any(w in user_input for w in ["模型", "embedding", "向量", "检索模型", "语义模型"]):
            if any(w in user_input for w in ["切换", "更换", "换", "使用"]):
                for alias in EMBEDDING_MODELS.keys():
                    if alias.replace("-", "").replace("_", "").lower() in user_input_lower.replace("-", "").replace("_", ""):
                        return {"intent": "switch_model", "params": {"model": alias}}
                return {"intent": "list_models"}
            elif any(w in user_input for w in ["列表", "有哪些", "list"]):
                return {"intent": "list_models"}
            elif any(w in user_input for w in ["当前", "现在", "current"]):
                return {"intent": "current_model"}

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
            "play_all": self.handle_play_all,
            "recommend_random": self.handle_recommend_random,
            "playlist_from_results": self.handle_playlist_from_results,
            "play_all_results": self.handle_play_all_results,
            "play_all_except": self.handle_play_all_except,
            "batch_select": self.handle_batch_select,
            "show_language_stats": self.handle_show_language_stats,
            "detect_language_by_audio": self.handle_detect_language_by_audio,
            "detect_single_language": self.handle_detect_single_language,
            "export_library": self.handle_export_library,
            "import_library": self.handle_import_library,
            "show_library_stats": self.handle_show_library_stats,
            "export_language_csv": self.handle_export_language_csv,
            "correct_language": self.handle_correct_language,
            "correct_emotion": self.handle_correct_emotion,
            "play_by_artist": self.handle_play_by_artist,
            "update_song_info": self.handle_update_song_info,
            "analyze_emotion": self.handle_analyze_emotion,
            "analyze_single_emotion": self.handle_analyze_single_emotion,
            "download_lyrics": self.handle_download_lyrics,
            "generate_lyrics_whisper": self.handle_generate_lyrics_whisper,
            "query_emotion_songs": self.handle_query_emotion_songs,
            "query_language_songs": self.handle_query_language_songs,
            "play": self.handle_play,
            "info": self.handle_info,
            # v2 新增
            "monitor": self.handle_monitor,
            "diagnose": self.handle_diagnose,
            "fix_metadata_issues": self.handle_fix_metadata_issues,
            "sync_emotion": self.handle_sync_emotion,
            "smart_playlist": self.handle_smart_playlist,
            "list_playlists": self.handle_list_playlists,
            "refresh_playlist": self.handle_refresh_playlist,
            "delete_playlist": self.handle_delete_playlist,
        }
        handler = handlers.get(intent.get("intent"), handlers["chat"])
        return handler(intent.get("params", {}))

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