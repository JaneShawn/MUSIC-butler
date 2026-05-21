# -*- coding: utf-8 -*-
"""意图路由节点 — 四级路由：L0命令映射 → L1关键词 → L2 LLM FC → L3 兜底"""
import json
import random
import re
from typing import Any, Dict, List, Optional

from graph.state import MusicAgentState
from core.emotion_constants import EMOTION_KEYWORDS, EMOTION_ALIAS, EMOTION_NAMES
from core.language_constants import LANGUAGE_ALIAS
from core.vector_store import EMBEDDING_MODELS
from chat.context import NLPUtils
from graph.utils import msg_content


_COMMAND_MAP = {
    "扫描": "scan", "scan": "scan",
    "帮助": "help", "help": "help", "功能": "help", "能做什么": "help",
    "退出": "exit", "exit": "exit", "再见": "exit", "quit": "exit",
    "清除": "clear", "清空": "clear", "886": "exit", "88": "exit",
    "播放全部": "play_all", "全部播放": "play_all",
    "语言检测": "show_language_stats", "语言分布": "show_language_stats",
    "语言统计": "show_language_stats", "有哪些语言": "show_language_stats",
    "情绪检测": "analyze_emotion", "情绪分布": "analyze_emotion",
    "清除情绪缓存": "clear_emotion_cache",
    "监控": "monitor", "monitor": "monitor",
}


def intent_router_node(state: MusicAgentState) -> Dict[str, Any]:
    """解析用户意图，路由到对应 Agent 节点"""
    result = _do_route(state)
    # 每轮对话必须清空 final_response，防止 MemorySaver 跨轮残留
    result.setdefault("final_response", "")
    result.setdefault("task_params", {})
    return result


def _do_route(state: MusicAgentState) -> Dict[str, Any]:
    """内部路由逻辑"""
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "respond", "agent_trace": ["intent_router: 无消息"]}

    last_msg = messages[-1]
    user_input = msg_content(last_msg).strip()

    # L0: 命令映射
    cmd = _COMMAND_MAP.get(user_input)
    if cmd:
        return {"intent": cmd, "agent_trace": [f"intent_router(L0): {cmd}"]}

    # ---- 确认/取消拦截（优先级高于关键词） ----
    pending = state.get("pending_action")
    if pending:
        confirm_words = ['确认', '确定', '是的', '执行', 'ok', 'yes', 'y']
        cancel_words = ['取消', '算了', 'no', 'n']
        if any(w in user_input for w in confirm_words):
            return {
                "intent": pending.get("action_type", "fix_metadata"),
                "task_params": {**pending.get("params", {}), "from_pending": True},
                "agent_trace": ["intent_router(confirm): pending action executed"],
            }
        if any(w in user_input for w in cancel_words):
            return {"intent": "cancel",
                    "agent_trace": ["intent_router(confirm): cancelled"]}

    # ---- 查询结果后的快捷上下文指令 ----
    query_results = state.get("query_results", [])
    if query_results:
        ctx_result = _handle_query_context(user_input, query_results, state)
        if ctx_result:
            return ctx_result

    user_input_lower = user_input.lower()

    # L1: 高频关键词拦截
    l1_result = _l1_intercept(user_input, user_input_lower)
    if l1_result:
        return l1_result

    # L2: LLM Function Calling
    l2_result = _llm_fc_route(user_input)
    if l2_result:
        return l2_result

    # L3: 生存兜底
    return _l3_fallback(user_input, user_input_lower)


