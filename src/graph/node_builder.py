"""
节点构建 — 幂等写入 Neo4j 的 Course / Chapter / Section / KnowledgePoint / Skill / Role 节点。

所有函数使用 Cypher MERGE，可重复调用不产生重复数据。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.config import config
from src.graph.client import get_driver

logger = logging.getLogger(__name__)


def _run_cypher(cypher: str, **params: Any) -> list[dict[str, Any]]:
    """执行单条 Cypher，返回记录列表。"""
    driver = get_driver()
    with driver.session(database=config.neo4j.database) as session:
        result = session.run(cypher, **params)
        return [dict(r) for r in result]


# ── Course ──────────────────────────────────────────

def build_course_nodes(course_infos: list[dict[str, Any]]) -> int:
    """
    从课程信息创建 Course 节点。

    参数：
        course_infos: [{course_id, title, tags, industry}, ...]
    返回：
        新创建或更新的节点数
    """
    count = 0
    for info in course_infos:
        cid = str(info.get("course_id") or "").strip()
        title = str(info.get("title") or "").strip()
        if not cid or not title:
            continue
        tags = info.get("tags", [])
        if isinstance(tags, list):
            tags_str = ", ".join(str(t) for t in tags)
        else:
            tags_str = str(tags or "")
        industry = str(info.get("industry") or "IT").strip() or "IT"

        cypher = """
        MERGE (c:Course {id: $id})
          ON CREATE SET c.title = $title, c.tags = $tags, c.industry = $industry
          ON MATCH  SET c.title = $title, c.tags = $tags, c.industry = $industry
        RETURN c.id AS id
        """
        result = _run_cypher(
            cypher, id=cid, title=title, tags=tags_str, industry=industry
        )
        if result:
            count += 1
            logger.debug("Course: %s", cid)
    logger.info("Course 节点: %d", count)
    return count


# ── Chapter / Section ───────────────────────────────

def build_chapter_section_nodes(
    course_infos: list[dict[str, Any]],
) -> tuple[int, int]:
    """
    从课程目录结构创建 Chapter 和 Section 节点。

    参数：
        course_infos: [{course_id, chapters: [{cc, title, sections: [{section, title, media_path}]}]}, ...]
    返回：
        (Chapter 数, Section 数)
    """
    ch_count = 0
    sec_count = 0

    for info in course_infos:
        cid = str(info.get("course_id") or "").strip()
        for ch in info.get("chapters", []):
            cc = str(ch.get("cc") or "").strip()
            ch_title = str(ch.get("title") or "").strip()
            if not cc or not ch_title:
                continue
            ch_id = f"{cid}_{cc}"

            cypher_ch = """
            MERGE (ch:Chapter {id: $id})
              ON CREATE SET ch.course_id = $course_id, ch.cc = $cc, ch.title = $title
              ON MATCH  SET ch.course_id = $course_id, ch.cc = $cc, ch.title = $title
            RETURN ch.id AS id
            """
            r = _run_cypher(
                cypher_ch, id=ch_id, course_id=cid, cc=cc, title=ch_title
            )
            if r:
                ch_count += 1

            for sec in ch.get("sections", []):
                section = str(sec.get("section") or "").strip()
                sec_title = str(sec.get("title") or "").strip()
                if not section or not sec_title:
                    continue
                sec_id = f"{cid}_{section}"
                media_path = str(sec.get("media_path") or "")

                cypher_sec = """
                MERGE (s:Section {id: $id})
                  ON CREATE SET s.course_id = $course_id, s.section = $section,
                                s.title = $title, s.media_path = $media_path
                  ON MATCH  SET s.course_id = $course_id, s.section = $section,
                                s.title = $title, s.media_path = $media_path
                RETURN s.id AS id
                """
                r2 = _run_cypher(
                    cypher_sec,
                    id=sec_id, course_id=cid, section=section,
                    title=sec_title, media_path=media_path,
                )
                if r2:
                    sec_count += 1

    logger.info("Chapter: %d, Section: %d", ch_count, sec_count)
    return ch_count, sec_count


# ── KnowledgePoint ──────────────────────────────────

def count_kps_in_section(section_id: str) -> int:
    """查询某 Section 下已有 KnowledgePoint 数。"""
    cypher = """
    MATCH (:Section {id: $section_id})-[:HAS_KNOWLEDGE_POINT]->(kp:KnowledgePoint)
    RETURN count(kp) AS cnt
    """
    result = _run_cypher(cypher, section_id=section_id)
    return int(result[0].get("cnt", 0)) if result else 0


def delete_kps_in_section(section_id: str) -> int:
    """删除某 Section 下所有 KnowledgePoint 节点及其关系。"""
    cypher = """
    MATCH (:Section {id: $section_id})-[:HAS_KNOWLEDGE_POINT]->(kp:KnowledgePoint)
    DETACH DELETE kp
    RETURN count(*) AS cnt
    """
    result = _run_cypher(cypher, section_id=section_id)
    return int(result[0].get("cnt", 0)) if result else 0


def build_knowledge_point_nodes(
    section_infos: list[dict[str, Any]],
    force_sections: set[str] | None = None,
) -> int:
    """
    从 .knowledge.json 创建 KnowledgePoint 节点。

    增量策略：按 Section 批量检测——查询已有 KP 数，与 .knowledge.json 一致则跳过。
    force_sections 中的 section_id 强制删除重建。

    参数：
        section_infos: [{section_id, course_id, section, kps: [{kp_index, kp_title, kp_summary, key_points, start_sec, end_sec}]}, ...]
        force_sections: 强制重建的 section_id 集合

    返回：
        新创建的 KP 数
    """
    force = force_sections or set()
    total = 0

    for sec in section_infos:
        sec_id = str(sec.get("section_id") or "").strip()
        kps = sec.get("kps", [])
        expected = len(kps)
        existing = count_kps_in_section(sec_id)

        if sec_id not in force and expected > 0 and existing == expected:
            logger.debug("KP 跳过（已存在 %d）: %s", existing, sec_id)
            continue

        if existing > 0:
            removed = delete_kps_in_section(sec_id)
            logger.debug("重建 KP: %s (删除 %d)", sec_id, removed)

        course_id = str(sec.get("course_id") or "").strip()
        section = str(sec.get("section") or "").strip()

        for kp in kps:
            kp_idx = int(kp.get("kp_index", 0))
            kp_id = f"{sec_id}_kp{kp_idx}"
            kp_title = str(kp.get("kp_title") or "")[:256]
            kp_summary = str(kp.get("kp_summary") or "")[:1024]
            key_points = kp.get("key_points", [])
            if isinstance(key_points, list):
                key_points_str = ", ".join(str(p) for p in key_points)[:2048]
            else:
                key_points_str = str(key_points or "")[:2048]
            start_sec = int(kp.get("start_sec", -1))
            end_sec = int(kp.get("end_sec", -1))

            cypher = """
            MERGE (kp:KnowledgePoint {kp_id: $kp_id})
              ON CREATE SET kp.kp_index = $kp_index, kp.kp_title = $kp_title,
                            kp.kp_summary = $kp_summary, kp.key_points = $key_points,
                            kp.start_sec = $start_sec, kp.end_sec = $end_sec,
                            kp.course_id = $course_id, kp.section = $section
              ON MATCH  SET kp.kp_index = $kp_index, kp.kp_title = $kp_title,
                            kp.kp_summary = $kp_summary, kp.key_points = $key_points,
                            kp.start_sec = $start_sec, kp.end_sec = $end_sec,
                            kp.course_id = $course_id, kp.section = $section
            RETURN kp.kp_id AS id
            """
            _run_cypher(
                cypher,
                kp_id=kp_id, kp_index=kp_idx, kp_title=kp_title,
                kp_summary=kp_summary, key_points=key_points_str,
                start_sec=start_sec, end_sec=end_sec,
                course_id=course_id, section=section,
            )
            total += 1

    logger.info("KnowledgePoint: %d (新导入)", total)
    return total


# ── Skill / Role ────────────────────────────────────

def build_skill_role_nodes(roles_data: dict[str, Any]) -> tuple[int, int]:
    """
    从 roles.json 创建 Skill 和 Role 节点。

    返回：(Skill 数, Role 数)
    """
    skill_count = 0
    role_count = 0
    seen_skills: set[str] = set()

    for role in roles_data.get("roles", []):
        role_id = str(role.get("role_id") or "").strip()
        role_title = str(role.get("title") or "").strip()
        if not role_id:
            continue
        industry = str(role.get("industry") or "IT").strip() or "IT"

        cypher_role = """
        MERGE (r:Role {id: $id})
          ON CREATE SET r.title = $title, r.industry = $industry
          ON MATCH  SET r.title = $title, r.industry = $industry
        RETURN r.id AS id
        """
        _run_cypher(cypher_role, id=role_id, title=role_title, industry=industry)
        role_count += 1

    for sm in roles_data.get("skill_mappings", []):
        skill_name = str(sm.get("skill_name") or "").strip()
        if not skill_name or skill_name in seen_skills:
            continue
        seen_skills.add(skill_name)
        is_required = bool(sm.get("is_required", False))

        cypher_skill = """
        MERGE (sk:Skill {name: $name})
          ON CREATE SET sk.is_required = $is_required
          ON MATCH  SET sk.is_required = $is_required
        RETURN sk.name AS name
        """
        _run_cypher(cypher_skill, name=skill_name, is_required=is_required)
        skill_count += 1

    logger.info("Skill: %d, Role: %d", skill_count, role_count)
    return skill_count, role_count
