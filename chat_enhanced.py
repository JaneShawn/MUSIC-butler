# -*- coding: utf-8 -*-
"""
Music Agent Chat - 对话式音乐助手（增强版上下文）
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import yaml
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

from core.kimi_client import KimiClient
from agents import LibrarianAgent, ScoutAgent, CuratorAgent, OrganizerAgent, OrganizeStrategy


class SessionState(Enum):
    """会话状态"""
    IDLE = "idle"                    # 空闲
    AWAITING_CONFIRM = "awaiting_confirm"  # 等待确认（如整理、修复等）
    AWAITING_PARAMS = "awaiting_params"    # 等待补充参数
    IN_QUERY = "in_query"            # 查询结果中
    IN_ORGANIZE = "in_organize"      # 整理流程中


@dataclass
class PendingAction:
    """待执行的操作"""
    action_type: str          # 操作类型：organize/fix_metadata/...
    params: Dict[str, Any]    # 参数
    description: str          # 描述（用于向用户解释）
    requires_confirm: bool = True  # 是否需要确认


@dataclass
class Message:
    """单条消息"""
    role: str                 # user / assistant
    content: str
    timestamp: str
    intent: Optional[Dict] = None      # 意图信息
    entities: Optional[Dict] = None    # 提取的实体


class ContextManager:
    """上下文管理器"""
    
    def __init__(self, max_history: int = 20, session_file: Optional[Path] = None):
        self.max_history = max_history
        self.session_file = session_file or Path("chat_session.json")
        self.messages: List[Message] = []
        self.state = SessionState.IDLE
        self.pending_action: Optional[PendingAction] = None
        self.last_query_results: List[Dict] = []  # 上次查询结果（支持"第一首"等指代）
        self.session_metadata: Dict[str, Any] = {
            "start_time": datetime.now().isoformat(),
            "total_messages": 0,
            "commands_executed": 0
        }
        self._load_session()
    
    def add_message(self, role: str, content: str, intent: Dict = None, entities: Dict = None):
        """添加消息到历史"""
        msg = Message(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            intent=intent,
            entities=entities
        )
        self.messages.append(msg)
        self.session_metadata["total_messages"] += 1
        
        # 限制历史长度，保留最近的消息
        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history:]
    
    def get_recent_messages(self, n: int = 10) -> List[Message]:
        """获取最近的n条消息"""
        return self.messages[-n:] if self.messages else []
    
    def get_context_summary(self, max_tokens: int = 2000) -> str:
        """生成上下文摘要（用于LLM）"""
        if not self.messages:
            return ""
        
        # 获取最近的消息
        recent = self.get_recent_messages(8)
        
        # 构建上下文文本
        context_lines = []
        current_tokens = 0
        
        for msg in reversed(recent):
            line = f"{'用户' if msg.role == 'user' else '助手'}: {msg.content}\n"
            line_tokens = len(line)  # 简化估算
            
            if current_tokens + line_tokens > max_tokens:
                break
            
            context_lines.insert(0, line)
            current_tokens += line_tokens
        
        return "".join(context_lines)
    
    def set_pending_action(self, action: PendingAction):
        """设置待执行的操作"""
        self.pending_action = action
        self.state = SessionState.AWAITING_CONFIRM if action.requires_confirm else SessionState.IDLE
    
    def clear_pending_action(self):
        """清除待执行的操作"""
        self.pending_action = None
        self.state = SessionState.IDLE
    
    def set_query_results(self, results: List[Dict]):
        """保存查询结果（支持后续引用）"""
        self.last_query_results = results
        self.state = SessionState.IN_QUERY if results else SessionState.IDLE
    
    def resolve_reference(self, text: str) -> Optional[Dict]:
        """解析指代（如'第一首'、'最后一首'、'播放它'等）"""
        if not self.last_query_results:
            return None
        
        text_lower = text.lower()
        
        # 数字指代
        import re
        number_patterns = [
            (r'第(\d+)首', lambda m: int(m.group(1)) - 1),
            (r'(\d+)', lambda m: int(m.group(1)) - 1),
        ]
        
        for pattern, extractor in number_patterns:
            match = re.search(pattern, text)
            if match:
                idx = extractor(match)
                if 0 <= idx < len(self.last_query_results):
                    return self.last_query_results[idx]
        
        # 关键词指代
        if any(word in text for word in ['第一', '首个', '第一个']):
            return self.last_query_results[0] if self.last_query_results else None
        elif any(word in text for word in ['最后', '最后一首', '末尾']):
            return self.last_query_results[-1] if self.last_query_results else None
        elif any(word in text for word in ['这首', '它', '这个', '那首歌']):
            # 默认指代第一首或最近的
            return self.last_query_results[0] if self.last_query_results else None
        
        return None
    
    def _load_session(self):
        """加载会话历史"""
        if self.session_file.exists():
            try:
                with open(self.session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.messages = [Message(**m) for m in data.get('messages', [])]
                    self.session_metadata = data.get('metadata', self.session_metadata)
                    print(f"[系统] 已恢复之前的会话（{len(self.messages)} 条消息）")
            except Exception as e:
                print(f"[系统] 加载会话失败: {e}")
    
    def save_session(self):
        """保存会话历史"""
        try:
            data = {
                'messages': [asdict(m) for m in self.messages],
                'metadata': self.session_metadata,
                'last_saved': datetime.now().isoformat()
            }
            with open(self.session_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[系统] 保存会话失败: {e}")
    
    def clear_session(self):
        """清除会话历史"""
        self.messages = []
        self.pending_action = None
        self.last_query_results = []
        self.state = SessionState.IDLE
        if self.session_file.exists():
            self.session_file.unlink()


class MusicAgentChatEnhanced:
    """增强版对话式音乐助手"""
    
    def __init__(self):
        print("初始化中...")
        
        # 获取脚本所在目录
        script_dir = Path(__file__).parent.resolve()
        config_path = script_dir / "config.yaml"
        
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        # 初始化上下文管理器
        session_file = script_dir / "chat_session.json"
        self.context = ContextManager(max_history=30, session_file=session_file)
        
        try:
            self.kimi = KimiClient()
            print("✓ Kimi API 已连接")
        except:
            self.kimi = None
            print("✗ Kimi API 不可用")
        
        self._librarian = None
        self._organizer = None
    
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
    
    def understand_intent(self, user_input: str) -> Dict[str, Any]:
        """理解用户意图（上下文感知版）"""
        user_input_lower = user_input.lower()
        
        # 1. 检查是否有待确认的操作
        if self.context.state == SessionState.AWAITING_CONFIRM and self.context.pending_action:
            confirm_words = ['确认', '确定', '是的', '执行', '好', 'ok', 'yes', 'y']
            cancel_words = ['取消', '算了', '不', 'no', 'n']
            
            if any(word in user_input for word in confirm_words):
                return {
                    "intent": self.context.pending_action.action_type,
                    "params": self.context.pending_action.params,
                    "from_pending": True
                }
            elif any(word in user_input for word in cancel_words):
                self.context.clear_pending_action()
                return {"intent": "cancel", "params": {}}
        
        # 2. 检查指代（如"第一首"、"播放它"）
        referenced_item = self.context.resolve_reference(user_input)
        if referenced_item:
            if any(word in user_input for word in ['播放', '打开', '听']):
                return {
                    "intent": "play",
                    "params": {"song": referenced_item}
                }
            elif any(word in user_input for word in ['信息', '详情', '标签', '元数据']):
                return {
                    "intent": "show_info",
                    "params": {"song": referenced_item}
                }
        
        # 3. 多轮对话参数补充
        if self.context.state == SessionState.AWAITING_PARAMS:
            # 用户可能在补充参数
            return self._infer_params_from_context(user_input)
        
        # 4. 检查上下文中的隐含意图
        context_hint = self._check_context_hint(user_input)
        if context_hint:
            return context_hint
        
        # 5. 基础意图识别（原有逻辑）
        return self._base_intent_recognition(user_input)
    
    def _check_context_hint(self, user_input: str) -> Optional[Dict]:
        """检查上下文中的隐含意图"""
        recent = self.context.get_recent_messages(3)
        if not recent:
            return None
        
        user_input_lower = user_input.lower()
        
        # 检查是否是继续之前的操作
        last_intent = recent[-1].intent if recent[-1].intent else {}
        
        # 整理相关
        if last_intent.get('intent') == 'organize':
            if any(word in user_input for word in ['按流派', '流派']):
                return {"intent": "organize", "params": {"strategy": "genre", "confirm": False}}
            elif any(word in user_input for word in ['按年代', '年代', '年份']):
                return {"intent": "organize", "params": {"strategy": "year", "confirm": False}}
            elif any(word in user_input for word in ['平铺', '合并', '一起']):
                return {"intent": "organize", "params": {"strategy": "flat", "confirm": False}}
            elif any(word in user_input for word in ['按歌手', '歌手', '艺术家']):
                return {"intent": "organize", "params": {"strategy": "artist/album", "confirm": False}}
        
        # 查询相关 - 细化查询
        if last_intent.get('intent') == 'query':
            if any(word in user_input for word in ['粤语', '广东话']):
                return {"intent": "query", "params": {"query": "粤语歌曲"}, "refine": True}
            elif any(word in user_input for word in ['国语', '普通话', '中文']):
                return {"intent": "query", "params": {"query": "国语歌曲"}, "refine": True}
            elif any(word in user_input for word in ['英文', '英语', '欧美']):
                return {"intent": "query", "params": {"query": "英文歌曲"}, "refine": True}
        
        return None
    
    def _infer_params_from_context(self, user_input: str) -> Dict[str, Any]:
        """从上下文推断参数"""
        # 简化处理，实际可以更复杂
        return {"intent": "chat", "params": {"type": "general", "content": user_input}}
    
    def _base_intent_recognition(self, user_input: str) -> Dict[str, Any]:
        """基础意图识别（原 understand_intent 逻辑）"""
        user_input_lower = user_input.lower()
        
        if any(word in user_input_lower for word in ["exit", "quit", "退出", "再见"]):
            return {"intent": "exit"}
        
        if any(word in user_input_lower for word in ["扫描", "scan", "更新"]):
            return {"intent": "scan"}
        
        if any(word in user_input_lower for word in ["分析", "统计", "查看"]):
            return {"intent": "analyze"}
        
        organize_words = ["整理", "分类", "移动", "归类", "平铺", "合并", "放到一起"]
        if any(word in user_input for word in organize_words):
            strategy = "artist/album"
            if "平铺" in user_input or "合并" in user_input or "一起" in user_input:
                strategy = "flat"
            elif "流派" in user_input:
                strategy = "genre"
            elif "年代" in user_input:
                strategy = "year"
            
            confirm = "确认" in user_input
            return {
                "intent": "organize",
                "params": {"strategy": strategy, "confirm": confirm},
                "confirmation_needed": not confirm
            }
        
        if any(word in user_input for word in ["查询", "搜索", "找", "推荐", "有哪些"]):
            return {"intent": "query", "params": {"query": user_input}}
        
        if any(word in user_input for word in ["元数据", "标签", "修复", "补全"]):
            confirm = "确认" in user_input
            rename = "重命名" in user_input or "改名" in user_input
            return {
                "intent": "fix_metadata",
                "params": {"confirm": confirm, "rename": rename},
                "confirmation_needed": not confirm
            }
        
        if any(word in user_input for word in ["帮助", "help", "能做什么", "功能"]):
            return {"intent": "help"}
        
        if any(word in user_input for word in ["清除", "清空", "重置", "新会话"]):
            return {"intent": "clear_session"}
        
        # 闲聊意图
        chat_words = ["你好", "嗨", "hello", "hi", "在吗", "早上好", "晚上好", "谢谢", "感谢", "不错", "厉害"]
        if any(word in user_input for word in chat_words):
            return {"intent": "chat", "params": {"type": "greeting"}}
        
        emotion_words = ["无聊", "开心", "难过", "累", "烦", "郁闷", "高兴", "兴奋"]
        if any(word in user_input for word in emotion_words):
            return {"intent": "chat", "params": {"type": "emotion", "content": user_input}}
        
        music_chat_words = ["喜欢", "爱听", "最近", "歌单", "循环", "听腻"]
        if any(word in user_input for word in music_chat_words):
            return {"intent": "chat", "params": {"type": "music_chat", "content": user_input}}
        
        return {"intent": "chat", "params": {"type": "general", "content": user_input}}
    
    def execute(self, intent: Dict[str, Any]) -> str:
        """执行操作"""
        intent_type = intent.get("intent", "chat")
        params = intent.get("params", {})
        
        handlers = {
            "scan": self.handle_scan,
            "analyze": self.handle_analyze,
            "organize": self.handle_organize,
            "query": self.handle_query,
            "fix_metadata": self.handle_fix_metadata,
            "help": self.handle_help,
            "chat": self.handle_chat,
            "cancel": self.handle_cancel,
            "clear_session": self.handle_clear_session,
            "play": self.handle_play,
            "show_info": self.handle_show_info,
        }
        
        handler = handlers.get(intent_type, handlers["chat"])
        return handler(params)
    
    def handle_scan(self, params: Dict = None) -> str:
        """扫描音乐库"""
        print("正在扫描音乐库...")
        result = self.librarian.run("scan")
        return f"扫描完成！共发现 {result['total_files']} 个音乐文件，索引 {result['total_indexed']} 首歌曲。"
    
    def handle_analyze(self, params: Dict = None) -> str:
        """分析音乐库"""
        print("正在分析音乐库...")
        analysis = self.organizer.run("analyze")
        
        top_artists = analysis.get('top_artists', [])[:5]
        artists_text = "\n".join([f"  • {a}: {c}首" for a, c in top_artists])
        
        return f"""音乐库分析结果：
