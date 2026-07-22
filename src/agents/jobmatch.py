"""
JobMatchAgent — 课程覆盖匹配 Agent（MVP）。

对照站内岗位模板与学习进度，给出技能差距与补课建议。
非实时招聘市场匹配。

使用方式：
    from src.agents.jobmatch import build_jobmatch_agent
    agent = build_jobmatch_agent(coach_style="encouraging", emotion="neutral")
"""

from langgraph.prebuilt import create_react_agent

from src.agents.prompts import build_system_prompt
from src.agents.prompts.jobmatch import JOBMATCH_ROLE_PROMPT
from src.agents.student_context import bind_tools_student_id
from src.llm.base import LLMProvider
from src.tools.jobmatch_tools import analyze_skill_gap, get_job_roles
from src.tools.shared_tools import get_student_profile, update_student_profile


def build_jobmatch_agent(
    coach_style: str = "encouraging",
    emotion: str = "neutral",
    student_id: int = 1,
):
    """
    构建 JobMatchAgent — LangGraph ReAct Agent。

    不挂载 get_industry_trends，避免静态假趋势被当作市场真相。
    student_id 由会话注入，不向学员追问。
    """
    llm = LLMProvider.create().get_model(temperature=0.3)

    tools = bind_tools_student_id(
        [
            get_student_profile,
            update_student_profile,
            get_job_roles,
            analyze_skill_gap,
        ],
        student_id,
    )

    system_prompt = build_system_prompt(
        role_prompt=JOBMATCH_ROLE_PROMPT,
        coach_style=coach_style,
        emotion=emotion,
    )

    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,
    )
