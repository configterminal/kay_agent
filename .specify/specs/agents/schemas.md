# Agent 输出 Schema

> 定义子 Agent 的结构化输出格式。Supervisor 拿到 Schema 后可格式化为自然语言或保留结构化数据给 UI 渲染。

## ProgressReport

```python
class ProgressReport(BaseModel):
    completion_pct: float              # 完成百分比 0-100
    total_lessons: int                 # 总课时
    completed_lessons: int             # 已完成
    in_progress_lessons: int           # 进行中
    total_time_minutes: int            # 总学习时长（分钟）
    strongest_modules: list[str]       # 掌握最好的模块（最多3个）
    weakest_modules: list[str]         # 需要加强的模块（最多3个）
    weak_areas: list[str]              # 薄弱知识点（最多5个）
    strong_areas: list[str]            # 强项知识点（最多3个）
    current_streak: int                # 连续学习天数
    is_at_risk: bool                   # 是否懈怠预警
    suggestion: str                    # LLM 生成的改进建议
```

## RecommendationResult

```python
class Recommendation(BaseModel):
    module_id: str
    title: str
    reason: str                    # 为什么推荐
    priority: str                  # high / medium / low
    source: str                    # career_path / weak_area / self_pick_extension / skill_gap
    estimated_hours: int
    prerequisites_met: bool

class RecommendationResult(BaseModel):
    persona: str                   # university_student / working_professional
    current_summary: str           # 现状分析一句话
    recommendations: list[Recommendation]
```

## SkillGapResult（JobMatch；首版可不强制 structured）

```python
class SkillGapItem(BaseModel):
    skill: str
    recommended_module: str | None

class SkillGapResult(BaseModel):
    role_id: str
    role_title: str
    match_pct: float
    mastered: list[str]
    gaps: list[SkillGapItem]
    source: str = "course"         # course | market（未来）
```

见 [jobmatch.md](jobmatch.md)。

## ResumeFeedbackResult（Resume；首版可不强制 structured）

```python
class ResumeBulletRewrite(BaseModel):
    original: str
    rewritten: str
    rationale: str

class ResumeFeedbackResult(BaseModel):
    role_id: str
    mode: str                      # fact | target
    match_score: float
    missing_keywords: list[str]
    matched_keywords: list[str]
    structural_suggestions: list[str]
    content_suggestions: list[str]
    trim_suggestions: list[str]
    rewrites: list[ResumeBulletRewrite]
    source: str = "course"
```

见 [resume.md](resume.md)。
