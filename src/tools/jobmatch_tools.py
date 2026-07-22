"""
岗位匹配工具 — 岗位查询、技能差距分析、行业趋势。

供 JobMatchAgent 调用：对照站内课程能力模板与学习进度（非实时招聘市场）。

使用方式：
    from src.tools.jobmatch_tools import get_job_roles, analyze_skill_gap
    tools = [get_job_roles, analyze_skill_gap]  # 勿挂 get_industry_trends
"""

from langchain_core.tools import tool

from src.db.init_db import get_session
from src.db.schema import CourseModule, JobRole, LearningProgress, SkillMapping

# 查询别名 → DB industry 键（与课程 index.json / roles.json 一致）
_INDUSTRY_ALIASES = {
    "it": "IT",
    "IT": "IT",
    "互联网": "IT",
    "人工智能": "IT",
    "ai": "IT",
    "AI": "IT",
    "计算机": "IT",
    "软件": "IT",
    "金融科技": "IT",
}


def normalize_industry(industry: str) -> str:
    """将常见中文/别名归一为岗位表 industry 键。"""
    raw = (industry or "").strip()
    if not raw:
        return "IT"
    if raw in _INDUSTRY_ALIASES:
        return _INDUSTRY_ALIASES[raw]
    key = raw.lower()
    if key in _INDUSTRY_ALIASES:
        return _INDUSTRY_ALIASES[key]
    return raw


def _is_module_covered(module_id: str, completed_module_ids: set[str]) -> bool:
    """
    课程级 module_id(如 RAG101)在任一同课章已完成时也算覆盖。
    章级 id 则精确匹配。
    """
    if not module_id:
        return False
    if module_id in completed_module_ids:
        return True
    # 课程级：completed 含 RAG101-ch02 等前缀，或 course_id 字段指向该课
    prefix = f"{module_id}-"
    if any(mid == module_id or mid.startswith(prefix) for mid in completed_module_ids):
        return True
    return False


# ── 岗位查询 ────────────────────────────────────────

@tool
def get_job_roles(industry: str) -> list[dict]:
    """
    查询指定行业的站内课程对齐岗位模板（非实时招聘市场 JD）。

    参数：
        industry: 行业，如 "IT"、"人工智能"、"互联网"（后两者会归一为 IT）

    返回：
        [{role_id, title, required_skills, preferred_skills, salary_range, description}, ...]
        若该行业无岗位数据，返回空列表
    """
    industry_key = normalize_industry(industry)
    with get_session() as session:
        roles = (
            session.query(JobRole)
            .filter(JobRole.industry == industry_key)
            .all()
        )

    if not roles:
        return []

    return [
        {
            "role_id": r.role_id,
            "title": r.title,
            "required_skills": r.required_skills or [],
            "preferred_skills": r.preferred_skills or [],
            "salary_range": r.salary_range or "薪资未标注",
            "description": r.description or "",
        }
        for r in roles
    ]


# ── 技能差距分析 ────────────────────────────────────

@tool
def analyze_skill_gap(student_id: int, role_id: str) -> dict:
    """
    对比学员已完成的课程模块与目标岗位的技能要求，分析差距。

    逻辑：
      1. 查 learning_progress 表，取 status="completed" 的模块 ID
      2. 查 job_roles 表，取该岗位的 required_skills 列表
      3. 遍历 required_skills，通过 skill_mapping 表找对应 module_id
      4. 学员已完成 → mastered（已掌握）
      5. skill_mapping 有 module_id 但学员未完成 → gap（有对应课程，推荐学习）
      6. skill_mapping 无 module_id（coverage_status="gap" 或无记录）→ gap 且 recommended_module=None（课程缺失）

    参数：
        student_id: 学员ID
        role_id: 岗位ID，如 "rag_ai_engineer"

    返回：
        {
            match_pct: float,         # 技能匹配百分比 (0-100)
            mastered: [str],          # 已掌握的技能名列表
            gaps: [{
                skill: str,           # 缺失的技能名
                recommended_module: str | None  # 推荐课程模块ID，None 表示课程体系中暂无对应课程
            }]
        }
    """
    with get_session() as session:
        # 1. 已完成 module_id；另把「章完成」归并到所属 course_id，便于课程级映射
        completed_records = (
            session.query(LearningProgress.module_id)
            .filter(
                LearningProgress.student_id == student_id,
                LearningProgress.status == "completed",
            )
            .all()
        )
        completed_module_ids = {r.module_id for r in completed_records if r.module_id}
        if completed_module_ids:
            course_rows = (
                session.query(CourseModule.module_id, CourseModule.course_id)
                .filter(CourseModule.module_id.in_(list(completed_module_ids)))
                .all()
            )
            for mid, cid in course_rows:
                if cid:
                    completed_module_ids.add(cid)

        # 2. 获取岗位的技能要求
        role = session.query(JobRole).filter(JobRole.role_id == role_id).first()
        if not role:
            return {
                "match_pct": 0.0,
                "mastered": [],
                "gaps": [],
            }

        required_skills = role.required_skills or []
        if not required_skills:
            return {
                "match_pct": 100.0,
                "mastered": [],
                "gaps": [],
            }

        # 3. 遍历每个必需技能，查 skill_mapping 找对应课程
        mastered = []
        gaps = []

        for skill_name in required_skills:
            mappings = (
                session.query(SkillMapping)
                .filter(
                    SkillMapping.skill_name == skill_name,
                    SkillMapping.role_id == role_id,
                    SkillMapping.is_required == True,
                )
                .all()
            )

            is_mastered = False
            has_any_module = False

            for mapping in mappings:
                if mapping.module_id:
                    has_any_module = True
                    if _is_module_covered(mapping.module_id, completed_module_ids):
                        is_mastered = True
                        break

            if is_mastered:
                mastered.append(skill_name)
            else:
                recommended = None
                if has_any_module:
                    for mapping in mappings:
                        if mapping.module_id and not _is_module_covered(
                            mapping.module_id, completed_module_ids
                        ):
                            recommended = mapping.module_id
                            break

                gaps.append({
                    "skill": skill_name,
                    "recommended_module": recommended,
                })

        # 4. 计算匹配率
        total_required = len(required_skills)
        match_pct = round(len(mastered) / total_required * 100, 1) if total_required > 0 else 100.0

        return {
            "match_pct": match_pct,
            "mastered": mastered,
            "gaps": gaps,
        }


# ── 行业趋势 ────────────────────────────────────────

@tool
def get_industry_trends(industry: str) -> str:
    """
    【未挂载到 JobMatchAgent】静态占位；无可靠数据源前勿对学员宣称市场趋势。

    参数：
        industry: 行业名称

    返回：
        明确标注非实时的说明文案
    """
    key = normalize_industry(industry)
    return (
        f"【{key} / {industry}】当前未接入实时招聘数据源。\n"
        "JobMatch MVP 仅提供站内课程覆盖匹配（get_job_roles + analyze_skill_gap），"
        "请勿将本工具输出当作市场行情。"
    )
