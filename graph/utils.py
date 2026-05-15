# -*- coding: utf-8 -*-
"""Graph 通用工具函数"""


def msg_content(msg) -> str:
    """从 dict 或 LangChain BaseMessage 中安全提取文本内容。"""
    if isinstance(msg, dict):
        return msg.get("content", "") or ""
    return getattr(msg, "content", "") or ""


import yaml as _yaml
from pathlib import Path as _Path

_config = None


def load_config() -> dict:
    global _config
    if _config is None:
        config_path = _Path(__file__).resolve().parent.parent / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            _config = _yaml.safe_load(f)
    return _config