def _l1_intercept(user_input: str, user_input_lower: str) -> Dict[str, Any]:
    """L1: 关键词硬编码拦截"""
    trace_prefix = "intent_router(L1)"

    # 批量情绪分析
    if any(p in user_input for p in ["分析情绪", "情绪分析", "情绪识别"]):
        if not re.search(r'分析.+?的.?情绪', user_input):
            force = any(w in user_input for w in ["重新", "强制", "刷新", "更新"])
            return {"intent": "analyze_emotion", "task_params": {"force": force},
                    "agent_trace": [f"{trace_prefix}: analyze_emotion"]}

    # 监控控制
    if any(w in user_input for w in ["开启监控", "启动监控", "打开监控", "开始监控"]):
        return {"intent": "monitor", "task_params": {"action": "start"},
                "agent_trace": [f"{trace_prefix}: monitor_start"]}
    if any(w in user_input for w in ["关闭监控", "停止监控", "关掉监控"]):
        return {"intent": "monitor", "task_params": {"action": "stop"},
                "agent_trace": [f"{trace_prefix}: monitor_stop"]}

    # 语言/情绪统计
    if any(w in user_input for w in ["语言检测", "语言分布", "语言统计", "有哪些语言", "什么语言"]):
        return {"intent": "show_language_stats", "task_params": {},
                "agent_trace": [f"{trace_prefix}: show_language_stats"]}
    if any(w in user_input for w in ["情绪检测", "情绪分布", "情绪统计"]):
        if not re.search(r'分析.+?的.?情绪', user_input):
            return {"intent": "analyze_emotion", "task_params": {},
                    "agent_trace": [f"{trace_prefix}: analyze_emotion"]}

    # 诊断/修复
    if any(w in user_input for w in ["诊断元数据", "元数据诊断", "检查元数据"]):
        return {"intent": "diagnose", "task_params": {},
                "agent_trace": [f"{trace_prefix}: diagnose"]}
    if any(w in user_input for w in ["同步情绪缓存", "同步情绪"]):
        return {"intent": "sync_emotion", "task_params": {},
                "agent_trace": [f"{trace_prefix}: sync_emotion"]}
    if any(w in user_input for w in ["一键修复", "修复元数据问题", "批量修复元数据"]):
        return {"intent": "fix_metadata_issues", "task_params": {},
                "agent_trace": [f"{trace_prefix}: fix_metadata_issues"]}

    # 查看歌单
    if any(w in user_input for w in ["查看歌单", "我的歌单", "歌单列表"]):
        return {"intent": "list_playlists", "task_params": {},
                "agent_trace": [f"{trace_prefix}: list_playlists"]}

    return None


def _llm_fc_route(user_input: str) -> Dict[str, Any]:
    """L2: LLM Function Calling 意图识别"""
    try:
        from graph.utils import load_config
        from core.kimi_client import KimiClient
        from chat.tool_registry import ToolRegistry

        kimi = KimiClient(config=load_config())
        messages = [
            {"role": "system", "content": ToolRegistry.build_system_prompt()},
            {"role": "user", "content": user_input},
        ]

        response = kimi.chat_completion(
            messages=messages,
            tools=ToolRegistry.get_tools(),
            tool_choice="auto",
            temperature=0.1,
            max_tokens=300,
        )

        tool_calls = response.get("tool_calls")
        if not tool_calls or len(tool_calls) == 0:
            return {"intent": "respond", "task_params": {"query": user_input},
                    "agent_trace": ["intent_router(L2): respond (no tool)"]}

        tc = tool_calls[0]
        func = tc.get("function", {})
        intent_name = func.get("name", "respond")

        try:
            params = json.loads(func.get("arguments", "{}"))
        except (json.JSONDecodeError, TypeError):
            params = {}

        if intent_name not in ToolRegistry.get_tool_names():
            intent_name = "respond"

        return {"intent": intent_name, "task_params": params,
                "agent_trace": [f"intent_router(L2): {intent_name}"]}

    except Exception:
        return None


