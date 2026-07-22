"""
Prompt 工厂 — 运行时组装各个 Agent 的 System Prompt。

组装公式：
    shared_base + coach_prompt + emotion_strategy + role_prompt
"""

from src.agents.prompts.shared import get_shared_base
from src.agents.prompts.coach import get_coach_prompt
from src.agents.prompts.emotion import get_emotion_strategy


def build_system_prompt(
    role_prompt: str,
    coach_style: str = "encouraging",
    emotion: str = "neutral",
) -> str:
    """
    组装完整的 System Prompt。

    参数：
        role_prompt: Agent 专属的职责描述（来自 prompts/qa.py 等）
        coach_style: 人格标识
        emotion: 当前情绪状态（来自 Supervisor 的检测结果）

    返回：
        拼接完成的 System Prompt 字符串
    """
    parts = [
        get_shared_base(),
        get_coach_prompt(coach_style),
        get_emotion_strategy(emotion),
        role_prompt,
    ]
    return "\n\n".join(parts)
