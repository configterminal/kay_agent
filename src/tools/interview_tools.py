"""
模拟面试工具 — 面试题生成、答案评估、面试报告、会话持久化。

供 InterviewAgent 调用，提供端到端的模拟面试体验。

使用方式：
    from src.tools.interview_tools import (
        get_interview_questions, evaluate_answer,
        generate_interview_report, save_interview_session,
    )
    tools = [get_interview_questions, evaluate_answer, generate_interview_report, save_interview_session]
"""

import json
import uuid
from datetime import datetime

from langchain_core.tools import tool

from src.db.init_db import get_session
from src.db.schema import InterviewSession, JobRole
from src.llm.base import LLMProvider


def _get_llm(temperature: float = 0.3):
    """获取 LLM 实例的快捷方法"""
    provider = LLMProvider.create()
    return provider.get_model(temperature=temperature)


# ── 面试题生成 ──────────────────────────────────────

@tool
def get_interview_questions(role_id: str, difficulty: str = "medium", count: int = 5) -> list[dict]:
    """
    用 LLM 为指定岗位生成模拟面试题目。

    参数：
        role_id: 岗位ID，如 "backend_engineer"
        difficulty: 难度等级 — "easy" | "medium" | "hard"，默认 "medium"
        count: 生成题目数量，默认 5

    返回：
        [{
            question_id: str,          # 题目唯一ID（UUID）
            text: str,                 # 面试题文本
            type: str,                 # 题型 — "technical" | "behavioral" | "system_design"
            expected_topics: [str]     # 期望回答应涵盖的知识点
        }, ...]
    """
    # 获取岗位信息以生成更精准的题目
    with get_session() as session:
        role = session.query(JobRole).filter(JobRole.role_id == role_id).first()

    role_title = role.title if role else role_id
    role_skills = role.required_skills if role and role.required_skills else []
    role_desc = role.description if role and role.description else ""
    skills_str = ", ".join(role_skills) if role_skills else "通用技术能力"

    difficulty_map = {
        "easy": "初级（考察基础概念和简单应用）",
        "medium": "中级（考察理解深度和实际项目经验）",
        "hard": "高级（考察系统设计、架构能力和最佳实践）",
    }
    diff_desc = difficulty_map.get(difficulty, difficulty_map["medium"])

    prompt = f"""你是一位资深技术面试官。请为以下岗位生成 {count} 道{diff_desc}的模拟面试题。

岗位名称：{role_title}
岗位描述：{role_desc}
核心技能：{skills_str}

题型分配建议：
- technical（技术题）：约 60%，考察具体技术知识和编码能力
- behavioral（行为题）：约 20%，考察沟通协作和项目经验
- system_design（系统设计题）：约 20%，考察架构设计能力

请返回纯 JSON 数组（不要包含 markdown 代码块标记），格式如下：
[
    {{
        "text": "面试题文本",
        "type": "technical/behavioral/system_design",
        "expected_topics": ["知识点1", "知识点2", ...]
    }},
    ...
]

要求：
- 题目贴近真实面试场景，避免过于学术化
- expected_topics 每个题至少 2 个知识点
- 题目不要重复，覆盖不同技能方向
- 行为题要结合岗位级别的实际工作场景"""

    try:
        llm = _get_llm(temperature=0.8)  # 较高温度以增加题目多样性
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        questions = json.loads(content)

        if not isinstance(questions, list):
            return []

        # 为每道题添加唯一 ID 并限制数量
        result = []
        for i, q in enumerate(questions[:count]):
            result.append({
                "question_id": str(uuid.uuid4()),
                "text": q.get("text", ""),
                "type": q.get("type", "technical"),
                "expected_topics": q.get("expected_topics", []),
            })
        return result
    except (json.JSONDecodeError, Exception):
        # LLM 解析失败时返回空列表
        return []


# ── 答案评估 ────────────────────────────────────────

