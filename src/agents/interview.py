"""
InterviewAgent — 模拟面试（自然对话：提问 / 追问 / 反问 / Offer / 复盘）。

语音开麦与 TTS 在 UI + src/speech 预处理；本 Agent 只处理文本。
student_id 由会话注入，不向学员追问。
"""

from langgraph.prebuilt import create_react_agent

from src.agents.prompts import build_system_prompt
from src.agents.prompts.interview import INTERVIEW_ROLE_PROMPT
from src.agents.student_context import bind_tools_student_id
from src.llm.base import LLMProvider
from src.tools.interview_tools import (
    evaluate_answer,
    generate_interview_report,
    get_interview_questions,
    save_interview_session,
)
from src.tools.jobmatch_tools import get_job_roles
from src.tools.shared_tools import get_student_profile, update_student_profile


def build_interview_agent(
    coach_style: str = "encouraging",
    emotion: str = "neutral",
    student_id: int = 1,
):
    """构建 InterviewAgent — LangGraph ReAct Agent。"""
    llm = LLMProvider.create().get_model(temperature=0.4)

    tools = bind_tools_student_id(
        [
            get_student_profile,
            update_student_profile,
            get_job_roles,
            get_interview_questions,
            evaluate_answer,
            save_interview_session,
            generate_interview_report,
        ],
        student_id,
    )

    system_prompt = build_system_prompt(
        role_prompt=INTERVIEW_ROLE_PROMPT,
        coach_style=coach_style,
        emotion=emotion,
    )

    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,
    )
