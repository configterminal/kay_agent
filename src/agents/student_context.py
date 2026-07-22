"""
将会话中的 student_id 注入工具，避免 Agent 向学员追问 ID。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import create_model


def bind_student_id(tool: Any, student_id: int) -> Any:
    """
    包装需 student_id 的工具：调用时强制填入当前登录学员，并从 LLM 可见参数中去掉该字段。
    """
    sid = int(student_id or 0)
    name = getattr(tool, "name", None) or "tool"
    description = getattr(tool, "description", "") or name
    schema = getattr(tool, "args_schema", None)
    if schema is None:
        return tool

    fields = getattr(schema, "model_fields", None) or {}
    if "student_id" not in fields:
        return tool

    base_fields: dict[str, Any] = {}
    for fname, finfo in fields.items():
        if fname == "student_id":
            continue
        ann = finfo.annotation
        if finfo.is_required():
            base_fields[fname] = (ann, ...)
        else:
            default = finfo.default
            # PydanticUndefined → None 默认
            try:
                from pydantic_core import PydanticUndefined
                if default is PydanticUndefined:
                    base_fields[fname] = (ann, None)
                else:
                    base_fields[fname] = (ann, default)
            except Exception:
                base_fields[fname] = (ann, None)

    BoundArgs = create_model(f"{name}_StudentBound", **base_fields)

    def _run(**kwargs: Any) -> Any:
        payload = dict(kwargs)
        payload["student_id"] = sid
        return tool.invoke(payload)

    return StructuredTool.from_function(
        func=_run,
        name=name,
        description=(
            f"{description}\n"
            f"（系统已绑定当前登录学员 student_id={sid}，禁止向学员询问学员 ID。）"
        ),
        args_schema=BoundArgs,
    )


def bind_tools_student_id(tools: list, student_id: int) -> list:
    """批量注入 student_id。"""
    return [bind_student_id(t, student_id) for t in tools]


def student_id_context_prefix(student_id: int) -> str:
    """拼进 Agent 输入的会话头，防止模型向学员要 ID。"""
    sid = int(student_id or 0)
    return (
        f"[当前登录学员 student_id={sid}]\n"
        f"所有需要 student_id 的工具已由系统绑定为 {sid}；"
        f"禁止向学员询问、确认或索要学员 ID / student_id。\n\n"
    )
