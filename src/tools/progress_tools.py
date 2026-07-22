"""
ProgressAgent 工具 — 学习进度追踪和分析所需的数据查询函数。

每个工具用 @tool 装饰器注册，供 LangChain Agent 调用。

使用方式：
    from src.tools.progress_tools import (
        get_student_progress, get_quiz_history, get_weak_areas,
        get_strong_areas, get_study_streak, generate_progress_report,
    )
    tools = [get_student_progress, get_quiz_history, get_weak_areas, get_strong_areas, get_study_streak, generate_progress_report]
"""

from collections import Counter
from datetime import datetime, timedelta

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import func

from src.db.init_db import get_session
from src.db.schema import Student, LearningProgress, QuizAttempt, CourseModule
from src.llm.base import LLMProvider


# ── Pydantic 输出模型 ──────────────────────────────────

class ProgressReport(BaseModel):
    """学习进度综合报告 — 由 generate_progress_report 工具返回的结构化数据"""
    overall_score: float = Field(description="综合评分（0-100），基于完成率、测验成绩、学习频率综合计算")
    completion_pct: float = Field(description="课程整体完成百分比（0-100）")
    strongest_modules: list[str] = Field(description="掌握最好的模块标题列表（Top 3）")
    weakest_modules: list[str] = Field(description="需要加强的模块标题列表（Bottom 3）")
    weak_areas: list[str] = Field(description="薄弱知识点高频词列表（Top 5）")
    study_streak: int = Field(description="当前连续学习天数")
    suggestion: str = Field(description="LLM 生成的个性化学习建议（200 字以内）")


# ── 工具1：学习进度汇总 ──────────────────────────────────

@tool
def get_student_progress(student_id: int) -> dict:
    """
    查询指定学员的学习进度，按模块聚合完成状态和耗时。

    参数：
        student_id: 学员ID

    返回：
        {
            total_lessons: 总课时数,
            completed: 已完成课时数,
            in_progress: 进行中课时数,
            completion_pct: 完成百分比（0-100）,
            modules: [{module_id, title, status, time_spent}, ...]
        }
    """
    with get_session() as session:
        # 获取所有学习进度记录
        records = (
            session.query(LearningProgress)
            .filter(LearningProgress.student_id == student_id)
            .all()
        )

        # 按 module_id 聚合统计
        module_stats: dict[str, dict] = {}
        for r in records:
            mid = r.module_id or "unknown"
            if mid not in module_stats:
                module_stats[mid] = {
                    "module_id": mid,
                    "total": 0,
                    "completed": 0,
                    "in_progress": 0,
                    "time_spent": 0,
                }
            module_stats[mid]["total"] += 1
            module_stats[mid]["time_spent"] += r.time_spent_minutes or 0
            if r.status == "completed":
                module_stats[mid]["completed"] += 1
            elif r.status == "in_progress":
                module_stats[mid]["in_progress"] += 1

        # 补充模块标题（从 CourseModule 表查）
        module_ids = list(module_stats.keys())
        if module_ids:
            courses = (
                session.query(CourseModule)
                .filter(CourseModule.module_id.in_(module_ids))
                .all()
            )
            title_map = {c.module_id: c.title or c.module_id for c in courses}
        else:
            title_map = {}

        # 计算全局统计
        total_lessons = len(records)
        total_completed = sum(m["completed"] for m in module_stats.values())
        total_in_progress = sum(m["in_progress"] for m in module_stats.values())
        completion_pct = round((total_completed / total_lessons * 100), 1) if total_lessons > 0 else 0.0

        # 判断每个模块的整体状态
        modules_result = []
        for mid, stats in module_stats.items():
            if stats["completed"] == stats["total"]:
                status = "completed"
            elif stats["in_progress"] > 0 or stats["completed"] > 0:
                status = "in_progress"
            else:
                status = "not_started"
            modules_result.append({
                "module_id": mid,
                "title": title_map.get(mid, mid),
                "status": status,
                "time_spent": stats["time_spent"],
            })

    return {
        "total_lessons": total_lessons,
        "completed": total_completed,
        "in_progress": total_in_progress,
        "completion_pct": completion_pct,
        "modules": modules_result,
    }


# ── 工具2：测验历史 ──────────────────────────────────────

@tool
def get_quiz_history(student_id: int) -> list[dict]:
    """
    查询指定学员的所有测验记录，包括得分和薄弱知识点。

    参数：
        student_id: 学员ID

    返回：
        [{module_id, quiz_id, score, max_score, weak_areas, attempted_at}, ...]，
        按测验时间倒序排列
    """
    with get_session() as session:
        records = (
            session.query(QuizAttempt)
            .filter(QuizAttempt.student_id == student_id)
            .order_by(QuizAttempt.attempted_at.desc())
            .all()
        )

    return [
        {
            "module_id": r.module_id,
            "quiz_id": r.quiz_id,
            "score": r.score,
            "max_score": r.max_score,
            "weak_areas": r.weak_areas or [],
            "attempted_at": r.attempted_at.isoformat() if r.attempted_at else None,
        }
        for r in records
    ]


