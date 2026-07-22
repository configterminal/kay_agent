"""
EXPANDS 关系推断 — LLM 节内 KP 层级判断。

每次调用处理一节的 KP（3-10 个），判断哪些是概述、哪些是展开。
全量 122 节约 ¥0.50，结果可缓存到 Neo4j。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from src.llm.base import LLMProvider
from src.perf import log_timing

logger = logging.getLogger(__name__)

# ── Prompt ──────────────────────────────────────────

_EXPANDS_SYSTEM = """你是课程知识结构分析专家。一节视频课讲一个主题，其中包含若干知识点。
有些知识点是对本节主题的**概述/引入**，有些是概述的**具体展开/详细讲解**。

分析每个知识点的角色，输出它们之间的展开关系：
- "overview"：本节概述/引入/总览型知识点
- "detail"：具体讲解某个子主题的细节型知识点
- "expands"：overview → detail 的展开关系

规则：
1. 每节通常有 1-2 个 overview，其余是 detail
2. 不是所有 detail 都直接来自 overview——有些 detail 是独立的知识点
3. 只输出**确定性高**的关系，不确定的不输出
4. 严格 JSON 数组格式输出"""

_EXPANDS_USER = """课程：{course_title}
章节：{chapter_title}
节：{section_title}

知识点列表：
{kp_list}

分析每个知识点的角色（overview/detail），并输出概述→展开的关系。
输出 JSON 数组：
[{{"kp_index": 0, "role": "overview"}},
 {{"kp_index": 1, "role": "detail"}},
 {{"source_kp_index": 0, "target_kp_index": 1}}, ...]"""


# ── 格式化 ──────────────────────────────────────────

def _format_kp_list(kps: list[dict[str, Any]]) -> str:
    """将 KP 列表格式化为 LLM 输入文本。"""
    lines = []
    for kp in kps:
        idx = kp.get("kp_index", "?")
        title = kp.get("kp_title", "")
        summary = kp.get("kp_summary", "")
        points = kp.get("key_points", [])
        if isinstance(points, list):
            pts_str = "; ".join(str(p) for p in points[:3])
        else:
            pts_str = str(points or "")
        lines.append(
            f"[{idx}] {title}\n"
            f"    摘要: {summary}\n"
            f"    要点: {pts_str}"
        )
    return "\n\n".join(lines)


# ── 推断 ────────────────────────────────────────────

def infer_expands_for_section(
    section_id: str,
    kps: list[dict[str, Any]],
    course_title: str = "",
    chapter_title: str = "",
    section_title: str = "",
) -> list[dict[str, str]]:
    """
    对一节的 KP 列表推断 EXPANDS 关系。

    参数：
        section_id: 节 ID（如 "RAG101_10-06"）
        kps: [{kp_index, kp_title, kp_summary, key_points}, ...]
        course_title, chapter_title, section_title: 上下文（提升 LLM 准确率）

    返回：
        [{source_kp_id, target_kp_id}, ...]
    """
    if len(kps) <= 1:
        return []

    llm = LLMProvider.create().get_model(temperature=0)
    prompt = _EXPANDS_USER.format(
        course_title=course_title or "",
        chapter_title=chapter_title or "",
        section_title=section_title or "",
        kp_list=_format_kp_list(kps),
    )

    try:
        response = llm.invoke([
            {"role": "system", "content": _EXPANDS_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        content = response.content.strip() if hasattr(response, 'content') else str(response).strip()
    except Exception as e:
        logger.warning("LLM 推断 EXPANDS 失败 %s: %s", section_id, e)
        return []

    # 解析 JSON
    try:
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            data = json.loads(content[start:end])
        else:
            return []
    except json.JSONDecodeError:
        logger.warning("EXPANDS JSON 解析失败: %s", section_id)
        return []

    # 构建结果：先解析 role，再匹配 source→target
    kp_roles: dict[int, str] = {}
    expan_pairs: list[dict[str, str]] = []

    for item in data:
        if not isinstance(item, dict):
            continue
        kp_idx = item.get("kp_index")
        role = item.get("role")
        source_idx = item.get("source_kp_index")
        target_idx = item.get("target_kp_index")

        if kp_idx is not None and role:
            kp_roles[int(kp_idx)] = str(role)
        elif source_idx is not None and target_idx is not None:
            src_kp_id = f"{section_id}_kp{int(source_idx)}"
            tgt_kp_id = f"{section_id}_kp{int(target_idx)}"
            expan_pairs.append({
                "source_kp_id": src_kp_id,
                "target_kp_id": tgt_kp_id,
            })

    # 如果 LLM 只给了 role 没给 pairs，自动推导 overview→detail
    if not expan_pairs and kp_roles:
        overviews = [i for i, r in kp_roles.items() if r == "overview"]
        details = [i for i, r in kp_roles.items() if r == "detail"]
        for ov in overviews:
            for dt in details:
                expan_pairs.append({
                    "source_kp_id": f"{section_id}_kp{ov}",
                    "target_kp_id": f"{section_id}_kp{dt}",
                })

    return expan_pairs


# ── 批量推断 ────────────────────────────────────────

def infer_expands_all(
    section_infos: list[dict[str, Any]],
    force: bool = False,
) -> dict[str, list[dict[str, str]]]:
    """
    对所有 section 推断 EXPANDS 关系。

    参数：
        section_infos: [{section_id, course_title, chapter_title, section_title, kps: [...]}, ...]
        force: True=全量重新推断；False=跳过已有 EXPANDS 的节

    返回：
        {section_id: [{source_kp_id, target_kp_id}, ...]}
    """
    result: dict[str, list[dict[str, str]]] = {}
    t_total = time.perf_counter()

    from src.graph.client import get_driver
    from src.config import config as cfg
    driver = get_driver()

    for sec in section_infos:
        sec_id = str(sec.get("section_id") or "").strip()
        kps = sec.get("kps", [])
        if not kps or len(kps) <= 1:
            continue

        # 检测是否已有 EXPANDS 关系（除非 force）
        if not force:
            cypher = """
            MATCH (:Section {id: $section_id})-[:HAS_KNOWLEDGE_POINT]->(:KnowledgePoint)-[e:EXPANDS]->(:KnowledgePoint)
            RETURN count(e) AS cnt
            """
            with driver.session(database=cfg.neo4j.database) as session:
                rr = session.run(cypher, section_id=sec_id)
                row = rr.single()
                if row and row.get("cnt", 0) > 0:
                    logger.debug("EXPANDS 跳过: %s", sec_id)
                    continue

        t_s = time.perf_counter()
        pairs = infer_expands_for_section(
            sec_id, kps,
            course_title=str(sec.get("course_title") or ""),
            chapter_title=str(sec.get("chapter_title") or ""),
            section_title=str(sec.get("section_title") or ""),
        )
        log_timing("graph.expands.llm", time.perf_counter() - t_s, section=sec_id, n_pairs=len(pairs))

        if pairs:
            result[sec_id] = pairs

    log_timing(
        "graph.expands.total",
        time.perf_counter() - t_total,
        n_sections=len(result),
    )
    return result
