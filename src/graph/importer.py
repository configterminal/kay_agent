"""
Graph Importer — 知识图谱导入器入口。

编排 node_builder、relation_builder、expan_infer 三个模块，
从课程目录 + .knowledge.json + roles.json 构建完整 Neo4j 知识图谱。

设计原则：
- 幂等：可重复调用，MERGE 保证不产生重复数据
- 增量：按 Section 检测已有 KP 数，一致则跳过
- 静默降级：Neo4j 不可达时跳过，不阻塞服务

使用方式：
    from src.graph.importer import sync_graph
    sync_graph()           # 增量
    sync_graph(force=True) # 全量重建
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from src.config import config
from src.graph.client import check_connection
from src.perf import log_timing

logger = logging.getLogger(__name__)

# 复用 indexer.py 的扫描正则（与 COURSE_DIR_RE / CHAPTER_DIR_RE / LESSON_STEM_RE 一致）
COURSE_DIR_RE = re.compile(
    r"^(?P<course_id>[A-Za-z0-9][A-Za-z0-9-]*) (?P<course_title>.+)$"
)
CHAPTER_DIR_RE = re.compile(r"^(?P<cc>\d{2}) (?P<chapter_title>.+)$")
LESSON_STEM_RE = re.compile(r"^(?P<section>\d{2}-\d{2}) (?P<title>.+)$")


# ── 数据扫描（内联版，不依赖 indexer.py）────────────

def _scan_course_data(resources_dir: Path) -> list[dict[str, Any]]:
    """
    扫描课程目录，返回课程结构化数据。

    返回：
        [{course_id, title, tags, industry,
          chapters: [{cc, title, chapter_title,
                      sections: [{section, title, section_title, media_path, skills,
                                  kps: [{kp_index, kp_title, kp_summary, key_points, start_sec, end_sec}]}]}]}]
    """
    courses_dir = resources_dir / "courses"
    if not courses_dir.exists():
        logger.warning("课程目录不存在: %s", courses_dir)
        return []

    courses: list[dict[str, Any]] = []

    for course_dir in sorted(courses_dir.iterdir()):
        if not course_dir.is_dir():
            continue
        dir_m = COURSE_DIR_RE.match(course_dir.name)
        if not dir_m:
            continue

        index_file = course_dir / "index.json"
        if not index_file.exists():
            continue

        try:
            course_info = json.loads(index_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("读取 index.json 失败: %s", course_dir.name)
            continue

        course_id = str(course_info.get("course_id") or "").strip()
        course_title = str(course_info.get("title") or dir_m.group("course_title")).strip()
        industry = str(course_info.get("industry") or "IT").strip() or "IT"
        tags = course_info.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        chapters: list[dict[str, Any]] = []

        for chapter_dir in sorted(course_dir.iterdir()):
            if not chapter_dir.is_dir():
                continue
            ch_m = CHAPTER_DIR_RE.match(chapter_dir.name)
            if not ch_m:
                continue

            cc = ch_m.group("cc")
            chapter_title = ch_m.group("chapter_title")

            module_file = chapter_dir / "module.json"
            chapter_skills: list[str] = []
            if module_file.exists():
                try:
                    mod = json.loads(module_file.read_text(encoding="utf-8"))
                    skills = mod.get("skills", [])
                    if isinstance(skills, list):
                        chapter_skills = [str(s) for s in skills if s]
                except (json.JSONDecodeError, OSError):
                    pass

            sections: list[dict[str, Any]] = []

            for md_path in sorted(chapter_dir.glob("*.md")):
                stem_m = LESSON_STEM_RE.match(md_path.stem)
                if not stem_m:
                    continue
                section = stem_m.group("section")
                section_title = stem_m.group("title")

                # media_path
                mp4_path = md_path.with_suffix(".mp4")
                media_path = ""
                if mp4_path.is_file():
                    try:
                        media_path = str(
                            mp4_path.relative_to(resources_dir)
                        ).replace("\\", "/")
                    except ValueError:
                        pass

                # .knowledge.json
                kp_path = md_path.with_suffix(".knowledge.json")
                kps: list[dict[str, Any]] = []
                if kp_path.exists():
                    try:
                        kp_data = json.loads(kp_path.read_text(encoding="utf-8"))
                        for kp in kp_data.get("knowledge_points", []):
                            kps.append({
                                "kp_index": int(kp.get("kp_index", 0)),
                                "kp_title": str(kp.get("kp_title", ""))[:256],
                                "kp_summary": str(kp.get("kp_summary", ""))[:1024],
                                "key_points": kp.get("key_points", []),
                                "start_sec": int(kp.get("start_sec", -1)),
                                "end_sec": int(kp.get("end_sec", -1)),
                            })
                    except (json.JSONDecodeError, OSError):
                        pass

                sections.append({
                    "section": section,
                    "title": section_title,
                    "media_path": media_path,
                    "skills": chapter_skills,
                    "kps": kps,
                })

            if sections:
                chapters.append({
                    "cc": cc,
                    "title": chapter_title,
                    "sections": sections,
                })

        courses.append({
            "course_id": course_id,
            "title": course_title,
            "tags": tags,
            "industry": industry,
            "chapters": chapters,
        })

    return courses


# ── 主入口 ──────────────────────────────────────────

def sync_graph(force: bool = False) -> dict[str, Any]:
    """
    同步课程知识图谱到 Neo4j。

    参数：
        force: True=全量重建所有节点和关系

    返回：
        {courses, chapters, sections, kp_new, relations,
         expands_sections, expands_relations, error}
    """
    if not check_connection()[0]:
        logger.warning("Neo4j 不可达，跳过图同步")
        return {"error": "Neo4j 不可达"}

    t_all = time.perf_counter()
    result: dict[str, Any] = {
        "courses": 0, "chapters": 0, "sections": 0,
        "kp_new": 0, "relations": 0,
        "expands_sections": 0, "expands_relations": 0,
    }

    # ① 扫描数据
    courses = _scan_course_data(config.resources_dir)
    if not courses:
        logger.warning("未找到课程数据")
        return result

    # ② Course + Chapter + Section 节点
    from src.graph.node_builder import (
        build_course_nodes,
        build_chapter_section_nodes,
    )
    result["courses"] = build_course_nodes(courses)
    result["chapters"], result["sections"] = build_chapter_section_nodes(courses)

    # ③ 树形关系
    from src.graph.relation_builder import build_tree_relations
    result["relations"] += build_tree_relations(courses)

    # ④ 收集 section 信息给 KP builder
    section_infos: list[dict[str, Any]] = []
    for c in courses:
        cid = c["course_id"]
        ctitle = c.get("title", "")
        for ch in c.get("chapters", []):
            chtitle = ch.get("title", "")
            for sec in ch.get("sections", []):
                section_infos.append({
                    "section_id": f"{cid}_{sec['section']}",
                    "course_id": cid,
                    "section": sec["section"],
                    "course_title": ctitle,
                    "chapter_title": chtitle,
                    "section_title": sec.get("title", ""),
                    "skills": sec.get("skills", []),
                    "kps": sec.get("kps", []),
                })

    force_sections: set[str] | None = None
    if force:
        force_sections = {s["section_id"] for s in section_infos}

    # ⑤ KnowledgePoint 节点
    from src.graph.node_builder import build_knowledge_point_nodes
    result["kp_new"] = build_knowledge_point_nodes(
        section_infos, force_sections=force_sections
    )

    # ⑥ KP 关系
    from src.graph.relation_builder import build_knowledge_point_relations
    result["relations"] += build_knowledge_point_relations(section_infos)

    # ⑦ Skill/Role 节点 + 技能关系
    roles_data: dict[str, Any] = {}
    roles_path = config.resources_dir / "job_roles" / "IT" / "roles.json"
    if roles_path.exists():
        try:
            roles_data = json.loads(roles_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    if roles_data:
        from src.graph.node_builder import build_skill_role_nodes
        build_skill_role_nodes(roles_data)

        from src.graph.relation_builder import build_skill_relations
        result["relations"] += build_skill_relations(section_infos, roles_data)

    # ⑧ EXPANDS 推断
    from src.graph.expan_infer import infer_expands_all
    expan_data = infer_expands_all(section_infos, force=force)
    if expan_data:
        from src.graph.relation_builder import build_expan_relations
        result["expands_sections"] = len(expan_data)
        result["expands_relations"] = build_expan_relations(expan_data)

    log_timing(
        "graph.sync.total",
        time.perf_counter() - t_all,
        **{k: v for k, v in result.items() if v},
    )
    logger.info(
        "图同步完成: %d 课 %d 章 %d 节, %d KP, %d 关系, %d EXPANDS 节 %d 边",
        result["courses"], result["chapters"], result["sections"],
        result["kp_new"], result["relations"],
        result["expands_sections"], result["expands_relations"],
    )
    return result