• 总歌曲: {analysis['total_songs']} 首
• 艺术家: {analysis['artists_count']} 位
• 流派: {analysis['genres_count']} 种

Top 5 艺术家：
{artists_text}

推荐整理策略: {analysis['suggestion']}"""
    
    def handle_organize(self, params: Dict) -> str:
        """整理文件"""
        strategy_str = params.get("strategy", "artist/album")
        confirm = params.get("confirm", False)
        from_pending = params.get("from_pending", False)
        
        strategy = OrganizeStrategy(strategy_str)
        
        # 如果不是从待执行操作来的，需要先预览
        if not from_pending:
            print(f"正在规划整理方案 (策略: {strategy.value})...")
            plan = self.organizer.run("plan", strategy=strategy)
            preview = self.organizer.preview_plan(plan)
            summary = preview["summary"]
            
            result = f"""整理计划预览：
• 总文件: {summary['total_files']} 首
• 将移动: {summary['to_move']} 首
• 将复制: {summary['to_copy']} 首
• 跳过: {summary['skip']} 首（已在正确位置）
• 冲突: {summary['conflicts']} 首（将自动重命名）

策略: {strategy.value}

这是预览模式，文件不会被实际移动。输入'确认整理'执行。"""
            
            # 设置待执行操作
            self.context.set_pending_action(PendingAction(
                action_type="organize",
                params={"strategy": strategy_str, "confirm": True, "from_pending": True},
                description=f"按{strategy.value}策略整理音乐文件",
                requires_confirm=True
            ))
            return result
        
        # 执行整理
        print("正在执行整理...")
        plan = self.organizer.run("plan", strategy=strategy)
        result_obj = self.organizer.run("execute", plan=plan, dry_run=False)
        self.context.clear_pending_action()
        self.context.session_metadata["commands_executed"] += 1
        return f"整理完成！成功: {result_obj.executed} 首, 失败: {result_obj.failed} 首"
    
    def handle_query(self, params: Dict) -> str:
        """查询歌曲"""
        query_text = params.get("query", "")
        is_refine = params.get("refine", False)
        
        if is_refine:
            print(f"正在细化搜索: {query_text}")
        else:
            print(f"正在搜索: {query_text}")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        results = self.librarian.query(query_text, top_k=5)
        self.context.set_query_results(results)
        
        if not results:
            self.context.state = SessionState.IDLE
            return "没有找到匹配的歌曲。"
        
        # 构建结果文本，带序号
        songs_lines = []
        for i, item in enumerate(results, 1):
            song = item['song']
            songs_lines.append(f"  {i}. 《{song.title}》- {song.artist}")
        
        songs_text = "\n".join(songs_lines)
        
        return f"找到 {len(results)} 首相关歌曲（可以输入序号如'1'或'播放第一首'来选择）：\n{songs_text}"
    
    def handle_fix_metadata(self, params: Dict) -> str:
        """修复元数据"""
        confirm = params.get("confirm", False)
        rename = params.get("rename", False)
        from_pending = params.get("from_pending", False)
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        if not from_pending:
            # 先预览
            result = self.librarian.fix_metadata(dry_run=True, rename_files=rename)
            
            if result["incomplete"] == 0:
                return "所有歌曲元数据完整！无需修复。"
            
            rename_hint = "\n\n将同时重命名文件为'歌手 - 歌名'格式" if rename else ""
            
            # 设置待执行操作
            self.context.set_pending_action(PendingAction(
                action_type="fix_metadata",
                params={"confirm": True, "rename": rename, "from_pending": True},
                description=f"修复元数据{'并重命名文件' if rename else ''}",
                requires_confirm=True
            ))
            
            return f"""元数据检查结果：
