"""
上下文预算 — 摘要 + 近窗组 prompt，禁止全量 messages 进子 Agent。

对齐 .specify/specs/memory.md「上下文预算」。
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


# ── 话题块存储（会话内话题回溯检索）────────────────────

THREAD_BLOCKS_NAMESPACE = "thread_blocks"
THREAD_BLOCKS_MAX = 10
THREAD_BLOCKS_TTL_SECONDS = 30 * 24 * 3600  # 30 天


def _thread_blocks_keys(student_id: int, thread_id: str) -> list[str]:
    """构造话题块 Store key 命名空间。"""
    return ["students", str(student_id), THREAD_BLOCKS_NAMESPACE, thread_id]


def save_thread_block(
    student_id: int,
    thread_id: str,
    topic: str,
    summary: str,
    start_msg_index: int,
    end_msg_index: int,
    message_count: int,
    time_range: str,
) -> str | None:
    """
    保存一个对话主题块到 Store。

    Key: students:{id}:thread_blocks:{thread_id}
    blocks 列表最多保留 THREAD_BLOCKS_MAX 个（超过则丢弃最旧的）。
    Redis key 设 30 天 TTL。
    不阻塞主链路（调用方 catch 异常）。

    返回 block_id，失败返回 None。
    """
    tid = (thread_id or "").strip()
    if not tid or not student_id:
        return None

    from datetime import datetime, timezone

    store = get_store()
    keys = _thread_blocks_keys(student_id, tid)
    data = store.get(keys) or {}
    blocks: list[dict] = data.get("blocks") or []

    # 生成 block_id（使用当前块数）
    block_id = f"block_{len(blocks) + 1}"
    now = datetime.now(timezone.utc).isoformat()

    block = {
        "block_id": block_id,
        "topic": (topic or "").strip() or "未命名话题",
        "summary": (summary or "").strip(),
        "start_msg_index": start_msg_index,
        "end_msg_index": end_msg_index,
        "message_count": message_count,
        "time_range": time_range,
        "created_at": now,
    }

    blocks.append(block)

    # 超过上限则丢弃最旧的
    if len(blocks) > THREAD_BLOCKS_MAX:
        blocks = blocks[-THREAD_BLOCKS_MAX:]

    store.put(keys, {"blocks": blocks})

    # 设 TTL（Redis 原生 key expiry）
    try:
        from redis.commands.json.path import Path
        raw_key = store._make_key(keys)
        store._client.expire(raw_key, THREAD_BLOCKS_TTL_SECONDS)
    except Exception:
        pass

    logger.info(
        "保存话题块 student=%s thread=%s block_id=%s topic=%s messages=%d",
        student_id, tid, block_id, block["topic"], message_count,
    )
    return block_id


def get_thread_blocks(
    student_id: int,
    thread_id: str,
) -> list[dict]:
    """读取某个会话的全部话题块。"""
    tid = (thread_id or "").strip()
    if not tid or not student_id:
        return []
    data = get_store().get(_thread_blocks_keys(student_id, tid)) or {}
    return list(data.get("blocks") or [])


def list_thread_topics_store(
    student_id: int,
    thread_id: str,
) -> list[str]:
    """列出某个会话的话题标题列表。"""
    blocks = get_thread_blocks(student_id, thread_id)
    return [b.get("topic", "") for b in blocks]


def _extract_topic_from_messages(messages: list) -> str:
    """用 LLM 从消息中提取话题名（<=15 字）。失败回退返回 '未命名话题'。"""
    from src.llm.base import LLMProvider

    transcript = _format_messages_for_summary(messages)
    if not transcript.strip():
        return "未命名话题"

    prompt = (
        "请为以下对话片段提取一个简短中文话题名（不超过15字）：\n"
        f"{transcript}\n"
        "只输出话题名，不要多余内容。"
    )
    try:
        model = LLMProvider.create().get_model(temperature=0)
        resp = model.invoke(prompt)
        topic = (getattr(resp, "content", None) or str(resp)).strip()
        if len(topic) > 15:
            topic = topic[:15]
        return topic or "未命名话题"
    except Exception as e:
        logger.warning("话题提取 LLM 失败: %s", e)
        return "未命名话题"


def search_thread_blocks_store(
    student_id: int,
    thread_id: str,
    query: str,
    top_k: int = 3,
    time_range: str = "recent",
) -> list[dict]:
    """
    从 Store 检索历史话题块。

    使用 Redis FT.SEARCH 全文匹配 topic + summary 字段。
    回退方案：Python 层面关键词匹配。
    """
    tid = (thread_id or "").strip()
    q = (query or "").strip()
    if not tid or not student_id or not q:
        return []

    store = get_store()
    keys = _thread_blocks_keys(student_id, tid)
    raw_key = store._make_key(keys)

    # 优先用 RediSearch 全文检索
    try:
        index_name = store._index_name(f"{THREAD_BLOCKS_NAMESPACE}_{student_id}")
        _ensure_thread_blocks_index(store, student_id)
        # FT.SEARCH 用 @topic:@summary: 联合查询
        escaped = q.replace(" ", "|")
        ft_query = f"(@topic:{escaped})|(@summary:{escaped})"
        result = store._client.ft(index_name).search(ft_query)
        docs = []
        for doc in result.docs:
            if doc.id == raw_key and hasattr(doc, "json") and doc.json:
                import json as _json
                payload = _json.loads(doc.json)
                all_blocks = payload.get("blocks") or []
                # 排序：匹配到的块靠近 top_k
                for blk in all_blocks:
                    blk_topic = (blk.get("topic") or "").lower()
                    blk_summary = (blk.get("summary") or "").lower()
                    q_lower = q.lower()
                    if q_lower in blk_topic or q_lower in blk_summary:
                        blk["source_thread"] = tid
                        docs.append(blk)
                break  # 只有一个文档 key
        if docs:
            return docs[:top_k]
    except Exception as e:
        logger.debug("RediSearch 检索话题块失败，回退 Python 匹配: %s", e)

    # 回退方案：Python 层面关键词匹配
    blocks = get_thread_blocks(student_id, tid)
    if not blocks:
        return []

    scored: list[tuple[int, dict]] = []
    q_lower = q.lower()
    q_terms = q_lower.split()

    for blk in blocks:
        blk_topic = (blk.get("topic") or "").lower()
        blk_summary = (blk.get("summary") or "").lower()
        score = 0
        # 完整查询命中权重更高
        if q_lower in blk_topic:
            score += 10
        if q_lower in blk_summary:
            score += 5
        # 分词命中
        for term in q_terms:
            if term in blk_topic:
                score += 2
            if term in blk_summary:
                score += 1
        if score > 0:
            blk["source_thread"] = tid
            scored.append((score, blk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:top_k]]


def delete_thread_blocks_store(
    student_id: int,
    thread_id: str,
    before_days: int | None = None,
) -> int:
    """
    删除会话话题块。

    before_days=None 删除全部；否则删除 N 天前创建的块。
    返回删除数量。
    """
    tid = (thread_id or "").strip()
    if not tid or not student_id:
        return 0

    store = get_store()
    keys = _thread_blocks_keys(student_id, tid)

    if before_days is None:
        # 删除全部
        if not store.exists(keys):
            return 0
        old_blocks = get_thread_blocks(student_id, tid)
        count = len(old_blocks)
        store.delete(keys)
        logger.info("已删除全部话题块 student=%s thread=%s count=%d", student_id, tid, count)
        return count

    # 按时间删除
    blocks = get_thread_blocks(student_id, tid)
    if not blocks:
        return 0

    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=before_days)

    kept: list[dict] = []
    deleted = 0
    for blk in blocks:
        created_str = blk.get("created_at") or ""
        try:
            created = datetime.fromisoformat(created_str)
        except (ValueError, TypeError):
            kept.append(blk)
            continue
        if created < cutoff:
            deleted += 1
        else:
            kept.append(blk)

    if deleted > 0:
        if kept:
            store.put(keys, {"blocks": kept})
        else:
            store.delete(keys)
        logger.info(
            "已删除 %d 个话题块 student=%s thread=%s before_days=%s",
            deleted, student_id, tid, before_days,
        )

    return deleted


def _ensure_thread_blocks_index(store, student_id: int) -> None:
    """
    为指定学员的 thread_blocks 数据建立 RediSearch 索引。

    索引名: idx:students:thread_blocks_{student_id}
    索引范围: students:{student_id}:thread_blocks:* key 前缀
    索引字段: topic, summary 使用 TEXT 索引
    """
    namespace = f"{THREAD_BLOCKS_NAMESPACE}_{student_id}"
    index_name = store._index_name(namespace)
    try:
        store._client.execute_command("FT.INFO", index_name)
    except Exception:
        # 索引不存在，创建
        key_prefix = f"students:{student_id}:{THREAD_BLOCKS_NAMESPACE}:"
        store._client.execute_command(
            "FT.CREATE", index_name,
            "ON", "JSON",
            "PREFIX", "1", key_prefix,
            "SCHEMA",
            "$.blocks[*].topic", "AS", "topic", "TEXT",
            "$.blocks[*].summary", "AS", "summary", "TEXT",
        )


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


# ── 对话垃圾桶（软删除 / 恢复 / 彻底清除）────────────

_TRASH_NAMESPACE = "trash"


def _trash_keys(student_id: int) -> list[str]:
    """垃圾桶 Store key 命名空间。"""
    return ["students", str(student_id), _TRASH_NAMESPACE]


def trash_thread(student_id: int, thread_id: str) -> bool:
    """标记 thread 为已删除（软删除）。存到 Store students:{id}:trash。"""
    tid = (thread_id or "").strip()
    if not tid or not student_id:
        return False

    from datetime import datetime, timezone

    store = get_store()
    keys = _trash_keys(student_id)
    data = store.get(keys) or {}
    thread_ids: set[str] = set(data.get("thread_ids") or [])
    if tid in thread_ids:
        return False  # 已在垃圾桶中
    thread_ids.add(tid)

    trashed_at = data.get("trashed_at") or {}
    trashed_at[tid] = datetime.now(timezone.utc).isoformat()

    store.put(keys, {"thread_ids": sorted(thread_ids), "trashed_at": trashed_at})
    logger.info("已标记删除 student=%s thread=%s", student_id, tid)
    return True


def restore_thread(student_id: int, thread_id: str) -> bool:
    """从垃圾桶恢复 thread。"""
    tid = (thread_id or "").strip()
    if not tid or not student_id:
        return False
    store = get_store()
    keys = _trash_keys(student_id)
    data = store.get(keys) or {}
    thread_ids: set[str] = set(data.get("thread_ids") or [])
    if tid not in thread_ids:
        return False  # 不在垃圾桶中
    thread_ids.discard(tid)
    trashed_at = data.get("trashed_at") or {}
    trashed_at.pop(tid, None)
    if thread_ids:
        store.put(keys, {"thread_ids": sorted(thread_ids), "trashed_at": trashed_at})
    else:
        store.delete(keys)
    logger.info("已恢复 student=%s thread=%s", student_id, tid)
    return True


def is_thread_trashed(student_id: int, thread_id: str) -> bool:
    """检查 thread 是否在垃圾桶中。"""
    tid = (thread_id or "").strip()
    if not tid or not student_id:
        return False
    data = get_store().get(_trash_keys(student_id)) or {}
    return tid in set(data.get("thread_ids") or [])


def get_trashed_thread_ids(student_id: int) -> set[str]:
    """获取学员所有垃圾桶中的 thread_id 列表。"""
    if not student_id:
        return set()
    data = get_store().get(_trash_keys(student_id)) or {}
    return set(data.get("thread_ids") or [])


def purge_thread(student_id: int, thread_id: str) -> dict:
    """
    彻底删除：清除 thread_blocks + summary + trash 标记。

    返回 {"blocks": int, "summary": bool} 计数。
    """
    tid = (thread_id or "").strip()
    if not tid or not student_id:
        return {"blocks": 0, "summary": False}

    result = {"blocks": 0, "summary": False}

    # 1) 删除话题块
    try:
        block_count = delete_thread_blocks_store(student_id, tid)
        result["blocks"] = block_count
    except Exception as e:
        logger.warning("purge 删除 thread_blocks 失败 student=%s thread=%s: %s", student_id, tid, e)

    # 2) 删除滚动摘要
    try:
        delete_thread_summary(student_id, tid)
        result["summary"] = True
    except Exception as e:
        logger.warning("purge 删除 summary 失败 student=%s thread=%s: %s", student_id, tid, e)

    # 3) 从垃圾桶移除标记
    try:
        store = get_store()
        keys = _trash_keys(student_id)
        data = store.get(keys) or {}
        thread_ids: set[str] = set(data.get("thread_ids") or [])
        thread_ids.discard(tid)
        if thread_ids:
            trashed_at = data.get("trashed_at") or {}
            trashed_at.pop(tid, None)
            store.put(keys, {"thread_ids": sorted(thread_ids), "trashed_at": trashed_at})
        else:
            store.delete(keys)
    except Exception as e:
        logger.warning("purge 移除 trash 标记失败 student=%s thread=%s: %s", student_id, tid, e)

    logger.info(
        "已彻底删除 student=%s thread=%s blocks=%d summary=%s",
        student_id, tid, result["blocks"], result["summary"],
    )
    return result
