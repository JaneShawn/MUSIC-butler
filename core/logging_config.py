"""
单一日志配置 — 所有 core/ 和 agents/ 模块统一使用 logger，替代 print()。
支持 LOG_LEVEL 环境变量控制输出级别。
"""
import logging
import os
import sys

_log_configured = False
_loggers = {}


def get_logger(name: str) -> logging.Logger:
    """惰性返回模块级 logger。首次调用时配置 root logger。"""
    global _log_configured
    if not _log_configured:
        level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(level)
        root.handlers.clear()
        root.addHandler(handler)
        _log_configured = True

    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)
    return _loggers[name]
