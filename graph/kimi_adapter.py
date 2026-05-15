# -*- coding: utf-8 -*-
"""KimiChatModel — 将现有 KimiClient 包装为 LangChain 兼容的 ChatModel"""
import json
from typing import Any, Dict, Iterator, List, Optional, Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel, generate_from_stream
from langchain_core.messages import (
    AIMessage, AIMessageChunk, BaseMessage, HumanMessage,
    SystemMessage, ToolCall, ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool

from core.kimi_client import KimiClient


class KimiChatModel(BaseChatModel):
    """LangChain 兼容的 Kimi API 聊天模型，复用现有 KimiClient。"""

    model: str = "moonshot-v1-8k"
    temperature: float = 0.7
    max_tokens: int = 1000
    _client: Optional[KimiClient] = None
    _bound_tools: Optional[List[BaseTool]] = None

    class Meta:
        abstract = True

    @property
    def _llm_type(self) -> str:
        return "kimi-chat"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {"model": self.model, "temperature": self.temperature}

    def _get_client(self) -> KimiClient:
        if self._client is None:
            from graph.utils import load_config
            self._client = KimiClient(config=load_config())
        return self._client

    def bind_tools(
        self,
        tools: Sequence[Any],
        **kwargs: Any,
    ) -> "KimiChatModel":
        """绑定工具到模型，返回新实例（LangGraph create_react_agent 必需）。"""
        normalized: List[BaseTool] = []
        for t in tools:
            if isinstance(t, BaseTool):
                normalized.append(t)
            elif hasattr(t, "name") and callable(getattr(t, "run", None)):
                normalized.append(t)
        # 不用 deepcopy — Pydantic v2 私有属性无法通过 deepcopy 保留
        cloned = KimiChatModel(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        # 共享同一个 KimiClient（无状态的 HTTP 客户端）
        cloned._client = self._client
        cloned._bound_tools = normalized
        return cloned

    def _convert_messages(self, messages: List[BaseMessage]) -> List[Dict[str, str]]:
        """将 LangChain 消息转换为 Kimi API 格式"""
        converted = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                converted.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                converted.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                entry: Dict[str, Any] = {"role": "assistant", "content": msg.content}
                if msg.tool_calls:
                    entry["tool_calls"] = []
                    for i, tc in enumerate(msg.tool_calls):
                        # 兼容 ToolCall 对象和 dict 两种格式
                        if isinstance(tc, dict):
                            tc_name = tc.get("name", tc.get("function", {}).get("name", ""))
                            tc_args = tc.get("args", {})
                            tc_id = tc.get("id", f"call_{i}")
                        else:
                            tc_name = getattr(tc, "name", "")
                            tc_args = getattr(tc, "args", {}) or {}
                            tc_id = getattr(tc, "id", f"call_{i}")
                        entry["tool_calls"].append({
                            "id": tc_id,
                            "type": "function",
                            "function": {
                                "name": tc_name,
                                "arguments": json.dumps(tc_args, ensure_ascii=False),
                            },
                        })
                converted.append(entry)
            elif isinstance(msg, ToolMessage):
                converted.append({"role": "tool", "content": msg.content,
                                  "tool_call_id": msg.tool_call_id})
        return converted

    def _convert_tools(self, tools: List[BaseTool]) -> List[Dict[str, Any]]:
        """将 LangChain 工具转为 OpenAI Function Calling 格式"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": _dict_schema_to_json_schema(tool.args_schema.schema()
                        if tool.args_schema else {"type": "object", "properties": {}}),
                },
            }
            for tool in tools
        ]

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        client = self._get_client()
        kimi_messages = self._convert_messages(messages)

        tools = kwargs.get("tools") or self._bound_tools
        if tools:
            kimi_tools = self._convert_tools(tools)
        else:
            kimi_tools = None

        response = client.chat_completion(
            messages=kimi_messages,
            tools=kimi_tools,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        content = response.get("content", "") or ""
        tool_calls_raw = response.get("tool_calls")

        additional_kwargs = {}
        langchain_tool_calls = []

        if tool_calls_raw:
            additional_kwargs["tool_calls"] = tool_calls_raw
            for tc in tool_calls_raw:
                func = tc.get("function", {})
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    args = {}
                langchain_tool_calls.append(
                    ToolCall(
                        name=func.get("name", ""),
                        args=args,
                        id=tc.get("id", ""),
                    )
                )

        # tool_calls 不接受 None，没有时传空列表
        ai_msg = AIMessage(
            content=content,
            additional_kwargs=additional_kwargs,
            tool_calls=langchain_tool_calls if langchain_tool_calls else [],
        )

        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        # Kimi API 不支持流式，回退到同步生成再模拟 chunk
        result = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        content = result.generations[0].message.content
        if run_manager and content:
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=content))
            run_manager.on_llm_new_token(content, chunk=chunk)
            yield chunk


def _dict_schema_to_json_schema(schema: dict) -> dict:
    """将 dict schema 转为 OpenAI tools parameters 格式，去除 $defs 等 meta key。"""
    result = {"type": "object", "properties": {}}
    props = schema.get("properties", {})
    for name, prop in props.items():
        result["properties"][name] = {
            k: v for k, v in prop.items() if k != "title"
        }
    if "required" in schema:
        result["required"] = schema["required"]
    return result
