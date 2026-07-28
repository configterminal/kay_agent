"""
共享工具 — Supervisor 级工具，所有 Agent 均可调用。

提供学员档案查询、职业路径管理、自选课程、导师人格切换、
长期记忆读写、学习进度概览等 11 个工具。

使用方式：
    from src.tools.shared_tools import get_student_profile, switch_coach_style, ...
    tools = [get_student_profile, switch_coach_style, ...]
"""

import datetime
import json
from typing import Any

from langchain_core.tools import tool

from src.db.init_db import get_session
from src.db.schema import (
    Student,
    LearningProgress,
    CourseModule,
    JobRole,
    SkillMapping,
)
from src.llm.base import CoachStyle
from src.memory.store import get_store


# ── 常量 ──────────────────────────────────────────────────

VALID_COACH_STYLES = frozenset(s.value for s in CoachStyle)


# ── 辅助函数 ──────────────────────────────────────────────

def _get_student(session, student_id: int) -> Student | None:
    """查询学员，不存在返回 None"""
    return session.query(Student).filter(Student.id == student_id).first()


def _parse_career_paths(career_paths: Any) -> list[dict]:
    """安全解析 career_paths JSON 字段，始终返回列表"""
    if career_paths is None:
        return []
    if isinstance(career_paths, str):
        try:
            parsed = json.loads(career_paths)
        except (json.JSONDecodeError, TypeError):
            return []
        if isinstance(parsed, list):
            return parsed
        return []
    if isinstance(career_paths, list):
        return career_paths
    return []


# ── 1. 学员档案 ──────────────────────────────────────────

@tool
def get_student_profile(student_id: int) -> dict:
    """
    查询学员完整档案信息，返回 persona、skill_level、career_paths、
    enrolled_modules、target_role、coach_style、display_name 等字段。

    参数：
        student_id: 学员 ID

    返回：
        {persona, skill_level, career_paths, enrolled_modules, target_role,
         coach_style, display_name, ...}
        - 学员不存在时返回 {"error": "学员不存在", "student_id": student_id}
    """
    with get_session() as session:
        student = _get_student(session, student_id)
        if student is None:
            return {"error": "学员不存在", "student_id": student_id}

        return {
            "persona": student.persona,
            "skill_level": student.skill_level,
            "career_paths": _parse_career_paths(student.career_paths),
            "enrolled_modules": student.enrolled_modules or [],
            "target_role": student.target_role,
            "coach_style": student.coach_style or "encouraging",
            "display_name": student.display_name,
            "major": student.major,
            "university": student.university,
            "company": student.company,
            "job_title": student.job_title,
            "years_of_experience": student.years_of_experience,
        }


VALID_PERSONAS = frozenset({"university_student", "working_professional"})
VALID_SKILL_LEVELS = frozenset({"beginner", "intermediate", "advanced"})