# ── 工具3：薄弱知识点分析 ────────────────────────────────

@tool
def get_weak_areas(student_id: int) -> list[dict]:
    """
    汇总学员在所有测验中暴露的薄弱知识点，按出现频率降序排列。

    参数：
        student_id: 学员ID

    返回：
        [{topic, error_count, last_error_at}, ...]，按错误次数降序
    """
    with get_session() as session:
        records = (
            session.query(QuizAttempt)
            .filter(
                QuizAttempt.student_id == student_id,
                QuizAttempt.weak_areas.isnot(None),
            )
            .all()
        )

    # 用 Counter 聚合薄弱知识点频率
    topic_counter: Counter = Counter()
    topic_last_time: dict[str, datetime] = {}

    for r in records:
        for topic in (r.weak_areas or []):
            topic_counter[topic] += 1
            if r.attempted_at:
                if topic not in topic_last_time or r.attempted_at > topic_last_time[topic]:
                    topic_last_time[topic] = r.attempted_at

    # 按频率降序排列
    result = []
    for topic, count in topic_counter.most_common():
        result.append({
            "topic": topic,
            "error_count": count,
            "last_error_at": topic_last_time[topic].isoformat() if topic in topic_last_time else None,
        })

    return result


# ── 工具4：优势知识点分析 ────────────────────────────────

@tool
def get_strong_areas(student_id: int) -> list[dict]:
    """
    分析学员高得分测验中的优势知识点，基于近期测验成绩。

    通过检查 quiz_attempts 表中 score/max_score >= 0.8 的测验记录，
    并结合模块信息推断学员掌握较好的领域。

    参数：
        student_id: 学员ID

    返回：
        [{topic, avg_score, quiz_count}, ...]，按平均分降序排列
    """
    with get_session() as session:
        records = (
            session.query(QuizAttempt)
            .filter(QuizAttempt.student_id == student_id)
            .all()
        )

    if not records:
        return []

    # 按 module_id 聚合：只统计表现好的模块（该模块下所有测验平均分 >= 80%）
    module_scores: dict[str, list[float]] = {}
    module_count: dict[str, int] = {}
    for r in records:
        mid = r.module_id or "unknown"
        if mid not in module_scores:
            module_scores[mid] = []
            module_count[mid] = 0
        if r.score is not None and r.max_score is not None and r.max_score > 0:
            module_scores[mid].append(r.score / r.max_score * 100)
        module_count[mid] += 1

    # 补充模块标题
    module_ids = list(module_scores.keys())
    title_map: dict[str, str] = {}
    if module_ids:
        courses = (
            session.query(CourseModule)
            .filter(CourseModule.module_id.in_(module_ids))
            .all()
        )
        title_map = {c.module_id: c.title or c.module_id for c in courses}

    result = []
    for mid, scores in module_scores.items():
        if not scores:
            continue
        avg = round(sum(scores) / len(scores), 1)
        if avg >= 80:  # 只输出掌握较好的领域
            result.append({
                "topic": title_map.get(mid, mid),
                "avg_score": avg,
                "quiz_count": module_count[mid],
            })

    # 按平均分降序
    result.sort(key=lambda x: x["avg_score"], reverse=True)
    return result


# ── 工具5：学习连续天数 ──────────────────────────────────

@tool
def get_study_streak(student_id: int) -> dict:
    """
    计算学员的连续学习天数（streak），基于 learning_progress.last_accessed_at。

    逻辑：
    - current_streak: 从最近一次学习日往前倒推，连续有记录的天数
    - longest_streak: 历史最长连续天数
    - is_at_risk: 如果距上次学习超过 7 天，标记为流失风险

    参数：
        student_id: 学员ID

    返回：
        {
            current_streak: 当前连续学习天数,
            longest_streak: 历史最长连续学习天数,
            last_study_date: 最近学习日期（ISO 格式）,
            days_since_last: 距上次学习天数,
            is_at_risk: 是否有流失风险（True/False）
        }
    """
    with get_session() as session:
        records = (
            session.query(LearningProgress.last_accessed_at)
            .filter(
                LearningProgress.student_id == student_id,
                LearningProgress.last_accessed_at.isnot(None),
            )
            .order_by(LearningProgress.last_accessed_at.asc())
            .all()
        )

    if not records:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "last_study_date": None,
            "days_since_last": -1,
            "is_at_risk": True,
        }

    # 提取所有有学习记录的日期（去重、排序）
    study_dates = sorted({r.last_accessed_at.date() for r in records})

    today = datetime.utcnow().date()

    # 计算 current_streak：从最近一天往前倒推，连续有记录的天数
    last_study_date = study_dates[-1]
    days_since_last = (today - last_study_date).days

    current_streak = 0
    # 如果今天或昨天有学习，则计算连续天数
    if days_since_last <= 1:
        current_streak = 1
        # 从倒数第二天开始往前检查
        for i in range(len(study_dates) - 2, -1, -1):
            expected = study_dates[i + 1] - timedelta(days=1)
            if study_dates[i] == expected:
                current_streak += 1
            else:
                break

    # 计算 longest_streak：全局遍历一次
    longest_streak = 1
    current_run = 1
    for i in range(1, len(study_dates)):
        if study_dates[i] == study_dates[i - 1] + timedelta(days=1):
            current_run += 1
        else:
            longest_streak = max(longest_streak, current_run)
            current_run = 1
    longest_streak = max(longest_streak, current_run)

    return {
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "last_study_date": last_study_date.isoformat(),
        "days_since_last": days_since_last,
        "is_at_risk": days_since_last > 7,
    }