• 总歌曲: {result['total']} 首
• 待修复: {result['incomplete']} 首
• 可从文件名修复: {result['fixed']} 首
• 在线搜索找到: {result.get('found_online', 0)} 首{rename_hint}

这是预览模式。输入'确认修复'执行修复。"""
        
        # 执行修复
        print("正在搜索MusicBrainz数据库（可能需要几分钟）...")
        result = self.librarian.fix_metadata(dry_run=False, rename_files=rename)
        self.context.clear_pending_action()
        self.context.session_metadata["commands_executed"] += 1
        
        rename_info = f"\n• 重命名文件: {result.get('renamed', 0)} 首" if rename else ""
        
        return f"""元数据修复完成：
• 总歌曲: {result['total']} 首
• 待修复: {result['incomplete']} 首
• 已修复: {result['fixed']} 首
• 成功写入标签: {result['written']} 首{rename_info}
• 未找到: {result['failed']} 首

修改已保存到文件标签中。"""
    
    def handle_play(self, params: Dict) -> str:
        """播放歌曲（显示信息）"""
        song = params.get("song")
        if not song:
            return "没有找到要播放的歌曲。"
        
        s = song.get('song', song)  # 兼容两种数据结构
        return f"🎵 {s.artist} - {s.title}\n文件路径: {s.file_path}"
    
    def handle_show_info(self, params: Dict) -> str:
        """显示歌曲详细信息"""
        song = params.get("song")
        if not song:
            return "没有找到歌曲信息。"
        
        s = song.get('song', song)
        info = f"""📀 {s.title}