@tool
def update_student_profile(
    student_id: int,
    persona: str | None = None,
    skill_level: str | None = None,
    target_role: str | None = None,
    display_name: str | None = None,
    major: str | None = None,
    university: str | None = None,
    company: str | None = None,
    job_title: str | None = None,
    years_of_experience: int | None = None,
    enrolled_modules: list[str] | None = None,
    primary_course_id: str | None = None,
) -> dict:
    """
    部分更新学员画像。仅非空字段覆盖；enrolled_modules 为追加去重。

    学员自述身份、水平、目标岗位后应调用本工具。
    primary_course_id：正式选课时传入，写入 enrolled 并置顶为画像主课。

    参数：
        student_id: 学员 ID
        persona: university_student | working_professional
        skill_level: beginner | intermediate | advanced
        target_role: 目标岗位文案，如「AI应用开发」
        enrolled_modules: 要追加的课程/模块 ID 列表
        primary_course_id: 正式选课的 course 级 id（如 CAREER201）

    返回：
        更新后的 profile 摘要；学员不存在或枚举非法时返回 error
    """
    with get_session() as session:
        student = _get_student(session, student_id)
        if student is None:
            return {"error": "学员不存在", "student_id": student_id}

        if persona is not None:
            p = str(persona).strip()
            if p not in VALID_PERSONAS:
                return {
                    "error": f"非法 persona: {persona}",
                    "allowed": sorted(VALID_PERSONAS),
                }
            student.persona = p

        if skill_level is not None:
            s = str(skill_level).strip()
            if s not in VALID_SKILL_LEVELS:
                return {
                    "error": f"非法 skill_level: {skill_level}",
                    "allowed": sorted(VALID_SKILL_LEVELS),
                }
            student.skill_level = s

        if target_role is not None:
            student.target_role = str(target_role).strip() or None
        if display_name is not None:
            student.display_name = str(display_name).strip() or None
        if major is not None:
            student.major = str(major).strip() or None
        if university is not None:
            student.university = str(university).strip() or None
        if company is not None:
            student.company = str(company).strip() or None
        if job_title is not None:
            student.job_title = str(job_title).strip() or None
        if years_of_experience is not None:
            student.years_of_experience = int(years_of_experience)

        if enrolled_modules is not None:
            existing = list(student.enrolled_modules or [])
            seen = set(existing)
            for mid in enrolled_modules:
                m = str(mid).strip()
                if m and m not in seen:
                    existing.append(m)
                    seen.add(m)
            student.enrolled_modules = existing

        # 正式选课：置顶为画像主课
        if primary_course_id is not None:
            pc = str(primary_course_id).strip()
            if pc:
                existing = list(student.enrolled_modules or [])
                existing = [x for x in existing if str(x).strip() != pc]
                student.enrolled_modules = [pc] + existing

        session.commit()
        session.refresh(student)
        return {
            "ok": True,
            "persona": student.persona,
            "skill_level": student.skill_level,
            "target_role": student.target_role,
            "enrolled_modules": student.enrolled_modules or [],
            "display_name": student.display_name,
            "major": student.major,
            "company": student.company,
            "job_title": student.job_title,
            "years_of_experience": student.years_of_experience,
        }


# ── 2. 职业路径列表 ──────────────────────────────────────

@tool
def get_career_paths(student_id: int) -> list[dict]:
    """
    查询学员的所有职业路径，每条包含 role_id、title、status、is_primary、started_at。

    参数：
        student_id: 学员 ID

    返回：
        [{role_id, title, status(active|archived), is_primary, started_at}, ...]
        - 学员不存在时返回 [{"error": "学员不存在"}]
        - 无职业路径时返回空列表 []
    """
    with get_session() as session:
        student = _get_student(session, student_id)
        if student is None:
            return [{"error": "学员不存在"}]

        paths = _parse_career_paths(student.career_paths)
        # 只返回接口需要的字段
        return [
            {
                "role_id": p.get("role_id"),
                "title": p.get("title"),
                "status": p.get("status", "active"),
                "is_primary": p.get("is_primary", False),
                "started_at": p.get("started_at"),
            }
            for p in paths
        ]


# ── 3. 切换主职业路径 ────────────────────────────────────

@tool
def switch_career_path(student_id: int, role_id: str) -> dict:
    """
    将指定职业路径设为主路径（is_primary=true），其他路径设为非主路径。

    参数：
        student_id: 学员 ID
        role_id: 目标岗位 ID（如 "frontend_engineer"）

    返回：
        {success, message}
        - 失败时 success=false，message 说明原因
    """
    with get_session() as session:
        student = _get_student(session, student_id)
        if student is None:
            return {"success": False, "message": f"学员 {student_id} 不存在"}

        paths = _parse_career_paths(student.career_paths)
        if not paths:
            return {"success": False, "message": "该学员尚未设置任何职业路径"}

        target_found = False
        for p in paths:
            if p.get("role_id") == role_id:
                p["is_primary"] = True
                target_found = True
            else:
                p["is_primary"] = False

        if not target_found:
            return {
                "success": False,
                "message": f"未找到 role_id='{role_id}' 的职业路径",
            }

        student.career_paths = paths
        session.commit()
        return {
            "success": True,
            "message": f"已将 '{role_id}' 设为主职业路径",
        }


