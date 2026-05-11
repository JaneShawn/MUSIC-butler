# -*- coding: utf-8 -*-
"""
Music Agent Chat — LangGraph 多Agent 对话入口
所有意图路由 & Agent 调度由 graph/ 下的 LangGraph 图处理。
chat_unified.py 只负责：接收用户输入 → 传给 graph → 输出响应。
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from pathlib import Path
from dotenv import load_dotenv

current_dir = Path(__file__).parent
env_path = current_dir / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv()

import yaml
from datetime import datetime

from chat.handlers import (
    FixHandlers, DiscoverHandlers, PlayHandlers, AnalyzeHandlers,
    ManageHandlers, OpsHandlers, InfoHandlers,
)

# ── LangGraph 入口 ──
from graph.graph import music_graph
from langchain_core.messages import HumanMessage


class MusicAgentChat(FixHandlers, DiscoverHandlers, PlayHandlers, AnalyzeHandlers,
                      ManageHandlers, OpsHandlers, InfoHandlers):
    """对话入口 — LangGraph 多Agent 系统的薄包装层。

    保留 Handler mixin 继承以兼容 scripts/ 和 web UI 中的直接方法调用。
    交互式对话的 run() 方法已迁移到 LangGraph 图。
    """

    def __init__(self):
        print("Initializing Music Agent (LangGraph)...")

        config_path = current_dir / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.graph = music_graph
        self.thread_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 延迟初始化的属性（保持与旧版兼容）
        self._librarian = None
        self._organizer = None
        self._scout = None
        self._curator = None
        self.kimi = None

        # 上下文兼容（旧代码引用 self.context 时不报错）
        from chat.context import ContextManager
        self.context = ContextManager(session_file=current_dir / "chat_session.json")

        print("Music Agent ready! (LangGraph backend)")

    # ── Agent 惰性属性（scripts/ 中直接调用时使用） ──
    @property
    def librarian(self):
        if self._librarian is None:
            from agents import LibrarianAgent
            self._librarian = LibrarianAgent(self.config)
        return self._librarian

    @property
    def organizer(self):
        if self._organizer is None:
            from agents import OrganizerAgent
            self._organizer = OrganizerAgent(self.config, self.librarian)
        return self._organizer

    @property
    def scout(self):
        if self._scout is None:
            from agents import ScoutAgent
            self._scout = ScoutAgent(self.config)
        return self._scout

    @property
    def curator(self):
        if self._curator is None:
            from agents import CuratorAgent
            self._curator = CuratorAgent(self.config, self.librarian)
        return self._curator

    # ── 对话接口 ──
    def chat(self, user_input: str) -> str:
        """单轮对话：传入用户输入，返回助手回复。

        使用 LangGraph MemorySaver 自动维护多轮对话状态（替代 chat_session.json）。
        """
        config = {"configurable": {"thread_id": self.thread_id}}

        result = self.graph.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
        )

        response = result.get("final_response", "")
        if not response:
            # 回退：取最后一条 assistant 消息
            msgs = result.get("messages", [])
            for m in reversed(msgs):
                content = m.content if hasattr(m, 'content') else m.get("content", "")
                if content and (hasattr(m, 'type') and m.type == 'ai' or m.get('role') == 'assistant'):
                    response = content
                    break

        return response or "处理完成。"

    def stream(self, user_input: str):
        """流式输出，展示 Agent 执行轨迹。"""
        config = {"configurable": {"thread_id": self.thread_id}}

        for event in self.graph.stream(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
            stream_mode="values",
        ):
            yield event

    # ── 交互式对话 ──
    def run(self):
        """交互式对话主循环"""
        print("\n" + "=" * 55)
        print("Music Agent Chat - LangGraph Multi-Agent")
        print("=" * 55 + "\n")
        print("Hello! I'm your music assistant. How can I help you today?")
        print("Type 'help' to see all features\n")

        while True:
            try:
                user_input = input("\nJane: ").strip()
                if not user_input:
                    continue

                if user_input.lower() in ["exit", "quit", "q", "bye", "886", "退出", "再见"]:
                    print("\nGoodbye! Enjoy the music!")
                    break

                response = self.chat(user_input)
                print(f"\nAssistant: {response}")

            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                break
            except Exception as e:
                print(f"\nError: {e}")


if __name__ == "__main__":
    chat = MusicAgentChat()
    chat.run()