@tool
def evaluate_answer(question: str, answer: str, role_id: str) -> dict:
    """
    用 LLM 对学员的面试回答进行评分和评估。

    参数：
        question: 面试题文本
        answer: 学员的回答文本
        role_id: 岗位ID（用于评估岗位相关性）

    返回：
        {
            score: float,           # 评分 0-10
            strengths: [str],       # 回答的优点
            weaknesses: [str],      # 回答的不足
            model_answer: str       # 参考答案（示范性回答）
        }
        若 answer 为空，score 为 0 并提示学员先作答
    """
    if not answer or not answer.strip():
        return {
            "score": 0.0,
            "strengths": [],
            "weaknesses": ["学员未提供回答，请先完成作答"],
            "model_answer": "",
        }

    # 获取岗位信息
    with get_session() as session:
        role = session.query(JobRole).filter(JobRole.role_id == role_id).first()
    role_title = role.title if role else role_id

    prompt = f"""你是一位严格的面试官，正在评估候选人对以下面试题的回答。

目标岗位：{role_title}

面试题：
{question}

候选人回答：
{answer}

请返回纯 JSON（不要包含 markdown 代码块标记），格式如下：
{{
    "score": 数字(0-10, 保留一位小数),
    "strengths": ["优点1", "优点2", ...],
    "weaknesses": ["不足1", "不足2", ...],
    "model_answer": "一段高质量的参考答案，150-300字，展示理想回答的结构和深度"
}}

评分标准：
- 0-3：完全答错或答非所问，缺乏基本概念
- 4-5：部分正确，但深度不足或有明显错误
- 6-7：基本正确，覆盖了主要知识点，但表达或结构可优化
- 8-9：正确且全面，有实际经验支撑，逻辑清晰
- 10：完美回答，展现深入理解和最佳实践，超出预期

注意：
- strengths 和 weaknesses 每条要具体、可操作，不要泛泛而谈
- model_answer 要展示该题目的理想回答方式，供学员对照学习"""

    try:
        llm = _get_llm(temperature=0.2)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        result = json.loads(content)

        return {
            "score": round(float(result.get("score", 0)), 1),
            "strengths": result.get("strengths", []),
            "weaknesses": result.get("weaknesses", []),
            "model_answer": result.get("model_answer", ""),
        }
    except (json.JSONDecodeError, Exception):
        return {
            "score": 0.0,
            "strengths": [],
            "weaknesses": ["评分系统异常，请稍后重试"],
            "model_answer": "",
        }


# ── 面试报告生成 ────────────────────────────────────

@tool
def generate_interview_report(session_id: str) -> dict:
    """
    从数据库加载面试会话，聚合所有题目得分，用 LLM 生成综合反馈和改进计划。

    规则：
      - total_score >= 70：模拟 Offer（包含岗位、薪资区间、条件）
      - total_score < 50：建议更多准备后再尝试
      - 其他情况：给出具体改进计划

    参数：
        session_id: 面试会话ID（UUID 字符串）

    返回：
        {
            total_score: float,                     # 总分（所有题目平均分映射到 0-100）
            by_question: [{question, answer, score, strengths, weaknesses}, ...],
            overall_feedback: str,                  # LLM 生成的综合评价
            improvement_plan: [str],                # 改进计划列表
            offer: dict | None                      # 模拟 Offer（分数 >= 70 时填充）
                {role, salary_range, conditions, accepted}
        }
        若 session_id 不存在，返回各字段为空的默认结构
    """
    with get_session() as session:
        interview = (
            session.query(InterviewSession)
            .filter(InterviewSession.id == session_id)
            .first()
        )

        if not interview:
            return {
                "total_score": 0.0,
                "by_question": [],
                "overall_feedback": "面试会话不存在，请检查 session_id",
                "improvement_plan": [],
                "offer": None,
            }

        # 提取面试数据
        questions = interview.questions or []
        answers = interview.answers or []
        feedback_list = interview.feedback or []

        # 按题目整理评估数据
        by_question = []
        total_score_sum = 0.0
        question_count = 0

        for i in range(max(len(questions), len(answers))):
            q_text = questions[i].get("text", "") if i < len(questions) else ""
            a_text = answers[i].get("text", "") if i < len(answers) else ""
            fb = feedback_list[i] if i < len(feedback_list) else {}

            q_score = fb.get("score", 0) if isinstance(fb, dict) else 0
            total_score_sum += q_score
            question_count += 1

            by_question.append({
                "question": q_text,
                "answer": a_text,
                "score": q_score,
                "strengths": fb.get("strengths", []) if isinstance(fb, dict) else [],
                "weaknesses": fb.get("weaknesses", []) if isinstance(fb, dict) else [],
            })

        # 将 0-10 分映射到 0-100
        avg_score = total_score_sum / question_count if question_count > 0 else 0
        total_score = round(avg_score * 10, 1)

        # 获取岗位信息
        role = (
            session.query(JobRole)
            .filter(JobRole.role_id == interview.job_role_id)
            .first()
        ) if interview.job_role_id else None

    # 用 LLM 生成综合评价和改进计划
    strengths_summary = []
    weaknesses_summary = []
    for item in by_question:
        strengths_summary.extend(item.get("strengths", []))
        weaknesses_summary.extend(item.get("weaknesses", []))

    role_title = role.title if role else (interview.job_role_id or "未知岗位")

    prompt = f"""你是一位资深技术面试官，刚完成一场模拟面试。请根据以下数据生成综合评价和改进计划。

岗位：{role_title}
总分：{total_score}/100
题目数量：{question_count}

各题表现亮点：{json.dumps(strengths_summary[:10], ensure_ascii=False)}
各题主要问题：{json.dumps(weaknesses_summary[:10], ensure_ascii=False)}

请返回纯 JSON（不要包含 markdown 代码块标记），格式如下：
{{
    "overall_feedback": "200-400字的综合评价，涵盖技术能力、沟通表达、逻辑思维等维度",
    "improvement_plan": ["具体可执行的改进建议1", "建议2", "建议3", ...]
}}

要求：
- overall_feedback 要有针对性，不要泛泛而谈，引用具体的优势和不足
- improvement_plan 每条要具体可执行，给出明确的学习方向或练习方法
- improvement_plan 至少 3 条"""

    try:
        llm = _get_llm(temperature=0.4)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        llm_result = json.loads(content)

        overall_feedback = llm_result.get("overall_feedback", "")
        improvement_plan = llm_result.get("improvement_plan", [])
    except (json.JSONDecodeError, Exception):
        overall_feedback = f"面试总结：共 {question_count} 题，总分 {total_score} 分。"
        improvement_plan = ["建议重新进行模拟面试以获得更详细的反馈"]

    # 生成模拟 Offer（总分 >= 70）
    offer = None
    if total_score >= 70:
        salary_range = role.salary_range if role and role.salary_range else "面议"
        offer = {
            "role": role_title,
            "salary_range": salary_range,
            "conditions": "通过技术面，建议进入 HR 面（模拟结果仅供参考）",
            "accepted": True,
        }
    elif total_score < 50:
        # 分数过低时在反馈中追加建议
        improvement_plan.insert(
            0,
            f"当前总分 {total_score} 分，建议先系统学习 {role_title} 的核心技能，再进行模拟面试"
        )

    return {
        "total_score": total_score,
        "by_question": by_question,
        "overall_feedback": overall_feedback,
        "improvement_plan": improvement_plan,
        "offer": offer,
    }