👤 艺术家: {s.artist}
💿 专辑: {s.album or '未知'}
🎵 流派: {s.genre or '未知'}
📅 年份: {s.year or '未知'}
📝 歌词: {'有' if s.lyrics else '无'}
💻 文件: {s.file_path.name}"""
        return info
    
    def handle_cancel(self, params: Dict = None) -> str:
        """取消待执行操作"""
        if self.context.pending_action:
            action_desc = self.context.pending_action.description
            self.context.clear_pending_action()
            return f"已取消: {action_desc}"
        return "没有待执行的操作。"
    
    def handle_clear_session(self, params: Dict = None) -> str:
        """清除会话"""
        msg_count = len(self.context.messages)
        self.context.clear_session()
        return f"会话已重置（清除了 {msg_count} 条历史消息）。"
    
    def handle_chat(self, params: Dict) -> str:
        """处理闲聊"""
        chat_type = params.get("type", "general")
        content = params.get("content", "")
        
        # 尝试使用Kimi生成回复
        if self.kimi:
            try:
                return self._generate_chat_response(chat_type, content)
            except Exception as e:
                print(f"[调试] Kimi生成失败: {e}")
        
        # 使用预设回复
        return self._get_preset_response(chat_type, content)
    
    def _generate_chat_response(self, chat_type: str, content: str) -> str:
        """使用Kimi生成闲聊回复（增强版，带完整上下文）"""
        system_prompt = """你是一个友好、幽默的音乐助手，叫Music Agent。

