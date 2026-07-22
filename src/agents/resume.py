"""
ResumeAgent — 中文技术岗简历优化（fact / target 双模式）。

证据驱动：parse → 画像 → JobMatch/网络定向 → optimize 整页终稿。
student_id 由会话注入，不向学员追问。
"""

from langgraph.prebuilt import create_react_agent

from src.agents.prompts import build_system_prompt
from src.agents.prompts.resume import RESUME_ROLE_PROMPT
from src.agents.student_context import bind_tools_student_id
from src.llm.base import LLMProvider
from src.tools.jobmatch_tools import analyze_skill_gap, get_job_roles
from src.tools.recommend_tools import get_available_modules, get_next_recommendations
from src.tools.resume_tools import (
    build_resume_direct_brief,
    compose_resume_document,
    get_resume_feedback,
    optimize_resume_document,
    parse_resume,
    research_target_role_signals,
    review_resume_document,
    sync_resume_profile,
)
from src.tools.shared_tools import get_student_profile, update_student_profile


def build_resume_agent(
    coach_style: str = "encouraging",
    emotion: str = "neutral",
    student_id: int = 1,
):
    """构建 ResumeAgent — LangGraph ReAct Agent。"""
    llm = LLMProvider.create().get_model(temperature=0.3)

    tools = bind_tools_student_id(
        [
            get_student_profile,
            update_student_profile,
            get_job_roles,
            parse_resume,
            sync_resume_profile,
            build_resume_direct_brief,
            research_target_role_signals,
            get_resume_feedback,
            optimize_resume_document,
            review_resume_document,
            compose_resume_document,
            get_next_recommendations,
            get_available_modules,
            analyze_skill_gap,
        ],
        student_id,
    )

    system_prompt = build_system_prompt(
        role_prompt=RESUME_ROLE_PROMPT,
        coach_style=coach_style,
        emotion=emotion,
    )

    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,
    )
