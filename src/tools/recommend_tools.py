"""
推荐系统工具 — 课程推荐、前置检查、模块查询。

依赖 course_modules（由 catalog_sync 从 resources/ 同步）。

使用方式：
    from src.tools.recommend_tools import (
        get_available_modules,
        get_next_recommendations,
        get_prerequisite_modules,
    )
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from src.db.init_db import get_session
from src.db.schema import Student, LearningProgress, QuizAttempt, CourseModule
from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_DIFFICULTY_ORDER = {"beginner": 1, "intermediate": 2, "advanced": 3}


def _difficulty_fits(module_difficulty: str, student_skill_level: str) -> bool:
    """判断模块难度是否不超过学员水平。"""
    mod_level = _DIFFICULTY_ORDER.get(module_difficulty or "beginner", 1)
    stu_level = _DIFFICULTY_ORDER.get(student_skill_level or "beginner", 1)
    return mod_level <= stu_level


def _persona_fits(module_persona: str | None, student_persona: str | None) -> bool:
    """persona_target 兼容：all 通吃。"""
    target = (module_persona or "all").strip()
    if target == "all" or not student_persona:
        return True
    return target == student_persona


def _module_tags(m: CourseModule) -> list[str]:
    raw = m.tags
    if isinstance(raw, list):
        return [str(t) for t in raw if t]
    if isinstance(raw, str) and raw.strip():
        return [t.strip() for t in raw.split(",") if t.strip()]
    return []


def _keyword_hits(text: str, keywords: list[str]) -> list[str]:
    """返回在 text 中命中的关键词（小写比较）。"""
    hay = (text or "").lower()
    hits = []
    for kw in keywords:
        k = (kw or "").strip().lower()
        if k and k in hay:
            hits.append(kw)
    return hits


def _target_keywords(target_role: str | None) -> list[str]:
    """从目标岗位文案拆出匹配词（含常见同义扩展）。"""
    if not target_role:
        return []
    text = target_role.strip()
    base = [text]
    # 拆分常见分隔
    for sep in ("/", "、", "，", ",", " "):
        if sep in text:
            base.extend(p.strip() for p in text.split(sep) if p.strip())
    extras: list[str] = []
    joined = text.lower()
    if any(x in joined for x in ("ai", "大模型", "llm", "rag", "智能")):
        extras.extend(["RAG", "AI", "大模型", "向量", "检索"])
    if any(x in joined for x in ("跳槽", "面试", "晋升", "求职", "职业")):
        extras.extend(["职业跃迁", "跳槽", "面试", "晋升", "谈薪", "简历"])
    # 去重保序
    seen = set()
    out = []
    for w in base + extras:
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _score_module(
    m: CourseModule,
    *,
    student_persona: str | None,
    skill_level: str,
    target_role: str | None,
    enrolled: set[str],
    completed: set[str],
    weak_areas: set[str],
    prefer_course_level: bool,
) -> tuple[float, str, str]:
    """
    返回 (score, priority, source)。
    score 越高越优先推荐。
    """
    score = 0.0
    reasons: list[str] = []
    source = "career_path"
    priority = "medium"

    level = (m.level or ("course" if m.module_id == m.course_id else "chapter")).strip()
    tags = _module_tags(m)
    blob = " ".join([m.title or "", m.description or "", " ".join(tags)])

    # 难度门槛（调用前已过滤，这里加分）
    if _difficulty_fits(m.difficulty, skill_level):
        score += 1.0

    # persona
    if _persona_fits(m.persona_target, student_persona):
        if (m.persona_target or "all") != "all" and student_persona:
            score += 4.0
            reasons.append("匹配学员身份")
        else:
            score += 1.0

    # target_role ↔ tags/title
    kws = _target_keywords(target_role)
    hits = _keyword_hits(blob, kws)
    if hits:
        score += 5.0 + min(len(hits), 3)
        reasons.append(f"契合目标「{target_role}」")
        source = "career_path"
        priority = "high"

    # 薄弱点
    weak_hits = []
    for area in weak_areas:
        if area and (area.lower() in blob.lower()):
            weak_hits.append(area)
    if weak_hits:
        score += 3.5
        reasons.append(f"覆盖薄弱点：{'、'.join(weak_hits[:3])}")
        source = "weak_area"
        priority = "high"

    # 前置已满足 / 无前置
    prereqs = m.prerequisites or []
    if not prereqs:
        score += 2.0
        reasons.append("无前置要求，可直接学习")
    elif all(p in completed for p in prereqs):
        score += 3.0
        reasons.append("前置条件已满足")
        priority = "high"
    else:
        score -= 2.0  # 未满足前置降权（仍可能展示）

    # 已选课续学：优先同课下一章
    course_id = m.course_id or (m.module_id if level == "course" else "")
    if level == "chapter" and course_id and (
        course_id in enrolled or any(e.startswith(course_id) for e in enrolled)
    ):
        score += 4.0
        reasons.append("已选该课程，建议继续下一章")
        source = "self_pick_extension"
        priority = "high"

    # 分轨：未选课时抬高 course 级；已选课时抬高 chapter
    if prefer_course_level and level == "course":
        score += 3.0
    elif not prefer_course_level and level == "chapter":
        score += 2.5
    elif prefer_course_level and level == "chapter":
        score -= 1.0  # 未选课时少推章
    elif not prefer_course_level and level == "course":
        score -= 0.5

    if not reasons:
        reasons.append("拓展学习推荐")

    return score, priority, source


def _build_reason(
    module: CourseModule,
    completed_ids: set,
    weak_areas: set,
    extra: str = "",
) -> str:
    """规则型推荐理由。"""
    reasons = []
    if extra:
        reasons.append(extra)
    prereqs = module.prerequisites or []
    if prereqs and all(p in completed_ids for p in prereqs):
        reasons.append("前置条件已满足，可立即开始学习")
    elif not prereqs:
        reasons.append("无前置要求，可直接学习")

    title_lower = (module.title or "").lower()
    desc_lower = (module.description or "").lower()
    matched_weak = [
        area for area in weak_areas
        if area.lower() in title_lower or area.lower() in desc_lower
    ]
    if matched_weak:
        reasons.append(f"覆盖薄弱知识点：{'、'.join(matched_weak)}")

    if not reasons:
        reasons.append("拓展学习推荐")
    return "；".join(reasons)


# ── 工具 1：查询可用模块 ──────────────────────────────

@tool
def get_available_modules(
    industry: str,
    skill_level: str,
    module_type: str = None,
) -> list[dict]:
    """
    查询可用课程模块。按行业和学员水平过滤，可选按类型进一步筛选。

    参数：
        industry: 所属行业（如 "IT"、"互联网"）
        skill_level: 学员技能水平（beginner/intermediate/advanced）
        module_type: 可选，模块类型过滤（匹配标题）

    返回：
        [{module_id, course_id, level, title, description, difficulty,
          prerequisites, estimated_hours, persona_target, tags}, ...]
    """
    with get_session() as session:
        query = session.query(CourseModule).filter(
            CourseModule.industry == industry
        )
        if module_type:
            query = query.filter(CourseModule.title.contains(module_type))
        modules = query.all()

    result = []
    for m in modules:
        if _difficulty_fits(m.difficulty, skill_level):
            result.append({
                "module_id": m.module_id,
                "course_id": m.course_id or m.module_id,
                "level": m.level or "chapter",
                "title": m.title,
                "description": m.description,
                "difficulty": m.difficulty,
                "prerequisites": m.prerequisites or [],
                "estimated_hours": m.estimated_hours,
                "persona_target": m.persona_target,
                "tags": _module_tags(m),
            })
    return result


# ── 工具 2：核心推荐逻辑 ────────────────────────────

@tool
def get_next_recommendations(
    student_id: int,
    count: int = 5,
) -> list[dict]:
    """
    为指定学员生成下一阶段课程推荐。综合画像、进度、薄弱点与目录标签。

    未选课时优先推荐课程级；已选课后优先推荐下一章。

    参数：
        student_id: 学员ID
        count: 返回推荐数，默认 5

    返回：
        [{module_id, title, reason, priority, source, level, course_id}, ...]
    """
    with get_session() as session:
        student = session.query(Student).filter(Student.id == student_id).first()
        if not student:
            return []

        enrolled_modules = list(student.enrolled_modules or [])
        skill_level = student.skill_level or "beginner"
        persona = student.persona
        target_role = student.target_role

        completed_rows = (
            session.query(LearningProgress.module_id)
            .filter(
                LearningProgress.student_id == student_id,
                LearningProgress.status == "completed",
            )
            .all()
        )
        completed_ids = {row[0] for row in completed_rows if row[0]}

        quiz_rows = (
            session.query(QuizAttempt.weak_areas)
            .filter(QuizAttempt.student_id == student_id)
            .all()
        )
        weak_areas: set[str] = set()
        for row in quiz_rows:
            if row[0]:
                for area in row[0]:
                    weak_areas.add(area)

        all_modules = session.query(CourseModule).all()

    enrolled_set = set(enrolled_modules)
    prefer_course = len(enrolled_set) == 0

    candidates: list[tuple[float, CourseModule, str, str, str]] = []
    for m in all_modules:
        if m.module_id in completed_ids:
            continue
        if not _difficulty_fits(m.difficulty, skill_level):
            continue
        if not _persona_fits(m.persona_target, persona):
            continue
        # 章级：前置未满足则跳过（课程级始终可推）
        level = m.level or ("course" if m.module_id == (m.course_id or m.module_id) else "chapter")
        prereqs = m.prerequisites or []
        if level == "chapter" and prereqs and not all(p in completed_ids for p in prereqs):
            # 仍允许弱相关展示，但分数会很低；严格跳过未解锁章
            continue

        score, priority, source = _score_module(
            m,
            student_persona=persona,
            skill_level=skill_level,
            target_role=target_role,
            enrolled=enrolled_set,
            completed=completed_ids,
            weak_areas=weak_areas,
            prefer_course_level=prefer_course,
        )
        reason = _build_reason(m, completed_ids, weak_areas)
        candidates.append((score, m, priority, source, reason))

    if not candidates:
        return []

    candidates.sort(key=lambda x: x[0], reverse=True)

    # 分轨混排：未选课 → 先取 course，再补 chapter；已选课 → 先 chapter
    def _is_course_row(m: CourseModule) -> bool:
        return (m.level or "") == "course" or (
            m.course_id and m.module_id == m.course_id
        )

    course_items = [c for c in candidates if _is_course_row(c[1])]
    chapter_items = [c for c in candidates if not _is_course_row(c[1])]

    ranked: list[tuple] = []
    if prefer_course:
        ranked = course_items[:2] + chapter_items
    else:
        ranked = chapter_items + course_items

    # 去重 module_id
    seen_ids = set()
    unique = []
    for item in ranked:
        mid = item[1].module_id
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        unique.append(item)

    top = unique[: max(count, 1)]

    # 候选不多时直接返回；较多时可选 LLM 润色
    if len(unique) <= count:
        return [
            {
                "module_id": m.module_id,
                "title": m.title,
                "reason": reason,
                "priority": priority,
                "source": source,
                "level": m.level or "chapter",
                "course_id": m.course_id or m.module_id,
                "estimated_hours": m.estimated_hours,
            }
            for _, m, priority, source, reason in top
        ]

    try:
        llm = LLMProvider.create()
        model = llm.get_model(temperature=0.2)
        candidates_text = "\n".join(
            f"- {m.module_id}: {m.title}（level:{m.level}, 难度:{m.difficulty}, "
            f"tags:{_module_tags(m)}, 前置:{m.prerequisites or '无'}）"
            for _, m, _, _, _ in unique[:20]
        )
        prompt = f"""你是 AI 课程推荐系统。根据学员信息从候选中选出最合适的 {count} 个。