你的特点：
1. 热爱音乐，对各种风格的音乐都有了解
2. 性格轻松幽默，像朋友一样聊天
3. 回答简短自然，30-80字左右
4. 如果用户提到情绪，推荐适合的音乐
5. 如果用户打招呼，热情回应
6. 能够记住之前的对话，保持连贯性

注意：你是音乐助手，如果用户要求具体操作（如整理文件），引导他们使用指令。"""

        # 获取完整上下文
        context = self.context.get_context_summary(max_tokens=1500)
        
        # 添加当前会话状态信息
        state_info = ""
        if self.context.pending_action:
            state_info = f"\n当前有待确认的操作: {self.context.pending_action.description}"
        if self.context.last_query_results:
            state_info += f"\n用户最近查询了 {len(self.context.last_query_results)} 首歌曲"
        
        prompt = f"""对话上下文：
{context}{state_info}

当前用户说：{content}

请自然友好地回复（简短，30-80字）："""

        response = self.kimi.generate(prompt, system=system_prompt, temperature=0.8, max_tokens=200)
        return response if response else self._get_preset_response(chat_type, content)
    
    def _get_preset_response(self, chat_type: str, content: str) -> str:
        """预设回复"""
        import random
        
        if chat_type == "greeting":
            greetings = [
                "你好！今天想听什么歌？",
                "嗨！需要我帮你整理音乐库吗？",
                "你好呀！最近有发现什么好歌吗？",
                "欢迎！今天音乐心情如何？"
            ]
            return random.choice(greetings)
        
        elif chat_type == "emotion":
            if "无聊" in content or "烦" in content:
                return "来首歌提提神？要我推荐一些节奏感强的歌吗？"
            elif "难过" in content or "郁闷" in content:
                return "抱抱~ 听点舒缓的音乐可能会好一些。要我帮你找一些温柔的歌吗？"
            elif "开心" in content or "高兴" in content or "兴奋" in content:
                return "太好了！开心的时候最适合听歌了，要不要我推荐一些欢快的歌？"
            elif "累" in content:
                return "辛苦了！来点轻音乐放松一下？"
            else:
                return "音乐是最好的情绪调节剂，需要我推荐一些适合你现在心情的歌吗？"
        
        elif chat_type == "music_chat":
            if "喜欢" in content or "爱听" in content:
                return "有品味！要我推荐类似风格的吗？"
            elif "最近" in content:
                return "最近有什么新歌推荐吗？我可以帮你发现一些新的音乐~"
            elif "听腻" in content:
                return "换个口味试试？我可以帮你整理一下歌单，或者发现一些新音乐~"
            else:
                return "聊音乐我最在行！要我帮你分析一下你的音乐库吗？"
        
        else:
            general = [
                "有趣的话题！说起来，你的音乐库需要整理一下吗？",
                "哈哈，说到这个，最近有听什么好歌吗？",
                "嗯嗯，继续聊？或者我可以帮你做点什么，比如整理音乐文件？",
                "了解了~ 需要我帮你扫描一下音乐库，看看有什么歌吗？"
            ]
            return random.choice(general)
    
    def handle_help(self, params: Dict = None) -> str:
        """显示帮助"""
        return """Music Agent 帮助（增强版）：

