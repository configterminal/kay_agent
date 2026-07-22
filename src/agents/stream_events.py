"""Chat / Supervisor 流式事件回调（ContextVar）。

SSE 路径注入回调后：probe/decide/dispatch 发 status，Agent LLM 发 token。
非流式路径不设回调，行为与原来一致。
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable
from typing import Any

# 回调签名：接收可 JSON 序列化的 dict（含 type 字段）
StreamCallback = Callable[[dict[str, Any]], None]

_stream_cb: contextvars.ContextVar[StreamCallback | None] = contextvars.ContextVar(
    "chat_stream_cb",
    default=None,
)


def has_stream_callback() -> bool:
    """当前上下文是否处于 SSE 流式。"""
    return _stream_cb.get() is not None


def set_stream_callback(cb: StreamCallback | None):
    """设置当前上下文的流式回调，返回 token 供 reset。"""
    return _stream_cb.set(cb)


def reset_stream_callback(token) -> None:
    """恢复 ContextVar。"""
    _stream_cb.reset(token)


def emit_stream_event(event: dict[str, Any]) -> None:
    """若当前有回调则发送事件；无回调则忽略。"""
    cb = _stream_cb.get()
    if cb is None:
        return
    try:
        cb(event)
    except Exception:
        # 流式回调失败不得打断主链路
        pass


def emit_status(phase: str, detail: str, *, agent: str = "") -> None:
    """发送阶段状态（前端配字）。"""
    payload: dict[str, Any] = {
        "type": "status",
        "phase": phase,
        "detail": detail,
    }
    if agent:
        payload["agent"] = agent
    emit_stream_event(payload)


def emit_token(text: str) -> None:
    """发送正文增量。"""
    if not text:
        return
    emit_stream_event({"type": "token", "text": text})


def chunk_text(chunk) -> str:
    """从 AIMessageChunk / str 提取纯文本 delta。"""
    if chunk is None:
        return ""
    if isinstance(chunk, str):
        return chunk
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif hasattr(block, "text"):
                parts.append(str(getattr(block, "text") or ""))
        return "".join(parts)
    return ""


def chunk_has_tool_calls(chunk) -> bool:
    """工具调用增量不向学员展示。"""
    if chunk is None:
        return False
    if getattr(chunk, "tool_call_chunks", None):
        return True
    tool_calls = getattr(chunk, "tool_calls", None)
    if tool_calls:
        return True
    return False
