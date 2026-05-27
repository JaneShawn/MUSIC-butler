# -*- coding: utf-8 -*-
"""
[DEPRECATED] Chat 包 — 旧对话系统的工具注册表和 NLP 工具类。

ToolRegistry → Phase 2 起由 hermes/gateway.py 的 GATEWAY_DISPATCH_SCHEMA 替代。
NLPUtils       → Phase 2 起不再被活跃代码引用（intent_router 已弃用）。

保留文件供参考，不建议新代码依赖此包。
"""
from .context import NLPUtils

__all__ = ["NLPUtils"]
