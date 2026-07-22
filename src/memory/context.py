"""
上下文预算 — 摘要 + 近窗组 prompt，禁止全量 messages 进子 Agent。

对齐 docs/architecture/memory.md「上下文预算」。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.config import config
from src.memory.store import get_store

logger = logging.getLogger(__name__)


def _recent_message_limit() -> int:
    """近窗消息条数上限（一轮 ≈ 学员+助教两条）。"""
    return max(2, config.context.recent_turns * 2)


def _summaries_keys(student_id: int) -> list[str]:
    return ["students", str(student_id), "summaries"]


def get_thread_summary(student_id: int, thread_id: str) -> dict[str, Any] | None:
    """读取本会话滚动摘要；无则返回 None。"""
    tid = (thread_id or "").strip()
    if not tid or not student_id:
        return None
    data = get_store().get(_summaries_keys(student_id)) or {}
    by_thread = data.get("by_thread") or {}
    entry = by_thread.get(tid)
    return entry if isinstance(entry, dict) else None


def delete_thread_summary(student_id: int, thread_id: str) -> None:
    """删除会话时去掉该 thread 的摘要桶。"""
    tid = (thread_id or "").strip()
    if not tid or not student_id:
        return
    store = get_store()
    keys = _summaries_keys(student_id)
    data = store.get(keys) or {}
    by_thread = dict(data.get("by_thread") or {})
    if tid not in by_thread:
        return
    by_thread.pop(tid, None)
    store.put(keys, {"by_thread": by_thread})


def take_recent_messages(messages: list, recent_turns: int | None = None) -> list:
    """从全量历史中取最近 N 轮原文（不修改原列表）。"""
    if not messages:
        return []
    n = _recent_message_limit() if recent_turns is None else max(2, recent_turns * 2)
    return list(messages[-n:])


def build_agent_messages(
    all_messages: list,
    task_input: str,
    *,
    summary_text: str | None = None,
    recent_turns: int | None = None,
) -> list[BaseMessage]:
    """
    组装子 Agent 的 messages：可选摘要 + 近窗原文 + 本轮 input。

    会去掉近窗末尾的 HumanMessage，再追加 task_input，避免与改写后的本轮输入重复叠床架屋。
    """
    recent = take_recent_messages(all_messages, recent_turns=recent_turns)
    while recent and isinstance(recent[-1], HumanMessage):
        recent = recent[:-1]

    out: list[BaseMessage] = []
    text = (summary_text or "").strip()
    if text:
        max_chars = config.context.summary_max_chars
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        out.append(SystemMessage(
            content=(
                "【本会话更早内容摘要】（非本轮原文，仅供背景；"
                "指代与选项以近窗对话为准）\n"
                f"{text}"
            ),
        ))

    for msg in recent:
        # 只保留对话角色，避免把工具中间态整段塞进子 Agent
        if isinstance(msg, (HumanMessage, AIMessage, SystemMessage)):
            out.append(msg)

    out.append(HumanMessage(content=task_input))
    return out


def _format_messages_for_summary(messages: list) -> str:
    """把消息列表压成适合摘要的纯文本。"""
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "学员"
        elif isinstance(msg, AIMessage):
            role = "助教"
        else:
            continue
        content = getattr(msg, "content", "") or ""
        if isinstance(content, list):
            content = str(content)
        content = str(content).strip().replace("\n", " ")
        if len(content) > 400:
            content = content[:399] + "…"
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _llm_summarize(old_summary: str, transcript: str) -> str:
    """调用 LLM 生成滚动摘要；失败返回截断后的旧摘要或原文头。"""
    max_chars = config.context.summary_max_chars
    prompt = f"""请将以下学习助教对话压缩为简洁中文摘要，供后续轮次作为背景。
要求：
- 保留：讨论过的主题/知识点、学员倾向或未决选择、重要结论
- 不要逐句复述；不要编号任务列表；不超过 {max_chars} 字
- 只输出摘要正文

【已有摘要】
{old_summary or '（无）'}

【需并入的更早对话】
{transcript}
"""
    try:
        from src.llm.base import LLMProvider
        model = LLMProvider.create().get_model(temperature=0)
        resp = model.invoke(prompt)
        text = (getattr(resp, "content", None) or str(resp)).strip()
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        return text
    except Exception as e:
        logger.warning("会话摘要 LLM 失败，降级保留旧摘要: %s", e)
        fallback = (old_summary or transcript[:max_chars]).strip()
        return fallback[:max_chars]


def maybe_update_thread_summary(
    student_id: int,
    thread_id: str,
    messages: list,
) -> dict[str, Any] | None:
    """
    当全量 messages 超过阈值时，把「近窗之外」的内容滚进 Store.summaries。

    成功返回写入的 entry；跳过或失败返回 None。不阻塞主回复（调用方可忽略异常）。
    """
    tid = (thread_id or "").strip()
    if not tid or not student_id or not messages:
        return None

    trigger = config.context.summary_trigger_messages
    recent_n = _recent_message_limit()
    if len(messages) < trigger:
        return None
    if len(messages) <= recent_n:
        return None

    old_part = list(messages[:-recent_n])
    if not old_part:
        return None

    existing = get_thread_summary(student_id, tid) or {}
    covered = int(existing.get("source_message_count") or 0)
    if covered >= len(old_part):
        return None

    # 只摘要「尚未覆盖」的增量，减轻 token
    delta = old_part[covered:] if covered > 0 else old_part
    if not delta:
        return None

    transcript = _format_messages_for_summary(delta)
    if not transcript.strip():
        return None

    new_text = _llm_summarize(str(existing.get("text") or ""), transcript)
    entry = {
        "text": new_text,
        "source_message_count": len(old_part),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    store = get_store()
    keys = _summaries_keys(student_id)
    data = store.get(keys) or {}
    by_thread = dict(data.get("by_thread") or {})
    by_thread[tid] = entry
    store.put(keys, {"by_thread": by_thread})
    logger.info(
        "已更新会话摘要 student=%s thread=%s covered=%d chars=%d",
        student_id, tid, entry["source_message_count"], len(new_text),
    )
    return entry
