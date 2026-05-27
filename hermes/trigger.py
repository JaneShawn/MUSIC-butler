# -*- coding: utf-8 -*-
"""
Hermes Trigger 层 — 统一输入标准化

所有外部输入（聊天、CLI、Web、文件监控）通过 Trigger 归一化为 TriggerEvent，
下游 Gateway 只认这一种格式，不再关心输入来源。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


# ── 标准事件格式 ───────────────────────────────────────────

@dataclass
class TriggerEvent:
    """所有触发源的统一事件格式。Gateway 只消费这个结构。"""
    source: str                              # "chat" | "cli" | "web" | "watcher"
    user_id: str = "default"
    content: str = ""                        # 用户文本 或 系统事件描述
    context: Dict[str, Any] = field(default_factory=dict)  # 附加上下文
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_user_message(self) -> bool:
        """是否来自用户主动输入（chat/cli/web），而非系统事件（watcher）。"""
        return self.source in ("chat", "cli", "web")

    @property
    def is_system_event(self) -> bool:
        """是否来自系统事件（watcher 等）。"""
        return self.source == "watcher"


# ── Trigger 基类 ───────────────────────────────────────────

class TriggerBase(ABC):
    """所有 Trigger 继承此类，实现 normalize() 将原始输入转为 TriggerEvent。"""

    source: str = "unknown"

    @abstractmethod
    def normalize(self, raw_input: Any) -> TriggerEvent:
        """将原始输入标准化为 TriggerEvent。"""
        ...

    def __repr__(self):
        return f"<{self.__class__.__name__} source={self.source}>"


# ── Chat Trigger ───────────────────────────────────────────

class ChatTrigger(TriggerBase):
    """交互式对话输入。"""

    source = "chat"

    def __init__(self, user_id: str = "jane"):
        self.user_id = user_id

    def normalize(self, raw_input: str) -> TriggerEvent:
        return TriggerEvent(
            source="chat",
            user_id=self.user_id,
            content=raw_input.strip() if raw_input else "",
        )


# ── CLI Trigger ────────────────────────────────────────────

class CLITrigger(TriggerBase):
    """命令行输入（main.py）。"""

    source = "cli"

    def normalize(self, raw_input: str) -> TriggerEvent:
        return TriggerEvent(
            source="cli",
            content=raw_input.strip() if raw_input else "",
        )


# ── Web Trigger ────────────────────────────────────────────

class WebTrigger(TriggerBase):
    """Web UI 输入（Streamlit）。"""

    source = "web"

    def __init__(self, user_id: str = "web_user"):
        self.user_id = user_id

    def normalize(self, raw_input: str, extra_context: Optional[Dict[str, Any]] = None) -> TriggerEvent:
        return TriggerEvent(
            source="web",
            user_id=self.user_id,
            content=raw_input.strip() if raw_input else "",
            context=extra_context or {},
        )


# ── File System Monitor Trigger ────────────────────────────

class FSMonitorTrigger(TriggerBase):
    """文件系统事件（folder_watcher）。"""

    source = "watcher"

    def normalize(self, event_type: str, file_paths: list, extra: Optional[Dict[str, Any]] = None) -> TriggerEvent:
        """将文件变更事件转为 TriggerEvent。

        Args:
            event_type: "files_added" | "files_deleted" | "files_changed"
            file_paths: 受影响的文件路径列表
            extra: 额外上下文
        """
        return TriggerEvent(
            source="watcher",
            content=event_type,
            context={
                "event_type": event_type,
                "file_paths": file_paths,
                **(extra or {}),
            },
        )