# ── 工具6：综合进度报告 ──────────────────────────────────

@tool
def generate_progress_report(student_id: int) -> ProgressReport:
    """
    生成学员综合学习进度报告，汇总以上所有指标，并用 LLM 生成个性化建议。

    聚合了学习进度、测验成绩、薄弱/优势知识点、学习连续性等数据，
    调用 LLMProvider 将原始数据总结为可读的结构化报告。

    参数：
        student_id: 学员ID

    返回：
        ProgressReport: {
            overall_score: 综合评分（0-100）,
            completion_pct: 完成百分比,
            strongest_modules: 最强模块标题列表,
            weakest_modules: 最弱模块标题列表,
            weak_areas: 薄弱知识点列表,
            study_streak: 当前连续学习天数,
            suggestion: LLM 生成的个性化建议
        }
    """
    # 聚合所有子工具的数据
    progress = get_student_progress.invoke({"student_id": student_id})
    quiz_history = get_quiz_history.invoke({"student_id": student_id})
    weak_areas = get_weak_areas.invoke({"student_id": student_id})
    strong_areas = get_strong_areas.invoke({"student_id": student_id})
    streak = get_study_streak.invoke({"student_id": student_id})

    # 提取结构
    completion_pct = progress["completion_pct"]
    study_streak = streak["current_streak"]

    strongest_modules = [item["topic"] for item in strong_areas[:3]]
    weakest_modules = [item["topic"] for item in weak_areas[:3]]
    weak_areas_topics = [item["topic"] for item in weak_areas[:5]]

    # 计算 overall_score
    # 公式：完成率占 40% + 测验平均分占 40% + streak 活跃度占 20%
    if quiz_history:
        valid_quizzes = [
            q for q in quiz_history
            if q["score"] is not None and q["max_score"] is not None and q["max_score"] > 0
        ]
        avg_quiz_pct = (
            sum(q["score"] / q["max_score"] * 100 for q in valid_quizzes) / len(valid_quizzes)
        ) if valid_quizzes else 0.0
    else:
        avg_quiz_pct = 0.0

    streak_score = min(study_streak / 30.0 * 100, 100)  # 30 天连续学习 = 满分

    overall_score = round(
        completion_pct * 0.4 + avg_quiz_pct * 0.4 + streak_score * 0.2,
        1,
    )

    # 用 LLM 生成个性化建议
    llm = LLMProvider.create()
    model = llm.get_model(temperature=0.3)
    prompt = _build_suggestion_prompt(
        completion_pct=completion_pct,
        overall_score=overall_score,
        strongest=strongest_modules,
        weakest=weakest_modules,
        weak_topics=weak_areas_topics,
        study_streak=study_streak,
        is_at_risk=streak["is_at_risk"],
    )
    response = model.invoke(prompt)
    suggestion = str(response.content).strip()

    return ProgressReport(
        overall_score=overall_score,
        completion_pct=completion_pct,
        strongest_modules=strongest_modules,
        weakest_modules=weakest_modules,
        weak_areas=weak_areas_topics,
        study_streak=study_streak,
        suggestion=suggestion,
    )


# ── LLM Prompt 构建辅助 ─────────────────────────────────

def _build_suggestion_prompt(
    completion_pct: float,
    overall_score: float,
    strongest: list[str],
    weakest: list[str],
    weak_topics: list[str],
    study_streak: int,
    is_at_risk: bool,
) -> str:
    """构建生成个性化学习建议的 prompt"""
    strongest_str = "、".join(strongest) if strongest else "暂无数据"
    weakest_str = "、".join(weakest) if weakest else "暂无数据"
    weak_topics_str = "、".join(weak_topics) if weak_topics else "暂无数据"
    risk_warning = (
        "学员已超过 7 天未学习，有流失风险，建议温和提醒并降低学习门槛。"
        if is_at_risk else ""
    )

    return f"""你是一位 AI 助教，请根据以下学习数据为学员撰写一段个性化学习建议（200 字以内）。

【学习数据】
- 课程完成率：{completion_pct}%
- 综合评分：{overall_score}/100
- 优势模块：{strongest_str}
- 薄弱模块：{weakest_str}
- 薄弱知识点：{weak_topics_str}
- 连续学习天数：{study_streak} 天
{risk_warning}

【要求】
- 语气鼓励、积极，但建议要具体可操作
- 先肯定学员的努力和优势
- 再针对薄弱点给出 1-2 条具体改进建议
- {risk_warning + " 建议从最简单的模块重新开始，找回学习节奏。" if is_at_risk else ""}
- 用中文回复，不超过 200 字"""
