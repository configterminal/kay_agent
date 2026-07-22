"""
ProgressAgent — 进度追踪 Agent。

查询学习进度、测验记录、薄弱点分析，生成结构化学习报告。

使用方式：
    from src.agents.progress import build_progress_agent
    agent = build_progress_agent(coach_style="encouraging", emotion="neutral")
    result = agent.invoke({"messages": [HumanMessage(content="我的学习进度怎么样")]})
"""

from langgraph.prebuilt import create_react_agent

from src.agents.prompts import build_system_prompt
from src.agents.prompts.progress import PROGRESS_ROLE_PROMPT
from src.llm.base import LLMProvider
from src.tools.progress_tools import (
    get_student_progress,
    get_quiz_history,
    get_weak_areas,
    get_strong_areas,
    get_study_streak,
    generate_progress_report,
)


def build_progress_agent(
    coach_style: str = "encouraging",
    emotion: str = "neutral",
):
    """
    构建 ProgressAgent — LangGraph ReAct Agent。

    参数：
        coach_style: 导师人格
        emotion: 当前情绪状态（由 Supervisor 传入）
    """
    llm = LLMProvider.create().get_model(temperature=0.3)

    tools = [
        get_student_progress,
        get_quiz_history,
        get_weak_areas,
        get_strong_areas,
        get_study_streak,
        generate_progress_report,
    ]

    system_prompt = build_system_prompt(
        role_prompt=PROGRESS_ROLE_PROMPT,
        coach_style=coach_style,
        emotion=emotion,
    )

    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,
    )