# ── 4. 关注 / 新增职业路径 ───────────────────────────────

@tool
def follow_career_path(student_id: int, role_id: str) -> dict:
    """
    新增一条职业路径并生成概览（所需技能数、匹配课程数、预估总学时）。

    MVP 阶段：直接将路径加入列表，返回概览信息。
    后续会加入确认步骤（先展示概览，学员确认后再提交）。

    参数：
        student_id: 学员 ID
        role_id: 目标岗位 ID

    返回：
        {success, message, overview}
        - overview: {role_title, required_skills_count, matching_course_count,
                     estimated_total_hours}
    """
    with get_session() as session:
        student = _get_student(session, student_id)
        if student is None:
            return {"success": False, "message": f"学员 {student_id} 不存在"}

        # 查询岗位定义
        job_role = session.query(JobRole).filter(JobRole.role_id == role_id).first()
        if job_role is None:
            return {"success": False, "message": f"岗位 '{role_id}' 不存在"}

        # 查询技能对照：该岗位关联的课程模块
        skill_mappings = (
            session.query(SkillMapping)
            .filter(SkillMapping.role_id == role_id)
            .all()
        )

        required_skills = [
            sm.skill_name for sm in skill_mappings if sm.is_required
        ]
        matching_module_ids = set(
            sm.module_id for sm in skill_mappings if sm.module_id
        )

        # 查课程模块统计学时
        estimated_hours = 0
        if matching_module_ids:
            modules = (
                session.query(CourseModule)
                .filter(CourseModule.module_id.in_(matching_module_ids))
                .all()
            )
            estimated_hours = sum(m.estimated_hours or 0 for m in modules)

        role_title = job_role.title or role_id

        # 检查是否已存在该路径
        paths = _parse_career_paths(student.career_paths)
        existing = [p for p in paths if p.get("role_id") == role_id]
        if existing:
            # 如果已存在且是 archived，恢复为 active
            if existing[0].get("status") == "archived":
                existing[0]["status"] = "active"
                student.career_paths = paths
                session.commit()
                return {
                    "success": True,
                    "message": f"已恢复 '{role_title}' 职业路径",
                    "overview": {
                        "role_title": role_title,
                        "required_skills_count": len(required_skills),
                        "matching_course_count": len(matching_module_ids),
                        "estimated_total_hours": estimated_hours,
                    },
                }
            return {
                "success": True,
                "message": f"职业路径 '{role_title}' 已在关注列表中",
                "overview": {
                    "role_title": role_title,
                    "required_skills_count": len(required_skills),
                    "matching_course_count": len(matching_module_ids),
                    "estimated_total_hours": estimated_hours,
                },
            }

        # 新增路径
        new_path = {
            "role_id": role_id,
            "title": role_title,
            "status": "active",
            "is_primary": len(paths) == 0,  # 第一个路径自动设为主路径
            "started_at": datetime.datetime.utcnow().isoformat(),
            "archived_at": None,
        }
        paths.append(new_path)
        student.career_paths = paths
        session.commit()

        return {
            "success": True,
            "message": f"已关注 '{role_title}' 职业路径",
            "overview": {
                "role_title": role_title,
                "required_skills_count": len(required_skills),
                "matching_course_count": len(matching_module_ids),
                "estimated_total_hours": estimated_hours,
            },
        }


# ── 5. 归档职业路径 ──────────────────────────────────────