# ── 面试会话保存 ────────────────────────────────────

@tool
def save_interview_session(
    student_id: int,
    role_id: str,
    questions: list[dict],
    answers: list[dict],
) -> str:
    """
    将模拟面试的题目和回答保存到 interview_sessions 表。

    参数：
        student_id: 学员ID
        role_id: 岗位ID
        questions: 面试题列表 [{question_id, text, type, expected_topics}, ...]
        answers: 学员回答列表 [{question_id, text}, ...]

    返回：
        生成的 session_id（字符串），用于后续生成面试报告
    """
    # 按 question_id 匹配题目和回答，构建完整记录
    question_map = {q.get("question_id", ""): q for q in questions}

    saved_questions = []
    saved_answers = []
    saved_feedback = []

    for answer_entry in answers:
        q_id = answer_entry.get("question_id", "")
        question_data = question_map.get(q_id, {})

        saved_questions.append({
            "question_id": q_id,
            "text": question_data.get("text", ""),
            "type": question_data.get("type", ""),
            "expected_topics": question_data.get("expected_topics", []),
        })
        saved_answers.append({
            "question_id": q_id,
            "text": answer_entry.get("text", ""),
        })
        # feedback 留空 — 由 evaluate_answer 工具逐题填充后再 update
        saved_feedback.append({
            "question_id": q_id,
            "score": 0,
            "strengths": [],
            "weaknesses": [],
            "model_answer": "",
        })

    # 生成唯一 session_id（使用 UUID 字符串，不与数据库自增 id 冲突）
    session_id = str(uuid.uuid4())

    with get_session() as session:
        interview_record = InterviewSession(
            id=session_id,
            student_id=student_id,
            job_role_id=role_id,
            questions=saved_questions,
            answers=saved_answers,
            feedback=saved_feedback,
            score=0,  # 初始分 0，后续通过 generate_interview_report 更新
            offer_details=None,
            created_at=datetime.utcnow(),
        )
        session.add(interview_record)
        session.commit()

    return session_id
