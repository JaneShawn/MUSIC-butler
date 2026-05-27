# -*- coding: utf-8 -*-
"""
Hermes Architecture — 三层主干 + 一圈闭环

  Trigger → Gateway → Agent Loop → Reflect ↺

Phase 1: Trigger 层（统一输入标准化）
Phase 2: Gateway 层（纯 LLM 路由网关）
Phase 3: Agent Loop 层（全部 ReAct agent）
Phase 4: Reflect 闭环（记忆 + 技能反哺 Gateway）
"""
from hermes.trigger import TriggerEvent, TriggerBase
from hermes.trigger import ChatTrigger, CLITrigger, WebTrigger, FSMonitorTrigger
from hermes.gateway import HermesGateway, RouteDecision
from hermes.memory import MemoryStore, get_memory_store, Memory
from hermes.skill import SkillStore, get_skill_store, Skill
from hermes.reflect import ReflectEngine

__all__ = [
    "TriggerEvent", "TriggerBase",
    "ChatTrigger", "CLITrigger", "WebTrigger", "FSMonitorTrigger",
    "HermesGateway", "RouteDecision",
    "MemoryStore", "get_memory_store", "Memory",
    "SkillStore", "get_skill_store", "Skill",
    "ReflectEngine",
]