def _l3_fallback(user_input: str, user_input_lower: str) -> Dict[str, Any]:
    """L3: 生存兜底 — LLM 不可用时的纯关键词匹配"""
    trace_prefix = "intent_router(L3)"

    if any(w in user_input_lower for w in ["exit", "quit", "退出", "再见"]):
        return {"intent": "exit", "task_params": {},
                "agent_trace": [f"{trace_prefix}: exit"]}

    if any(w in user_input_lower for w in ["扫描", "scan", "更新"]):
        return {"intent": "scan", "task_params": {},
                "agent_trace": [f"{trace_prefix}: scan"]}

    if any(w in user_input for w in ["帮助", "help", "能做什么", "功能"]):
        return {"intent": "help", "task_params": {},
                "agent_trace": [f"{trace_prefix}: help"]}

    if any(w in user_input for w in ["清除", "清空", "重置"]):
        return {"intent": "clear", "task_params": {},
                "agent_trace": [f"{trace_prefix}: clear"]}

    if any(phrase in user_input for phrase in ["播放全部", "播放所有", "全部播放", "所有歌曲"]):
        return {"intent": "play_all", "task_params": {},
                "agent_trace": [f"{trace_prefix}: play_all"]}

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
                        return {"intent": "play_by_artist", "task_params": {"artist": potential},
                                "agent_trace": [f"{trace_prefix}: play_by_artist"]}
                    return {"intent": "play_by_name", "task_params": {"song_name": potential},
                            "agent_trace": [f"{trace_prefix}: play_by_name"]}
        return {"intent": "query", "task_params": {"query": user_input},
                "agent_trace": [f"{trace_prefix}: query"]}

    # 情绪查询
    is_emotion = any(w in user_input for w in ["哪些", "有什么", "推荐", "歌", "歌曲"])
    detected_emotion = None
    for keyword, emotion in NLPUtils.EMOTION_KEYWORDS.items():
        if keyword in user_input:
            if keyword == "舞曲" and "小步舞曲" in user_input:
                continue
            detected_emotion = emotion
            break
    if is_emotion and detected_emotion:
        return {"intent": "query_emotion_songs", "task_params": {"emotion": detected_emotion},
                "agent_trace": [f"{trace_prefix}: query_emotion_songs"]}

    # 语言查询
    language_keywords = {
        "韩语": "韩语", "韩文": "韩语", "日语": "日语", "日文": "日语",
        "英语": "英语", "英文": "英语", "欧美": "英语",
        "国语": "国语", "普通话": "国语", "中文": "国语",
        "粤语": "粤语", "广东话": "粤语",
    }
    is_lang = any(w in user_input for w in ["哪些", "那些", "有什么", "列出", "显示", "推荐", "找"])
    detected_lang = None
    for keyword, lang in language_keywords.items():
        if keyword in user_input:
            detected_lang = lang
            break
    if detected_lang and is_lang:
        return {"intent": "query_language_songs", "task_params": {"language": detected_lang},
                "agent_trace": [f"{trace_prefix}: query_language_songs"]}

    # 查询
    if any(w in user_input for w in ["查询", "搜索", "找", "有哪些"]):
        return {"intent": "query", "task_params": {"query": user_input},
                "agent_trace": [f"{trace_prefix}: query"]}

    # 模型管理
    if any(w in user_input for w in ["模型", "embedding", "向量"]):
        if any(w in user_input for w in ["切换", "更换", "换"]):
            return {"intent": "list_models", "task_params": {},
                    "agent_trace": [f"{trace_prefix}: list_models"]}
        elif any(w in user_input for w in ["列表", "有哪些"]):
            return {"intent": "list_models", "task_params": {},
                    "agent_trace": [f"{trace_prefix}: list_models"]}
        elif any(w in user_input for w in ["当前", "现在"]):
            return {"intent": "current_model", "task_params": {},
                    "agent_trace": [f"{trace_prefix}: current_model"]}

    # 闲聊兜底
    return {"intent": "respond", "task_params": {"query": user_input},
            "agent_trace": [f"{trace_prefix}: respond"]}


