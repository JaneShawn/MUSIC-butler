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
from datetime import datetime

current_dir = Path(__file__).parent
env_path = current_dir / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv()

# ── LangGraph 入口 ──
from graph.graph import music_graph
from graph.utils import load_config
from langchain_core.messages import HumanMessage


class MusicAgentChat:
    """对话入口 — LangGraph 多Agent 系统的薄包装层。"""

    def __init__(self):
        print("Initializing Music Agent (LangGraph)...")

        self.config = load_config()
        self.graph = music_graph
        self.thread_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 自动启动文件监控
        self._start_watcher()

        print("Music Agent ready! (LangGraph backend)")

    def _start_watcher(self):
        """启动文件监控，监听 config.yaml 中 library.watch_dirs 配置的目录"""
        from core.folder_watcher import FolderWatcher
        from agents.librarian import get_librarian

        library_path = self.config.get("library", {}).get("path", "")
        if not library_path:
            print("  [监控] 未配置音乐库路径，跳过")
            return

        watch_entries = self.config.get("library", {}).get("watch_dirs", ["MUSIC", "ALBUM"])
        watch_dirs = []
        for d in watch_entries:
            p = Path(d)
            if not p.is_absolute():
                p = Path(library_path) / d
            watch_dirs.append(str(p))

        existing = [d for d in watch_dirs if Path(d).exists() and Path(d).is_dir()]
        if not existing:
            print(f"  [监控] 目录不存在: {watch_dirs}，跳过")
            return

        try:
            self._watcher = FolderWatcher(watch_dirs=existing)
            self._watcher.set_librarian(get_librarian())
            self._watcher.start()
            print(f"  [监控] 已启动，监听 {len(existing)} 个目录")
        except Exception as e:
            print(f"  [监控] 启动失败: {e}")

    # ── 对话接口 ──
    def _handle_monitor_command(self, user_input: str):
        """处理监控指令，返回回复字符串；不是监控指令则返回 None。"""
        start_words = ["开启监控", "启动监控", "打开监控", "开始监控"]
        stop_words = ["关闭监控", "停止监控", "关掉监控"]
        status_words = {"监控状态", "监控"}

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

    def chat(self, user_input: str) -> str:
        """单轮对话：传入用户输入，返回助手回复。

        使用 LangGraph MemorySaver 自动维护多轮对话状态（替代 chat_session.json）。
        """
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
        print("Hello Jane! 我是你的音乐助手，有什么能帮助你的？")

        while True:
            try:
                user_input = input("\nJane: ").strip()
                if not user_input:
                    continue

                if user_input.lower() in ["exit", "quit", "q", "bye", "886", "退出", "再见"]:
                    if hasattr(self, '_watcher') and self._watcher.is_running:
                        self._watcher.stop()
                    print("\n下次见！")
                    break

                response = self.chat(user_input)
                print(f"\nAssistant: {response}")

            except KeyboardInterrupt:
                if hasattr(self, '_watcher') and self._watcher.is_running:
                    self._watcher.stop()
                print("\n\nGoodbye!")
                break
            except Exception as e:
                print(f"\nError: {e}")


if __name__ == "__main__":
    chat = MusicAgentChat()
    chat.run()
