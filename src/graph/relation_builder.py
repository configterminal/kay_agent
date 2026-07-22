"""
关系构建 — 幂等创建 Neo4j 中的树形、技能和知识点层级关系。

所有函数使用 Cypher MERGE，可重复调用不产生重复边。
"""

from __future__ import annotations

import logging
from typing import Any

from src.config import config
from src.graph.client import get_driver

logger = logging.getLogger(__name__)


def _run_cypher(cypher: str, **params: Any) -> list[dict[str, Any]]:
    driver = get_driver()
    with driver.session(database=config.neo4j.database) as session:
        result = session.run(cypher, **params)
        return [dict(r) for r in result]


# ── 树形关系 ────────────────────────────────────────

def build_tree_relations(course_infos: list[dict[str, Any]]) -> int:
    """
    Course → Chapter → Section 树形关系。

    返回：创建的关系数
    """
    count = 0

    for info in course_infos:
        cid = str(info.get("course_id") or "").strip()
        for i, ch in enumerate(info.get("chapters", [])):
            cc = str(ch.get("cc") or "").strip()
            if not cc:
                continue
            ch_id = f"{cid}_{cc}"

            cypher_ch = """
            MATCH (c:Course {id: $course_id})
            MATCH (ch:Chapter {id: $chapter_id})
            MERGE (c)-[r:HAS_CHAPTER]->(ch)
              ON CREATE SET r.order = $order
            RETURN type(r) AS rel
            """
            r = _run_cypher(
                cypher_ch, course_id=cid, chapter_id=ch_id, order=i + 1
            )
            if r:
                count += 1

            for j, sec in enumerate(ch.get("sections", [])):
                section = str(sec.get("section") or "").strip()
                if not section:
                    continue
                sec_id = f"{cid}_{section}"

                cypher_sec = """
                MATCH (ch:Chapter {id: $chapter_id})
                MATCH (s:Section {id: $section_id})
                MERGE (ch)-[r:HAS_SECTION]->(s)
                  ON CREATE SET r.order = $order
                RETURN type(r) AS rel
                """
                r2 = _run_cypher(
                    cypher_sec, chapter_id=ch_id, section_id=sec_id, order=j + 1
                )
                if r2:
                    count += 1

    logger.info("树形关系: %d", count)
    return count


# ── 知识点关系 ──────────────────────────────────────

def build_knowledge_point_relations(
    section_infos: list[dict[str, Any]],
) -> int:
    """
    Section → KnowledgePoint 关系。

    返回：创建的关系数
    """
    count = 0

    for sec in section_infos:
        sec_id = str(sec.get("section_id") or "").strip()
        for i, kp in enumerate(sec.get("kps", [])):
            kp_idx = int(kp.get("kp_index", 0))
            kp_id = f"{sec_id}_kp{kp_idx}"

            cypher = """
            MATCH (s:Section {id: $section_id})
            MATCH (kp:KnowledgePoint {kp_id: $kp_id})
            MERGE (s)-[r:HAS_KNOWLEDGE_POINT]->(kp)
              ON CREATE SET r.order = $order
            RETURN type(r) AS rel
            """
            r = _run_cypher(
                cypher, section_id=sec_id, kp_id=kp_id, order=i + 1
            )
            if r:
                count += 1

    logger.info("KP 关系: %d", count)
    return count


# ── 技能关系 ────────────────────────────────────────

def build_skill_relations(
    section_infos: list[dict[str, Any]],
    roles_data: dict[str, Any],
) -> int:
    """
    TEACHES (Section→Skill), REQUIRES (Role→Skill), BELONGS_TO (KP→Skill)。

    返回：创建的关系数
    """
    count = 0

    # 收集每个 section 的 skills（来自 module.json）
    section_skills: dict[str, list[str]] = {}
    for sec in section_infos:
        sec_id = str(sec.get("section_id") or "").strip()
        skills = sec.get("skills", [])
        if isinstance(skills, list) and skills:
            section_skills[sec_id] = [str(s) for s in skills]

    # TEACHES: Section → Skill
    for sec_id, skill_names in section_skills.items():
        for skill_name in skill_names:
            cypher = """
            MATCH (s:Section {id: $section_id})
            MATCH (sk:Skill {name: $skill_name})
            MERGE (s)-[r:TEACHES]->(sk)
            RETURN type(r) AS rel
            """
            r = _run_cypher(cypher, section_id=sec_id, skill_name=skill_name)
            if r:
                count += 1

    # REQUIRES: Role → Skill
    for sm in roles_data.get("skill_mappings", []):
        role_id = str(sm.get("role_id") or "").strip()
        skill_name = str(sm.get("skill_name") or "").strip()
        importance = "required" if sm.get("is_required") else "preferred"
        if not role_id or not skill_name:
            continue

        cypher = """
        MATCH (r:Role {id: $role_id})
        MATCH (sk:Skill {name: $skill_name})
        MERGE (r)-[req:REQUIRES]->(sk)
          ON CREATE SET req.importance = $importance
        RETURN type(req) AS rel
        """
        r = _run_cypher(
            cypher, role_id=role_id, skill_name=skill_name, importance=importance
        )
        if r:
            count += 1

    # BELONGS_TO: KnowledgePoint → Skill
    # 反向推导：Section 教某 Skill → 其下所有 KP 都属于该 Skill
    for sec_id, skill_names in section_skills.items():
        for skill_name in skill_names:
            cypher = """
            MATCH (s:Section {id: $section_id})-[:HAS_KNOWLEDGE_POINT]->(kp:KnowledgePoint)
            MATCH (sk:Skill {name: $skill_name})
            MERGE (kp)-[r:BELONGS_TO]->(sk)
            RETURN count(r) AS cnt
            """
            r = _run_cypher(
                cypher, section_id=sec_id, skill_name=skill_name
            )
            if r:
                count += int(r[0].get("cnt", 0))

    logger.info("技能关系: %d", count)
    return count


# ── EXPANDS 关系 ────────────────────────────────────

def build_expan_relations(expan_data: dict[str, list[dict[str, str]]]) -> int:
    """
    KnowledgePoint → KnowledgePoint 的 EXPANDS 关系。

    参数：
        expan_data: {section_id: [{source_kp_id, target_kp_id}, ...]}

    返回：创建的关系数
    """
    count = 0

    for sec_id, pairs in expan_data.items():
        for pair in pairs:
            source = str(pair.get("source_kp_id") or "").strip()
            target = str(pair.get("target_kp_id") or "").strip()
            if not source or not target:
                continue

            cypher = """
            MATCH (src:KnowledgePoint {kp_id: $source_id})
            MATCH (tgt:KnowledgePoint {kp_id: $target_id})
            MERGE (src)-[r:EXPANDS]->(tgt)
            RETURN type(r) AS rel
            """
            rr = _run_cypher(cypher, source_id=source, target_id=target)
            if rr:
                count += 1

    logger.info("EXPANDS 关系: %d", count)
    return count