学员：
- 身份：{persona}
- 技能水平：{skill_level}
- 目标岗位：{target_role or '未填'}
- 已选模块：{enrolled_modules}
- 薄弱点：{list(weak_areas) if weak_areas else '无'}

候选：
{candidates_text}

规则：未选课时优先课程级(level=course)；已选课后优先该课下一章。
返回 JSON 数组（不要其他文字）：
[{{"module_id":"xxx","reason":"中文理由","priority":"high/medium/low","source":"career_path/weak_area/self_pick_extension"}}]"""
        response = model.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
            by_id = {m.module_id: m for _, m, _, _, _ in unique}
            result = []
            for item in parsed:
                mid = item.get("module_id")
                if mid not in by_id:
                    continue
                m = by_id[mid]
                result.append({
                    "module_id": mid,
                    "title": m.title,
                    "reason": item.get("reason") or _build_reason(m, completed_ids, weak_areas),
                    "priority": item.get("priority") or "medium",
                    "source": item.get("source") or "career_path",
                    "level": m.level or "chapter",
                    "course_id": m.course_id or m.module_id,
                    "estimated_hours": m.estimated_hours,
                })
                if len(result) >= count:
                    break
            if result:
                return result
    except Exception as e:
        logger.warning("LLM 推荐排序失败，使用规则排序: %s", e)

    return [
        {
            "module_id": m.module_id,
            "title": m.title,
            "reason": reason,
            "priority": priority,
            "source": source,
            "level": m.level or "chapter",
            "course_id": m.course_id or m.module_id,
            "estimated_hours": m.estimated_hours,
        }
        for _, m, priority, source, reason in top
    ]


# ── 工具 3：前置模块检查 ────────────────────────────

@tool
def get_prerequisite_modules(
    module_id: str,
    student_id: int,
) -> list[dict]:
    """
    检查指定模块的前置条件，并判断学员是否已完成每个前置模块。

    参数：
        module_id: 目标模块ID
        student_id: 学员ID

    返回：
        [{module_id, title, completed}, ...]
    """
    with get_session() as session:
        module = (
            session.query(CourseModule)
            .filter(CourseModule.module_id == module_id)
            .first()
        )
        if not module:
            return []

        prereqs = module.prerequisites or []
        if not prereqs:
            return []

        completed_rows = (
            session.query(LearningProgress.module_id)
            .filter(
                LearningProgress.student_id == student_id,
                LearningProgress.status == "completed",
                LearningProgress.module_id.in_(prereqs),
            )
            .all()
        )
        completed_ids = {row[0] for row in completed_rows if row[0]}

        result = []
        for prereq_id in prereqs:
            prereq_module = (
                session.query(CourseModule)
                .filter(CourseModule.module_id == prereq_id)
                .first()
            )
            title = prereq_module.title if prereq_module else prereq_id
            result.append({
                "module_id": prereq_id,
                "title": title,
                "completed": prereq_id in completed_ids,
            })
        return result