@tool
def archive_career_path(student_id: int, role_id: str) -> dict:
    """
    将职业路径状态设为 "archived"，保留学习记录。

    不能归档唯一的活跃路径（至少保留一条 active）。

    参数：
        student_id: 学员 ID
        role_id: 目标岗位 ID

    返回：
        {success, message}
    """
    with get_session() as session:
        student = _get_student(session, student_id)
        if student is None:
            return {"success": False, "message": f"学员 {student_id} 不存在"}

        paths = _parse_career_paths(student.career_paths)
        if not paths:
            return {"success": False, "message": "该学员尚未设置任何职业路径"}

        # 找到目标路径
        target_path = None
        for p in paths:
            if p.get("role_id") == role_id:
                target_path = p
                break

        if target_path is None:
            return {
                "success": False,
                "message": f"未找到 role_id='{role_id}' 的职业路径",
            }

        if target_path.get("status") == "archived":
            return {
                "success": False,
                "message": f"'{role_id}' 已经是归档状态",
            }

        # 检查是否是唯一的 active 路径
        active_paths = [p for p in paths if p.get("status") == "active"]
        if len(active_paths) == 1 and active_paths[0].get("role_id") == role_id:
            return {
                "success": False,
                "message": f"'{role_id}' 是唯一的活跃职业路径，不能归档。请先关注其他路径。",
            }

        # 归档
        target_path["status"] = "archived"
        target_path["archived_at"] = datetime.datetime.utcnow().isoformat()
        # 如果归档的是主路径，把第一个 active 路径设为主路径
        if target_path.get("is_primary"):
            target_path["is_primary"] = False
            for p in paths:
                if p.get("status") == "active":
                    p["is_primary"] = True
                    break

        student.career_paths = paths
        session.commit()
        return {
            "success": True,
            "message": f"已归档 '{role_id}' 职业路径，学习记录已保留",
        }


# ── 6. 自选课程 ──────────────────────────────────────────

@tool
def add_self_pick_module(student_id: int, module_id: str) -> dict:
    """
    学员自主选择课程模块，添加到 enrolled_modules 并在 learning_progress
    中创建一条 source="self_pick" 的记录（状态为 not_started）。

    参数：
        student_id: 学员 ID
        module_id: 课程模块 ID（如 "RAG101"）

    返回：
        {success, message}
    """
    with get_session() as session:
        student = _get_student(session, student_id)
        if student is None:
            return {"success": False, "message": f"学员 {student_id} 不存在"}

        # 验证模块存在
        course = (
            session.query(CourseModule)
            .filter(CourseModule.module_id == module_id)
            .first()
        )
        if course is None:
            return {"success": False, "message": f"课程模块 '{module_id}' 不存在"}

        # 更新 enrolled_modules
        enrolled = list(student.enrolled_modules or [])
        if module_id in enrolled:
            return {
                "success": False,
                "message": f"课程 '{course.title or module_id}' 已在学习列表中",
            }
        enrolled.append(module_id)
        student.enrolled_modules = enrolled

        # 创建 learning_progress 记录
        progress = LearningProgress(
            student_id=student_id,
            module_id=module_id,
            status="not_started",
            time_spent_minutes=0,
            source="self_pick",
            last_accessed_at=datetime.datetime.utcnow(),
        )
        session.add(progress)
        session.commit()

        return {
            "success": True,
            "message": f"已添加自选课程 '{course.title or module_id}'",
        }


# ── 7. 自选课程列表 ──────────────────────────────────────

@tool
def get_self_pick_modules(student_id: int) -> list[dict]:
    """
    查询学员所有自选课程（source="self_pick"），包含 module_id、title、status、started_at。

    参数：
        student_id: 学员 ID

    返回：
        [{module_id, title, status, started_at}, ...]
        - 学员不存在时返回 [{"error": "学员不存在"}]
        - 无自选课程时返回空列表 []
    """
    with get_session() as session:
        student = _get_student(session, student_id)
        if student is None:
            return [{"error": "学员不存在"}]

        records = (
            session.query(LearningProgress)
            .filter(
                LearningProgress.student_id == student_id,
                LearningProgress.source == "self_pick",
            )
            .all()
        )

        if not records:
            return []

        # 收集所有 module_id 以查标题
        module_ids = list({r.module_id for r in records if r.module_id})
        title_map = {}
        if module_ids:
            modules = (
                session.query(CourseModule)
                .filter(CourseModule.module_id.in_(module_ids))
                .all()
            )
            title_map = {m.module_id: m.title or m.module_id for m in modules}

        return [
            {
                "module_id": r.module_id,
                "title": title_map.get(r.module_id, r.module_id),
                "status": r.status or "not_started",
                "started_at": r.last_accessed_at.isoformat() if r.last_accessed_at else None,
            }
            for r in records
        ]


