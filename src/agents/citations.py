"""
课程来源 citations — 从 search_course_content 工具结果抽出跳转字段。

路径与秒数只来自检索，不由 LLM 编造。
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

SEARCH_TOOL_NAME = "search_course_content"

# 选项续聊时 Supervisor 改写 input 的前缀模式
_OPTION_INPUT_RE = re.compile(
    r"学员选择了选项\s*\d+[：:]\s*(.+?)。\s*请基于该选项",
    re.DOTALL,
)


def _encode_resource_path(path: str) -> str:
    """相对 resources/ 的路径 → 分段 URL 编码。"""
    rel = (path or "").replace("\\", "/").strip().lstrip("/")
    if not rel:
        return ""
    parts = [p for p in rel.split("/") if p and p != ".."]
    if not parts:
        return ""
    return "/".join(quote(p, safe="") for p in parts)


def build_media_url(media_path: str) -> str:
    """相对 resources/ 的路径 → /media/...（分段 URL 编码）。"""
    encoded = _encode_resource_path(media_path)
    return f"/media/{encoded}" if encoded else ""


def build_captions_url(media_path: str) -> str:
    """相对 resources/ 的 mp4 → /captions/...vtt。"""
    encoded = _encode_resource_path(media_path)
    return f"/captions/{encoded}" if encoded else ""


def _parse_tool_payload(content: Any) -> list[dict]:
    """解析 ToolMessage.content 为文档 dict 列表。"""
    if isinstance(content, list):
        return [x for x in content if isinstance(x, dict)]
    if isinstance(content, dict):
        return [content]
    if not isinstance(content, str):
        return []
    text = content.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def doc_to_citation_raw(doc: dict) -> dict | None:
    """检索/工具文档 → citation 原始字段；无视频跳转则 None。"""
    if doc.get("is_web_search") or doc.get("source") == "系统提示":
        return None
    path = str(doc.get("media_path") or "")
    start = int(doc.get("start_sec", -1) if doc.get("start_sec") is not None else -1)
    if not path or start < 0:
        return None
    return {
        "source": str(doc.get("source") or ""),
        "score": float(doc.get("score") or 0.0),
        "section": str(doc.get("section") or ""),
        "title": str(doc.get("title") or ""),
        "start_sec": start,
        "end_sec": int(doc.get("end_sec", -1) if doc.get("end_sec") is not None else -1),
        "media_path": path,
        "kp_title": str(doc.get("kp_title") or ""),
        "kp_summary": str(doc.get("kp_summary") or ""),
        "kp_index": int(doc.get("kp_index", -1) if doc.get("kp_index") is not None else -1),
    }


def build_qa_search_query(task_input: str) -> str:
    """QA 检索用词：选项续聊时用选项正文，否则用学员 input。"""
    text = (task_input or "").strip()
    m = _OPTION_INPUT_RE.search(text)
    if m:
        return m.group(1).strip()
    return text


def chat_history_for_rewrite(messages: list) -> list[str]:
    """供 retrieve 查询重写的最近对话摘要行。"""
    lines: list[str] = []
    for msg in messages or []:
        if isinstance(msg, HumanMessage):
            content = (msg.content or "").strip()
            if content:
                lines.append(f"学员: {content}")
        elif isinstance(msg, AIMessage):
            content = (msg.content or "").strip()
            if content:
                lines.append(f"助教: {content[:300]}")
    return lines[-6:]


def citations_from_retrieve_results(docs: list[dict]) -> list[dict]:
    """retrieve() 结果 → 规范化 citations（仅含可跳转视频）。"""
    raw: list[dict] = []
    for doc in docs or []:
        item = doc_to_citation_raw(doc)
        if item:
            raw.append(item)
    return normalize_citations(raw)


def merge_citation_lists(*groups: list[dict]) -> list[dict]:
    """合并多路 citations（已规范化或未规范化均可），去重保序。"""
    raw: list[dict] = []
    for group in groups:
        for item in group or []:
            if not isinstance(item, dict):
                continue
            raw.append({
                "source": str(item.get("source") or ""),
                "score": float(item.get("score") or 0.0),
                "section": str(item.get("section") or ""),
                "title": str(item.get("title") or ""),
                "start_sec": int(item.get("start_sec", -1) if item.get("start_sec") is not None else -1),
                "end_sec": int(item.get("end_sec", -1) if item.get("end_sec") is not None else -1),
                "media_path": str(item.get("media_path") or ""),
                "kp_title": str(item.get("kp_title") or ""),
                "kp_summary": str(item.get("kp_summary") or ""),
                "kp_index": int(
                    item.get("kp_index", -1) if item.get("kp_index") is not None else -1
                ),
            })
    return normalize_citations(raw)


def ensure_qa_citations(
    task_input: str,
    chat_history: list | None,
    agent_messages: list | None,
    course_id: str | None = None,
) -> list[dict]:
    """
    QA 每轮主 citations：从 Agent 工具调用结果中提取。

    Prompt 已强制每轮调搜索工具，不再做 dispatch 强检索（避免重复）。
    course_id 仅用于日志标注，不影响提取逻辑。
    """
    import time

    from src.perf import log_timing

    t0 = time.perf_counter()
    tool_citations = extract_citations_from_messages(agent_messages or [])
    log_timing(
        "qa.ensure_citations",
        time.perf_counter() - t0,
        tool_n=len(tool_citations),
        merged_n=len(tool_citations),
        course_id=course_id or "",
    )
    return tool_citations


def fetch_analogy_citations(
    task_input: str,
    chat_history: list | None,
    student_id: int,
    focus_course_id: str | None,
    top_k: int = 3,
) -> list[dict]:
    """
    类比路：在 enrolled 的其他课中检索相近片段（独立于主 citations）。
    """
    import time

    from src.agents.course_scope import analogy_course_ids
    from src.perf import log_timing
    from src.vectordb.retriever import retrieve

    focus = (focus_course_id or "").strip()
    if not focus:
        return []
    others = analogy_course_ids(student_id, focus)
    if not others:
        return []

    t0 = time.perf_counter()
    search_query = build_qa_search_query(task_input)
    if not search_query:
        return []
    hist = chat_history_for_rewrite(chat_history or [])
    try:
        docs = retrieve(
            search_query,
            chat_history=hist,
            top_k=top_k,
            course_ids=others,
        )
        cites = citations_from_retrieve_results(docs)
    except Exception:
        cites = []
    # 标记类比（前端可用 source 前缀区分；字段保持兼容）
    for c in cites:
        src = str(c.get("source") or "")
        if not src.startswith("类比·"):
            c["source"] = f"类比·{src}"
    log_timing(
        "qa.analogy_citations",
        time.perf_counter() - t0,
        n=len(cites),
        focus=focus,
        others=",".join(others),
    )
    return cites


def extract_citations_from_messages(messages: list) -> list[dict]:
    """从本轮 Agent messages 抽取检索 citations（含 media_url）。"""
    raw: list[dict] = []
    for msg in messages or []:
        if not isinstance(msg, ToolMessage):
            continue
        name = (getattr(msg, "name", None) or "").strip()
        docs = _parse_tool_payload(msg.content)
        if not docs:
            continue
        looks_like_search = any(
            "media_path" in d or "start_sec" in d or ("source" in d and "score" in d)
            for d in docs
        )
        if name and name != SEARCH_TOOL_NAME:
            continue
        if not name and not looks_like_search:
            continue
        for doc in docs:
            # 整份工具文档交给 doc_to_citation_raw，避免丢掉 kp_* 字段
            item = doc_to_citation_raw(doc if isinstance(doc, dict) else {})
            if item:
                raw.append(item)
    return normalize_citations(raw)


def normalize_citations(raw: list[dict]) -> list[dict]:
    """按 score 降序，(media_path, start_sec, kp_index) 去重，并补 media_url。"""
    seen: set[tuple[str, int, int]] = set()
    items: list[dict] = []
    for item in sorted(raw, key=lambda x: float(x.get("score") or 0), reverse=True):
        path = str(item.get("media_path") or "")
        start = int(item.get("start_sec", -1) if item.get("start_sec") is not None else -1)
        kp_index = int(
            item.get("kp_index", -1) if item.get("kp_index") is not None else -1
        )
        # 同秒不同知识点靠 kp_index 区分；无 kp 时仍按 path+start 去重
        key = (path, start, kp_index)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "source": str(item.get("source") or ""),
            "score": round(float(item.get("score") or 0.0), 4),
            "section": str(item.get("section") or ""),
            "title": str(item.get("title") or ""),
            "start_sec": start,
            "end_sec": int(item.get("end_sec", -1) if item.get("end_sec") is not None else -1),
            "media_path": path,
            "media_url": build_media_url(path),
            "captions_url": build_captions_url(path),
            "kp_title": str(item.get("kp_title") or ""),
            "kp_summary": str(item.get("kp_summary") or ""),
            "kp_index": kp_index,
        })
    return items
