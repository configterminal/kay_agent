"""
RAG 检索器 — 完整流水线主控。

组装查询重写 → 混合检索 → 重排序 → 结果处理四个阶段，
返回可直接喂给 LLM 的文档内容和来源标注。

使用方式：
    from src.vectordb.retriever import retrieve
    results = retrieve("RAG的检索模块怎么工作的", chat_history=[...], course_id="RAG101")
    # → [{content, source, score, section, title, is_web_search}, ...]
"""

import logging
import re
import time
from typing import Any

from src.perf import log_timing
from src.vectordb.hybrid_search import hybrid_search
from src.vectordb.query_rewriter import rewrite_query
from src.vectordb.reranker import get_reranker
from src.vectordb.schema import COLLECTION_NAME, ensure_collection, get_client

logger = logging.getLogger(__name__)

# 相关性阈值：低于此分数视为无关结果
_SCORE_THRESHOLD = 0.3

# 章目录名：02 标题…
_CHAPTER_DIR_RE = re.compile(r"^(?P<cc>\d{2})\s+(?P<title>.+)$")


# ── 父文档查询 ────────────────────────────────────

def _get_parent_contents_batch(parent_ids: list[str]) -> dict[str, str]:
    """批量获取父文档内容（一次 Milvus 查询）。"""
    if not parent_ids:
        return {}
    result_map: dict[str, str] = {}
    try:
        client = get_client()
        ensure_collection()
        # Milvus filter: id in ["a", "b", ...]
        id_list = ", ".join(f'"{pid}"' for pid in parent_ids)
        results = client.query(
            collection_name=COLLECTION_NAME,
            filter=f"id in [{id_list}]",
            output_fields=["id", "content"],
            limit=len(parent_ids),
        )
        for row in results:
            row_id = row.get("id")
            if row_id:
                result_map[str(row_id)] = str(row.get("content") or "")
    except Exception as e:
        logger.warning("批量获取父文档失败: %s", e)
    return result_map


# ── 来源格式化 ────────────────────────────────────

def _format_time(sec: int) -> str:
    """秒 → M:SS 或 H:MM:SS。"""
    if sec < 0:
        return ""
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _format_source(doc: dict[str, Any]) -> str:
    """格式化文档来源；章号解析目录名前缀，有 start_sec 时附带时间点。"""
    chapter_raw = str(doc.get("chapter") or "").strip()
    m = _CHAPTER_DIR_RE.match(chapter_raw)
    if m:
        ch_label = f"第{m.group('cc')}章"
    else:
        ch_label = chapter_raw or "未知章节"
    section = doc.get("section", "")
    title = doc.get("title", "")
    course_id = str(doc.get("course_id") or "").strip()
    prefix = f"[{course_id}] " if course_id else ""
    base = f"{prefix}课程 {ch_label} 第{section}节《{title}》"
    start = doc.get("start_sec", -1)
    if isinstance(start, int) and start >= 0:
        return f"{base} @{_format_time(start)}"
    return base


# ── 主入口 ────────────────────────────────────────

