"""
Graph Retriever — Neo4j 知识图谱检索。

按问题类型路由到图检索通路，用于关系型查询：
  - "X 和 Y 有什么区别"
  - "学 A 之前要掌握什么"
  - "哪些章节教了 B"

返回格式与 retrieve() 一致，兼容 citations 和前端。

使用方式：
    from src.graph.retriever import graph_search
    results = graph_search("Graph RAG 和 RAG 有什么区别", top_k=5)
"""

from __future__ import annotations

import logging
import time
from typing import Any

import jieba

from src.config import config
from src.graph.client import check_connection, get_driver
from src.perf import log_timing

logger = logging.getLogger(__name__)

# ── 关键词提取 ─────────────────────────────────────

def _extract_keywords(query: str, max_keywords: int = 8, min_len: int = 1) -> list[str]:
    """从查询中提取关键词（jieba 分词，去重保序，取最长的）。"""
    tokens = [t.strip() for t in jieba.cut(query) if len(t.strip()) >= min_len]
    seen: set[str] = set()
    unique: list[str] = []
    for t in sorted(tokens, key=len, reverse=True):
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique[:max_keywords]


# ── 内容组装 ───────────────────────────────────────

def _compose_content(kp: dict[str, Any]) -> str:
    """从 KP 元数据组装 content（无需回查 Milvus）。"""
    parts: list[str] = []
    title = str(kp.get("kp_title") or "").strip()
    summary = str(kp.get("kp_summary") or "").strip()
    key_points = str(kp.get("key_points") or "").strip()
    if title:
        parts.append(f"【{title}】")
    if summary:
        parts.append(summary)
    if key_points:
        parts.append(f"关键要点: {key_points}")
    return "\n".join(parts)


# ── 来源格式化 ─────────────────────────────────────

def _format_kp_source(doc: dict[str, Any]) -> str:
    """从图结果格式化来源字符串。"""
    course_id = str(doc.get("course_id") or "")
    chapter_title = str(doc.get("chapter") or "")
    section_num = str(doc.get("section") or "")
    sec_title = str(doc.get("title") or "")
    start_sec = int(doc.get("start_sec", -1) if doc.get("start_sec") is not None else -1)

    # 解析章号
    import re
    ch_label = chapter_title
    ch_m = re.match(r"^(?P<cc>\d{2})\s+(?P<title>.+)$", chapter_title)
    if ch_m:
        ch_label = f"第{ch_m.group('cc')}章"

    prefix = f"[{course_id}] " if course_id else ""
    base = f"{prefix}课程 {ch_label} 第{section_num}节《{sec_title}》"
    if start_sec >= 0:
        sec = int(start_sec)
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        ts = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
        return f"{base} @{ts}"
    return base


# ── Cypher 查询构建 ────────────────────────────────

def _build_course_filter(course_id: str | None, course_ids: list[str] | None) -> tuple[str, dict[str, Any]]:
    """构建 course 过滤子句和参数。"""
    if course_ids:
        ids = [str(c).strip() for c in course_ids if str(c).strip()]
        if len(ids) == 1:
            return "AND kp.course_id = $course_id", {"course_id": ids[0]}
        return "AND kp.course_id IN $course_ids", {"course_ids": ids}
    if course_id:
        return "AND kp.course_id = $course_id", {"course_id": str(course_id).strip()}
    return "", {}


# ── 主入口 ─────────────────────────────────────────