# ── 8. 切换导师人格 ──────────────────────────────────────

@tool
def switch_coach_style(student_id: int, style: str) -> dict:
    """
    切换 AI 导师的对话风格。

    支持的人格：encouraging（温柔鼓励）、pushing（严厉驱动）、
    humorous（幽默风趣）、professional（专业简洁）。

    触发关键词："切换人格" / "换风格" / "换个导师"

    参数：
        student_id: 学员 ID
        style: 人格标识（encouraging/pushing/humorous/professional）

    返回：
        {success, message, new_style}
    """
    # 校验 style 合法性
    style_lower = style.strip().lower()
    if style_lower not in VALID_COACH_STYLES:
        valid_list = " / ".join(sorted(VALID_COACH_STYLES))
        return {
            "success": False,
            "message": f"无效的人格 '{style}'，可选：{valid_list}",
            "new_style": None,
        }

    # 中文映射，方便用户输入中文
    chinese_map = {
        "鼓励型": "encouraging",
        "鼓励": "encouraging",
        "温柔": "encouraging",
        "严厉型": "pushing",
        "严厉": "pushing",
        "驱动": "pushing",
        "幽默型": "humorous",
        "幽默": "humorous",
        "风趣": "humorous",
        "专业型": "professional",
        "专业": "professional",
        "简洁": "professional",
    }
    if style_lower in chinese_map:
        style_lower = chinese_map[style_lower]

    with get_session() as session:
        student = _get_student(session, student_id)
        if student is None:
            return {
                "success": False,
                "message": f"学员 {student_id} 不存在",
                "new_style": None,
            }

        student.coach_style = style_lower
        session.commit()

        # 中文名映射用于友好提示
        style_display = {
            "encouraging": "温柔鼓励型",
            "pushing": "严厉驱动型",
            "humorous": "幽默风趣型",
            "professional": "专业简洁型",
        }

        return {
            "success": True,
            "message": f"导师风格已切换为「{style_display.get(style_lower, style_lower)}」",
            "new_style": style_lower,
        }


# ── 9. 读取长期记忆 ──────────────────────────────────────

@tool
def get_long_term_memory(student_id: int, key: str) -> dict | None:
    """
    从 Redis MemoryStore 读取学员的长期记忆。

    Key 命名空间格式: ["students", str(student_id), key]
    示例：key="preferences" → 读取 students:<id>:preferences

    参数：
        student_id: 学员 ID
        key: 记忆键名（如 "preferences", "weak_areas", "learning_style"）

    返回：
        记忆数据字典，无数据时返回 None
    """
    store = get_store()
    return store.get(["students", str(student_id), key])


# ── 10. 写入长期记忆 ─────────────────────────────────────

@tool
def set_long_term_memory(student_id: int, key: str, value: dict) -> bool:
    """
    将数据写入 Redis MemoryStore 作为学员的长期记忆。

    Key 命名空间格式: ["students", str(student_id), key]
    示例：key="preferences", value={"fav_topic": "Docker"} → students:<id>:preferences

    参数：
        student_id: 学员 ID
        key: 记忆键名
        value: 要存储的数据字典

    返回：
        True 表示写入成功
    """
    store = get_store()
    store.put(["students", str(student_id), key], value)
    return True


# ── 11. 学习进度概览 ─────────────────────────────────────

