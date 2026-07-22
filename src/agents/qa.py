"""
QAAgent — 智能答疑 Agent。

基于课程内容的问答，RAG 检索 + LLM 生成，带来源引用。

使用方式：
    from src.agents.qa import build_qa_agent
    agent = build_qa_agent(coach_style="encouraging", emotion="neutral")
    result = agent.invoke({"messages": [HumanMessage(content="什么是RAG")]})
"""

from langgraph.prebuilt import create_react_agent

from src.agents.prompts import build_system_prompt
from src.agents.prompts.qa import QA_ROLE_PROMPT
from src.llm.base import LLMProvider
from src.tools.qa_tools import search_course_content, get_lesson_content, get_qa_history
from src.tools.shared_tools import get_student_profile, update_student_profile
from src.tools.graph_tools import search_course_graph


def build_qa_agent(
    coach_style: str = "encouraging",
    emotion: str = "neutral",
):
    """
    构建 QAAgent — LangGraph ReAct Agent。

    参数：
        coach_style: 导师人格
        emotion: 当前情绪状态（由 Supervisor 传入）
    """
    llm = LLMProvider.create().get_model(temperature=0.3)

    tools = [
        search_course_content,
        search_course_graph,
        get_lesson_content,
        get_qa_history,
        get_student_profile,
        update_student_profile,
    ]

    system_prompt = build_system_prompt(
        role_prompt=QA_ROLE_PROMPT,
        coach_style=coach_style,
        emotion=emotion,
    )

    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,
    )
