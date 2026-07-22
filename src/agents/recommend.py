"""
RecommendAgent — 个性化推荐 Agent。

基于学员画像、进度、薄弱点，给出个性化学习路线推荐。
包含现状分析和人群差异化策略。

使用方式：
    from src.agents.recommend import build_recommend_agent
    agent = build_recommend_agent(coach_style="encouraging", emotion="neutral")
    result = agent.invoke({"messages": [HumanMessage(content="我该学什么")]})
"""

from langgraph.prebuilt import create_react_agent

from src.agents.prompts import build_system_prompt
from src.agents.prompts.recommend import RECOMMEND_ROLE_PROMPT
from src.llm.base import LLMProvider
from src.tools.recommend_tools import (
    get_available_modules,
    get_next_recommendations,
    get_prerequisite_modules,
)
from src.tools.shared_tools import get_student_profile, update_student_profile


def build_recommend_agent(
    coach_style: str = "encouraging",
    emotion: str = "neutral",
):
    """
    构建 RecommendAgent — LangGraph ReAct Agent。

    参数：
        coach_style: 导师人格
        emotion: 当前情绪状态（由 Supervisor 传入）
    """
    llm = LLMProvider.create().get_model(temperature=0.3)

    tools = [
        get_student_profile,
        update_student_profile,
        get_available_modules,
        get_next_recommendations,
        get_prerequisite_modules,
    ]

    system_prompt = build_system_prompt(
        role_prompt=RECOMMEND_ROLE_PROMPT,
        coach_style=coach_style,
        emotion=emotion,
    )

    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,
    )