def _handle_query_context(
    user_input: str, query_results: List[Dict[str, Any]], state: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """处理查询结果后的快捷上下文指令：数字选择、播放全部、随机、多选等"""
    n = len(query_results)
    u = user_input.strip()

    # 纯数字 → 播放对应索引
    if u.isdigit():
        idx = int(u) - 1
        if 0 <= idx < n:
            pending_fix = state.get("pending_action")
            if pending_fix and pending_fix.get("action_type") == "fix_single":
                return {
                    "intent": "fix_single",
                    "task_params": {"from_query": True, "force": True, "selected_idx": idx},
                    "agent_trace": ["intent_router(context): fix_single by index"],
                }
            return {
                "intent": "play",
                "task_params": {"item": query_results[idx]},
                "agent_trace": ["intent_router(context): play by index"],
            }

    # "第N" 或 "第N首"
    m = re.match(r'^第(\d+)首?$', u)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < n:
            return {
                "intent": "play",
                "task_params": {"item": query_results[idx]},
                "agent_trace": ["intent_router(context): play by index"],
            }

    # 中文序数词："第一首"、"第二首" 等
    ordinal_map = {
        "第一": 1, "第二": 2, "第三": 3, "第四": 4, "第五": 5,
        "第六": 6, "第七": 7, "第八": 8, "第九": 9, "第十": 10,
    }
    for word, num in ordinal_map.items():
        if u == word or u == word + "首" or u == word + "个":
            idx = num - 1
            if 0 <= idx < n:
                return {
                    "intent": "play",
                    "task_params": {"item": query_results[idx]},
                    "agent_trace": ["intent_router(context): play by ordinal"],
                }

    # "首个"
    if u == "首个":
        return {
            "intent": "play", "task_params": {"item": query_results[0]},
            "agent_trace": ["intent_router(context): play first"],
        }

    # "最后" / "末尾"
    if u in ("最后", "末尾"):
        return {
            "intent": "play", "task_params": {"item": query_results[-1]},
            "agent_trace": ["intent_router(context): play last"],
        }

    # "这首" / "它" / "这个"
    if u in ("这首", "它", "这个"):
        return {
            "intent": "play", "task_params": {"item": query_results[0]},
            "agent_trace": ["intent_router(context): play this"],
        }

    # "播放" / "播" → 播放全部结果
    if u in ("播放", "播"):
        return {
            "intent": "play_all_results",
            "task_params": {"items": query_results},
            "agent_trace": ["intent_router(context): play all results"],
        }

    # "播放这N首" / "播放全部" / "播放所有" / "全部播放" → 播放全部结果
    if re.match(r'^播放?(这|全部|所有|这些|这几|这[一二三四五六七八九十\d]+首?)?$', u) or \
       u in ("播放这些", "播放全部", "播放所有", "全都播放", "全播了", "都播", "这些都播"):
        return {
            "intent": "play_all_results",
            "task_params": {"items": query_results},
            "agent_trace": ["intent_router(context): play all results"],
        }

    # "播放这五首" / "播这三首" 等 — 中文数字+首
    m = re.match(r'^播放?这?([一二三四五六七八九十百\d]+)首$', u)
    if m:
        cn_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                  '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
        raw = m.group(1)
        count = cn_map.get(raw) or (int(raw) if raw.isdigit() else None)
        if count:
            items = query_results[:min(count, n)]
            return {
                "intent": "play_all_results",
                "task_params": {"items": items},
                "agent_trace": ["intent_router(context): play N results"],
            }

    # "随机来一首" 等 → 随机选一首播放
    if u in ("随机来一首", "随机一首", "随机播放", "随机来一个", "随机播", "来一首随机的"):
        return {
            "intent": "play",
            "task_params": {"item": random.choice(query_results)},
            "agent_trace": ["intent_router(context): random play"],
        }

    # "除了第N首都播放" → 排除指定序号后播放其余
    m = re.match(r'除了第?(\d+)首?(?:都?播放?|全部播放)?$', u)
    if m:
        exclude = int(m.group(1)) - 1
        if 0 <= exclude < n:
            keep = [query_results[i] for i in range(n) if i != exclude]
            return {
                "intent": "play_all_except",
                "task_params": {"songs": keep, "excluded": exclude},
                "agent_trace": ["intent_router(context): play all except"],
            }

    # 多选语法解析
    multi_indices = _parse_multi_select(user_input, n)
    if multi_indices is not None and len(multi_indices) > 0:
        return {
            "intent": "batch_select",
            "task_params": {"indices": multi_indices},
            "agent_trace": ["intent_router(context): batch select"],
        }

    return None


def _parse_multi_select(user_input: str, total_count: int) -> Optional[List[int]]:
    """解析多选索引，支持多种语法。返回选中的 0-based 索引列表，如果不是多选语法则返回 None"""
    text = user_input.strip().lower()

    # 1. "全部" / "所有" / "都"
    if text in ("全部", "所有", "都", "all"):
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
                indices.append(int(part) - 1)
        if indices and all(0 <= i < total_count for i in indices):
            return indices

    # 4. 空格/逗号分隔 "1 2 3" / "1,2,3"
    if ',' in text or (len(text.split()) > 1 and all(p.isdigit() for p in text.split())):
        parts = text.replace(',', ' ').split()
        indices = []
        for p in parts:
            if p.isdigit():
                indices.append(int(p) - 1)
        if indices and all(0 <= i < total_count for i in indices):
            return indices

    # 5. "前N首" / "前N个"
    fm = re.match(r'前(\d+)[首个]', text)
    if fm:
        n = int(fm.group(1))
        return list(range(min(n, total_count)))

    # 6. "第一首和第二首" 等中文序数
    ordinal_map = {
        "第一": 1, "第二": 2, "第三": 3, "第四": 4, "第五": 5,
        "第六": 6, "第七": 7, "第八": 8, "第九": 9, "第十": 10,
    }
    if any(ord in text for ord in ordinal_map):
        indices = []
        for word, idx in ordinal_map.items():
            if word in text:
                indices.append(idx - 1)
        if indices and all(0 <= i < total_count for i in indices):
            return indices

    return None