@tool
def get_student_progress_summary(student_id: int) -> dict:
    """
    快速获取学员学习进度概览：整体完成率、最近学习的 5 门课程、总学习时长。

    参数：
        student_id: 学员 ID

    返回：
        {completion_pct, recent_modules: [{module_id, title, status, last_accessed_at}],
         total_time_spent_minutes, total_modules, completed_count}
        - 学员不存在时返回 {"error": "学员不存在"}
    """
    with get_session() as session:
        student = _get_student(session, student_id)
        if student is None:
            return {"error": "学员不存在"}

        # 查询所有学习进度记录
        all_records = (
            session.query(LearningProgress)
            .filter(LearningProgress.student_id == student_id)
            .order_by(LearningProgress.last_accessed_at.desc().nullslast())
            .all()
        )

        if not all_records:
            return {
                "completion_pct": 0.0,
                "recent_modules": [],
                "total_time_spent_minutes": 0,
                "total_modules": 0,
                "completed_count": 0,
            }

        total = len(all_records)
        completed = sum(1 for r in all_records if r.status == "completed")
        total_minutes = sum(r.time_spent_minutes or 0 for r in all_records)

        # 最近 5 条
        recent = all_records[:5]
        recent_module_ids = list({r.module_id for r in recent if r.module_id})
        title_map = {}
        if recent_module_ids:
            modules = (
                session.query(CourseModule)
                .filter(CourseModule.module_id.in_(recent_module_ids))
                .all()
            )
            title_map = {m.module_id: m.title or m.module_id for m in modules}

        recent_modules = [
            {
                "module_id": r.module_id,
                "title": title_map.get(r.module_id, r.module_id),
                "status": r.status or "not_started",
                "last_accessed_at": (
                    r.last_accessed_at.isoformat() if r.last_accessed_at else None
                ),
            }
            for r in recent
        ]

        return {
            "completion_pct": round(completed / total * 100, 1) if total > 0 else 0.0,
            "recent_modules": recent_modules,
            "total_time_spent_minutes": total_minutes,
            "total_modules": total,
            "completed_count": completed,
        }


# ── 12. 会话内话题块检索 ─────────────────────────────────

@tool
def search_thread_blocks(
    query: str,
    top_k: int = 3,
    time_range: str = "recent",
    student_id: int = 0,
    thread_id: str = "",
) -> list[dict]:
    """
    在当前会话（或指定会话）的历史话题块中搜索匹配的话题。

    每个块含 block_id、topic、summary、source_thread、created_at 字段。
    可用于回答「我们之前聊过某某话题吗」「继续上次的 XX 话题」等回溯需求。

    参数：
        query: 搜索关键词（必填）
        top_k: 返回数量上限，默认 3
        time_range: "recent"（默认，最近 7 天）或 "all"（全部）
        student_id: 学员 ID（默认取当前）
        thread_id: 会话 ID（默认取当前）

    返回：
        匹配的话题块列表，每个含 {block_id, topic, summary, source_thread, created_at}
    """
    from src.memory.context import search_thread_blocks_store

    sid = int(student_id or 0)
    tid = (thread_id or "").strip()
    if not sid or not tid:
        return []
    return search_thread_blocks_store(
        student_id=sid,
        thread_id=tid,
        query=(query or "").strip(),
        top_k=top_k,
        time_range=time_range,
    )


@tool
def list_thread_topics(
    student_id: int = 0,
    thread_id: str = "",
) -> list[str]:
    """
    列出当前会话所有已记录的话题标题列表。

    参数：
        student_id: 学员 ID（默认取当前）
        thread_id: 会话 ID（默认取当前）

    返回：
        话题标题字符串列表
    """
    from src.memory.context import list_thread_topics_store

    sid = int(student_id or 0)
    tid = (thread_id or "").strip()
    if not sid or not tid:
        return []
    return list_thread_topics_store(student_id=sid, thread_id=tid)


@tool
def delete_thread_blocks(
    before_days: int | None = None,
    student_id: int = 0,
    thread_id: str = "",
) -> dict:
    """
    删除当前会话的历史话题块。

    参数：
        before_days: 删除 N 天前的块；None 表示删除全部
        student_id: 学员 ID（默认取当前）
        thread_id: 会话 ID（默认取当前）

    返回：
        {ok: bool, deleted: int, detail: str}
    """
    from src.memory.context import delete_thread_blocks_store

    sid = int(student_id or 0)
    tid = (thread_id or "").strip()
    if not sid or not tid:
        return {"ok": False, "deleted": 0, "detail": "缺少 student_id 或 thread_id"}
    deleted = delete_thread_blocks_store(
        student_id=sid,
        thread_id=tid,
        before_days=before_days,
    )
    return {
        "ok": True,
        "deleted": deleted,
        "detail": f"已删除 {deleted} 个话题块",
    }