def graph_search(
    query: str,
    top_k: int = 5,
    course_id: str | None = None,
    course_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Neo4j 图检索 — 用于关系型查询。

    返回格式与 retrieve() 一致（14 个字段），可直接喂给 citations 和前端。

    参数：
        query: 学员问题
        top_k: 返回结果数
        course_id / course_ids: 课程作用域过滤
    """
    ok, _msg = check_connection()
    if not ok:
        logger.warning("Neo4j 不可达，图检索跳过")
        return []

    t_all = time.perf_counter()

    # ── 关键词提取 ──
    t_kw = time.perf_counter()
    keywords = _extract_keywords(query)
    log_timing("graph.search.extract_kw", time.perf_counter() - t_kw, n_kw=len(keywords))
    if not keywords:
        return []

    cypher_clause, cypher_params = _build_course_filter(course_id, course_ids)

    # 共享的 RETURN + ORDER 片段
    tail = f"""
        OPTIONAL MATCH (kp)<-[:HAS_KNOWLEDGE_POINT]-(s:Section)
        OPTIONAL MATCH (s)<-[:HAS_SECTION]-(ch:Chapter)
        OPTIONAL MATCH (ch)<-[:HAS_CHAPTER]-(c:Course)
        RETURN kp,
               s.id AS section_id, s.title AS section_title,
               s.media_path AS media_path, s.section AS section_num,
               ch.id AS chapter_id, ch.title AS chapter_title,
               c.id AS course_id_val, c.title AS course_title
        ORDER BY kp.kp_index ASC
        LIMIT $top_k
    """

    # 路径 A：kp_title + kp_summary 匹配
    t_a = time.perf_counter()
    raw_a: list[dict[str, Any]] = []
    for kw in keywords[:5]:
        try:
            driver = get_driver()
            with driver.session(database=config.neo4j.database) as session:
                cypher = f"""
                MATCH (kp:KnowledgePoint)
                WHERE (kp.kp_title CONTAINS $keyword OR kp.kp_summary CONTAINS $keyword)
                  {cypher_clause}
                {tail}
                """
                params = {"keyword": kw, "top_k": top_k, **cypher_params}
                result = session.run(cypher, **params)
                for record in result:
                    raw_a.append(dict(record))
        except Exception as e:
            logger.warning("图检索 kp_title 匹配失败: %s", e)
    log_timing("graph.search.kp_match", time.perf_counter() - t_a, n_kw=len(keywords[:5]), n_hit=len(raw_a))

    # 路径 B：Skill name 匹配 → 展开 KP
    t_b = time.perf_counter()
    raw_b: list[dict[str, Any]] = []
    for kw in keywords[:5]:
        try:
            driver = get_driver()
            with driver.session(database=config.neo4j.database) as session:
                cypher = f"""
                MATCH (sk:Skill)
                WHERE sk.name CONTAINS $keyword
                MATCH (sk)<-[:BELONGS_TO]-(kp:KnowledgePoint)
                {cypher_clause.replace('kp.course_id', 'kp.course_id')}
                {tail}
                """
                params = {"keyword": kw, "top_k": top_k, **cypher_params}
                result = session.run(cypher, **params)
                for record in result:
                    raw_b.append(dict(record))
        except Exception as e:
            logger.warning("图检索 Skill 匹配失败: %s", e)
    log_timing("graph.search.skill_match", time.perf_counter() - t_b, n_kw=len(keywords[:5]), n_hit=len(raw_b))

    # 合并去重（按 kp.kp_id）
    t_merge = time.perf_counter()
    seen_ids: set[str] = set()
    merged: list[dict[str, Any]] = []
    for rec in raw_a + raw_b:
        kp = rec.get("kp")
        if kp is None:
            continue
        kp_id = str(kp.get("kp_id") or "")
        if kp_id in seen_ids:
            continue
        seen_ids.add(kp_id)

        media_path = str(rec.get("media_path") or "")
        start_sec = int(kp.get("start_sec", -1) if kp.get("start_sec") is not None else -1)
        end_sec = int(kp.get("end_sec", -1) if kp.get("end_sec") is not None else -1)

        doc = {
            "content": _compose_content(kp),
            "source": "",  # 后面格式化
            "score": 0.85,
            "section": str(rec.get("section_num") or kp.get("section") or ""),
            "title": str(rec.get("section_title") or ""),
            "course_id": str(rec.get("course_id_val") or kp.get("course_id") or ""),
            "chapter": str(rec.get("chapter_title") or ""),
            "start_sec": start_sec,
            "end_sec": end_sec,
            "media_path": media_path,
            "is_web_search": False,
            "kp_title": str(kp.get("kp_title") or ""),
            "kp_summary": str(kp.get("kp_summary") or ""),
            "kp_index": int(kp.get("kp_index", -1) if kp.get("kp_index") is not None else -1),
            "key_points": str(kp.get("key_points") or ""),
        }
        doc["source"] = _format_kp_source(doc)
        merged.append(doc)

    # 按 kp_index 排序，截断
    merged.sort(key=lambda d: d["kp_index"])
    result = merged[:top_k]

    log_timing("graph.search.merge", time.perf_counter() - t_merge, n_merged=len(merged), n_out=len(result))

    log_timing(
        "graph.search",
        time.perf_counter() - t_all,
        n_kw=len(keywords),
        n_raw=len(raw_a) + len(raw_b),
        n_out=len(result),
        course_id=course_id or "",
    )
    return result
