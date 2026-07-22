"""
Agent 输出 Schema — Pydantic 模型定义。

Supervisor 可根据需要将结构化输出格式化为自然语言。
"""

from pydantic import BaseModel, Field


class ProgressReport(BaseModel):
    """学习进度报告"""
    completion_pct: float = Field(description="完成百分比 0-100")
    total_lessons: int = Field(description="总课时")
    completed_lessons: int = Field(description="已完成课时")
    in_progress_lessons: int = Field(description="进行中课时")
    total_time_minutes: int = Field(description="总学习时长（分钟）")
    strongest_modules: list[str] = Field(default_factory=list, description="掌握最好的模块，最多3个")
    weakest_modules: list[str] = Field(default_factory=list, description="需要加强的模块，最多3个")
    weak_areas: list[str] = Field(default_factory=list, description="薄弱知识点，最多5个")
    strong_areas: list[str] = Field(default_factory=list, description="强项知识点，最多3个")
    current_streak: int = Field(default=0, description="连续学习天数")
    is_at_risk: bool = Field(default=False, description="是否懈怠预警")
    suggestion: str = Field(default="", description="LLM 生成的改进建议")


# ── RecommendAgent ──────────────────────────────────

class Recommendation(BaseModel):
    """单条推荐"""
    module_id: str = Field(description="模块 ID")
    title: str = Field(description="模块标题")
    reason: str = Field(description="推荐理由")
    priority: str = Field(description="high / medium / low")
    source: str = Field(description="career_path / weak_area / self_pick_extension / skill_gap")
    estimated_hours: int = Field(description="预估学习时长")
    prerequisites_met: bool = Field(description="前置课程是否已完成")


class RecommendationResult(BaseModel):
    """推荐结果"""
    persona: str = Field(description="university_student / working_professional")
    current_summary: str = Field(description="现状分析一句话总结")
    recommendations: list[Recommendation] = Field(default_factory=list, description="推荐列表")


# ── JobMatchAgent（首版自然语言；Schema 预留）────────

class SkillGapItem(BaseModel):
    """单项技能差距"""
    skill: str = Field(description="技能名")
    recommended_module: str | None = Field(
        default=None, description="推荐补课 module_id；无课则为 null"
    )


class SkillGapResult(BaseModel):
    """课程覆盖匹配结果（非实时市场 JD）"""
    role_id: str = Field(description="站内岗位模板 ID")
    role_title: str = Field(default="", description="岗位标题")
    match_pct: float = Field(description="必需技能匹配百分比 0-100")
    mastered: list[str] = Field(default_factory=list, description="已覆盖技能")
    gaps: list[SkillGapItem] = Field(default_factory=list, description="待补技能")
    source: str = Field(
        default="course",
        description="course=站内课程模板；market=未来市场数据源",
    )


# ── ResumeAgent（首版自然语言；Schema 预留）──────────

class ResumeBulletRewrite(BaseModel):
    """单条改前改后"""
    original: str = Field(description="原文")
    rewritten: str = Field(description="改后 STAR")
    rationale: str = Field(default="", description="改写理由")


class ResumeFeedbackResult(BaseModel):
    """简历优化结果（站内方向；非实时 ATS）"""
    role_id: str = Field(description="站内岗位模板 ID")
    mode: str = Field(description="fact | target")
    match_score: float = Field(description="相对站内方向匹配分 0-100")
    missing_keywords: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    structural_suggestions: list[str] = Field(default_factory=list)
    content_suggestions: list[str] = Field(default_factory=list)
    trim_suggestions: list[str] = Field(default_factory=list)
    rewrites: list[ResumeBulletRewrite] = Field(default_factory=list)
    source: str = Field(default="course", description="course | market")