def retrieve(
    query: str,
    chat_history: list[str] | None = None,
    top_k: int = 5,
    reranker: Any | None = None,
    course_id: str | None = None,
    course_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    RAG 完整检索流水线。

    参数：
        query: 学员原始问题
        chat_history: 最近对话历史（供查询重写的指代消解使用）
        top_k: 最终返回的文档数
        reranker: 外部传入的 Reranker 实例（由 lifespan 预加载）
        course_id: 单课作用域（主路 Soft/Hard/Profile）
        course_ids: 多课作用域（类比路）

    返回：
        [{content, source, score, section, title, is_web_search}, ...]
    """
    if chat_history is None:
        chat_history = []

    t_all = time.perf_counter()

    # ── ① 查询重写 ────────────────────────────────
    t = time.perf_counter()
    try:
        queries = rewrite_query(query, chat_history)
    except Exception as e:
        logger.warning("查询重写失败，使用原始查询: %s", e)
        queries = [query]
    log_timing("rag.rewrite", time.perf_counter() - t, n_queries=len(queries or []))

    if not queries:
        queries = [query]

    # ── ② 混合检索 ────────────────────────────────
    t = time.perf_counter()
    try:
        candidates = hybrid_search(
            queries,
            top_k=50,
            rrf_top_k=20,
            course_id=course_id,
            course_ids=course_ids,
        )
    except Exception as e:
        logger.warning("混合检索失败: %s", e)
        candidates = []
    log_timing(
        "rag.hybrid",
        time.perf_counter() - t,
        n_cand=len(candidates),
        course_id=course_id or "",
    )

    if not candidates:
        log_timing("rag.retrieve.total", time.perf_counter() - t_all, result="fallback")
        return _web_search_fallback(query)

    # ── ③ 重排序 ──────────────────────────────────
    t = time.perf_counter()
    try:
        if reranker is None:
            reranker = get_reranker()
        top_docs = reranker.rerank(query, candidates, top_k=top_k)
    except Exception as e:
        logger.warning("重排序失败，使用原始排分: %s", e)
        candidates.sort(key=lambda x: x.get("_original_score", 0), reverse=True)
        top_docs = candidates[:top_k]
    log_timing("rag.rerank", time.perf_counter() - t, n_out=len(top_docs))

    # 有课内作用域时：取 TopK 后按 section 升序，便于跟课表讲
    if course_id or course_ids:
        top_docs = sorted(top_docs, key=lambda d: str(d.get("section") or ""))

    # ── ④ 结果处理 ────────────────────────────────
    t = time.perf_counter()

    # 批量获取父文档（一次 Milvus 查询，替代逐条 query）
    parent_ids = list({d.get("parent_id") for d in top_docs if d.get("parent_id")})
    parent_map = _get_parent_contents_batch(parent_ids) if parent_ids else {}

    results = []
    for doc in top_docs:
        parent_id = doc.get("parent_id")
        full_content = parent_map.get(parent_id) if parent_id else None

        content = full_content or doc.get("content", "")
        score = doc.get("rerank_score", doc.get("_original_score", 0))

        if score < _SCORE_THRESHOLD:
            continue

        results.append({
            "content": content,
            "source": _format_source(doc),
            "score": round(score, 4),
            "section": doc.get("section", ""),
            "title": doc.get("title", ""),
            "course_id": doc.get("course_id", "") or "",
            "start_sec": int(doc.get("start_sec", -1) or -1),
            "end_sec": int(doc.get("end_sec", -1) or -1),
            "media_path": doc.get("media_path", "") or "",
            "is_web_search": False,
            "kp_title": doc.get("kp_title", "") or "",
            "kp_summary": doc.get("kp_summary", "") or "",
            "kp_index": int(doc.get("kp_index", -1) or -1),
            "key_points": doc.get("key_points", "") or "",
        })
    log_timing("rag.parent_expand", time.perf_counter() - t, n_keep=len(results))

    log_timing(
        "rag.retrieve.total",
        time.perf_counter() - t_all,
        n_keep=len(results),
    )
    if results:
        return results

    return _web_search_fallback(query)


# ── WebSearch 兜底（暂未实现）────────────────────

def _web_search_fallback(query: str) -> list[dict[str, Any]]:
    """
    RAG 无结果时 WebSearch 兜底。

    当前降级为提示信息，后续接入搜索 API。
    """
    return [{
        "content": f"关于「{query}」，当前课程资料中没有相关内容，"
                   "且网络搜索功能尚未接入。请稍后再试或换个问题。",
        "source": "系统提示",
        "score": 0.0,
        "section": "",
        "title": "",
        "course_id": "",
        "start_sec": -1,
        "end_sec": -1,
        "media_path": "",
        "is_web_search": True,  # 走兜底链路，当前降级为提示，后续接入真实搜索 API
    }]