【基本操作】
• "扫描音乐库" - 扫描文件夹，建立索引
• "分析我的音乐库" - 统计歌曲、艺术家、流派
• "帮助" - 显示此帮助信息
• "清除会话" - 重置对话历史

【文件整理】
• "帮我整理音乐文件" - 按艺术家/专辑分类
• "全部平铺" - 所有歌曲放一起
• "按流派整理" - 按音乐风格分类
• "按年代分类" - 按年份分类

整理流程：先输入整理指令预览 → 输入"确认整理"执行

【查询歌曲】
• "周杰伦的歌" - 找特定歌手的歌
• "推荐适合运动听的" - 按场景推荐
• "有哪些粤语歌" - 按语言筛选
• 查询后可用 "1" 或 "第一首" 选择结果

【元数据修复】
• "修复元数据" - 从文件名/在线搜索补全信息
• "确认修复" - 执行修复
• "确认修复并重命名" - 修复+重命名文件

【退出】
• "退出" 或 "再见" - 结束对话（会话会自动保存）"""
    
    def run(self):
        """启动对话"""
        print("\n" + "="*50)
        print("Music Agent Chat - 智能音乐助手")
        print("输入 '帮助' 查看所有功能")
        print("="*50 + "\n")
        
        # 恢复提示
        if self.context.messages:
            print(f"[系统] 已恢复之前的会话，共 {len(self.context.messages)} 条消息")
            print("[系统] 输入'清除会话'可重新开始\n")
        
        print("你好！我是你的音乐助手。今天想怎么管理你的音乐库？")
        
        try:
            while True:
                try:
                    user_input = input("\n你: ").strip()
                    
                    if not user_input:
                        continue
                    
                    if user_input.lower() in ["exit", "quit", "退出", "再见", "bye"]:
                        print("\n再见！享受音乐！")
                        self.context.save_session()
                        break
                    
                    # 理解意图
                    intent = self.understand_intent(user_input)
                    
                    # 记录用户消息
                    self.context.add_message(
                        role="user",
                        content=user_input,
                        intent=intent
                    )
                    
                    # 执行并获取回复
                    response = self.execute(intent)
                    
                    # 显示回复
                    print(f"\n助手: {response}")
                    
                    # 记录助手消息
                    self.context.add_message(
                        role="assistant",
                        content=response
                    )
                    
                    # 自动保存会话
                    if len(self.context.messages) % 5 == 0:
                        self.context.save_session()
                    
                except KeyboardInterrupt:
                    print("\n\n再见！")
                    self.context.save_session()
                    break
                except Exception as e:
                    print(f"\n出错了: {e}")
                    import traceback
                    traceback.print_exc()
        finally:
            self.context.save_session()


if __name__ == "__main__":
    chat = MusicAgentChatEnhanced()
    chat.run()
