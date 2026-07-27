"""
Agent 反思循环 (Reflection Loop)
GENERATE → REFLECT → (REVISE → REFLECT)*  直到合格或达到最大轮数
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from typing_extensions import TypedDict

from src.agents.stream_events import emit_status
from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)


# ── 类型定义 ──

class ReflectionResult(TypedDict):
    """反思审查结果"""
    total_score: int           # 1-10
    dimensions: dict[str, int]  # 各维度打分
    top_issues: list[str]       # 主要问题列表
    passed: bool                # 是否通过


# ── 配置 ──

class ReflectionConfig:
    """反思循环配置"""

    def __init__(
        self,
        max_rounds: int = 3,
        pass_threshold: int = 8,
        min_dimension: int = 5,
    ):
        self.max_rounds = max_rounds
        self.pass_threshold = pass_threshold
        self.min_dimension = min_dimension


# ── 默认评价维度 ──

_DEFAULT_DIMENSIONS = [
    "内容准确性",
    "结构清晰度",
    "语言表达",
    "实用价值",
    "格式规范",
]


# ── 自我审查 ──

def reflect_on_output(
    output: str,
    task_context: str,
    dimensions: list[str] | None = None,
) -> ReflectionResult:
    """
    LLM 自我审查：评价产出质量。

    参数：
        output: Agent 的最终回复文本
        task_context: 任务描述（如 "简历优化 fact/target 双模式"）
        dimensions: 评价维度列表，缺省使用通用维度

    返回：
        ReflectionResult: 包含总分、各维度分、问题列表、是否通过
    """
    dims = dimensions or _DEFAULT_DIMENSIONS
    dims_str = "\n".join(f"- {d}" for d in dims)

    prompt = f"""你是一位严格的质量审查专家。请对以下 AI 助教的产出进行评分。

## 任务背景
{task_context}

## 评价维度（每项 1-10 分）
{dims_str}

## AI 产出内容
---
{output}
---

## 评分要求
1. 逐维度打分，并给出简要理由
2. 给出综合总分（1-10）
3. 列出最关键的 2-5 个问题（如有）
4. 判断是否"通过"：总分 ≥ 8 且所有维度分 ≥ 5

请严格按以下 JSON 格式输出（不要添加任何其他文字）：
```json
{{
  "total_score": 8,
  "dimensions": {{"内容准确性": 8, "结构清晰度": 7, "语言表达": 9, "实用价值": 6, "格式规范": 8}},
  "top_issues": ["某部分表述不够精准", "缺少具体示例"],
  "passed": true
}}
```"""

    try:
        llm = LLMProvider.create().get_model(temperature=0.1)
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.warning("反思审查 LLM 调用失败: %s", e)
        return _fallback_result()

    return _parse_reflection_result(raw)


def _parse_reflection_result(raw: str) -> ReflectionResult:
    """从 LLM 回复中解析 JSON 评分结果。"""

    # 1) 尝试直接 json.loads
    try:
        data = json.loads(raw)
        return _validate_reflection_data(data)
    except json.JSONDecodeError:
        pass

    # 2) 尝试从 ```json ... ``` 代码块中提取
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        try:
            data = json.loads(match.group(1))
            return _validate_reflection_data(data)
        except json.JSONDecodeError:
            pass

    # 3) 尝试用正则匹配最外层 JSON 对象
    match = re.search(r"\{[\s\S]*\"total_score\"[\s\S]*\}", raw)
    if match:
        try:
            data = json.loads(match.group(0))
            return _validate_reflection_data(data)
        except json.JSONDecodeError:
            pass

    logger.warning("反思审查 JSON 解析失败，使用容错结果。原始回复前 200 字: %s", raw[:200])
    return _fallback_result()


def _validate_reflection_data(data: dict[str, Any]) -> ReflectionResult:
    """校验并规范化解析出的数据。"""
    total_score = data.get("total_score", 5)
    if not isinstance(total_score, int) or total_score < 1 or total_score > 10:
        total_score = 5

    dimensions = data.get("dimensions", {})
    if not isinstance(dimensions, dict):
        dimensions = {}

    # 确保各维度分值为 int
    dimensions = {
        k: int(v) if isinstance(v, (int, float)) else 5
        for k, v in dimensions.items()
    }

    top_issues = data.get("top_issues", [])
    if not isinstance(top_issues, list):
        top_issues = []
    top_issues = [str(i) for i in top_issues[:5]]

    passed = data.get("passed", False)
    if not isinstance(passed, bool):
        passed = total_score >= 8

    return ReflectionResult(
        total_score=total_score,
        dimensions=dimensions,
        top_issues=top_issues,
        passed=passed,
    )


def _fallback_result() -> ReflectionResult:
    """解析失败时的容错结果 — 放行不阻塞。"""
    return ReflectionResult(
        total_score=5,
        dimensions={},
        top_issues=["反思解析失败"],
        passed=True,
    )


# ── 内部辅助 ──

def _extract_final_output(result: dict) -> str:
    """从 agent.invoke() 返回的 {"messages": [...]} 中取最后一条足够长的 AIMessage 的 content。
    跳过过短的中间确认消息（如 "我来帮您优化"），取实际产出内容。"""
    from langchain_core.messages import AIMessage

    messages = result.get("messages", [])
    # 反向遍历，取第一条足够长的 AIMessage（≥ 50 字符）
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content.strip()) >= 50:
                return content.strip()
    # 回退：取最后一条（不管长度）
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return ""


def _stream_to_invoke(wrapped, input_data: dict, **kwargs):
    """stream() 兼容适配器：反思阶段统一走 invoke，不对外直播 token。

    supervisor._invoke_agent_maybe_stream 调用 agent.stream() 时，
    返回的 generator 模拟原生 LangGraph stream 格式：("messages", (chunk, metadata))。
    values 模式直接 yield 完整结果 dict。
    """
    stream_mode = kwargs.get("stream_mode")
    result = wrapped(input_data)

    if stream_mode == "values":
        yield ("values", result)
        return

    # messages 模式：逐个 yield 消息作为 (chunk, metadata) 元组
    messages = result.get("messages", [])
    for msg in messages:
        yield ("messages", (msg, {}))


# ── 反思循环包装器 ──

def build_reflection_cycle(
    agent,                      # LangGraph CompiledGraph (ReAct Agent)
    task_context: str,
    dimensions: list[str] | None = None,
    config: ReflectionConfig | None = None,
):
    """
    包装 Agent，注入 GENERATE → REFLECT → (REVISE → REFLECT)* 循环。

    返回的包装对象兼容 agent.invoke() / agent.stream() 调用协议，
    可直接替换 supervisor._invoke_agent_maybe_stream 中的 agent 参数。

    参数：
        agent: LangGraph CompiledGraph（已构建的 ReAct Agent）
        task_context: 任务描述
        dimensions: 评价维度列表
        config: 反思循环配置
    """
    cfg = config or ReflectionConfig()

    def _run(input_data: dict) -> dict:
        """包装后的 Agent 调用，自动执行反思循环。"""
        from langchain_core.messages import HumanMessage

        messages = list(input_data.get("messages", []))

        # ── Round 1: GENERATE ──
        emit_status("generate", f"AI 正在处理：{task_context}…")
        try:
            result = agent.invoke({"messages": messages})
        except Exception as e:
            logger.warning("Agent 首轮生成失败: %s", e)
            raise

        for round_num in range(1, cfg.max_rounds + 1):
            output = _extract_final_output(result)
            if not output.strip():
                logger.warning("Agent 第 %d 轮输出为空，直接返回", round_num)
                return result

            # ── REFLECT ──
            emit_status("reflect", "AI 正在自我审查产出质量…")
            try:
                reflection = reflect_on_output(output, task_context, dimensions)
            except Exception as e:
                logger.warning("reflect_on_output() 异常，跳过反思: %s", e)
                return result

            if reflection["passed"]:
                logger.info("反思审查通过 (总分 %d)，返回结果", reflection["total_score"])
                return result

            # ── 已达最大轮数 ──
            if round_num >= cfg.max_rounds:
                logger.info(
                    "已达最大轮数 %d (总分 %d)，返回最后一轮结果",
                    cfg.max_rounds,
                    reflection["total_score"],
                )
                return result

            # ── REVISE ──
            emit_status(
                "revise",
                f"正在根据审查意见修改…（第{round_num + 1}/{cfg.max_rounds}轮）",
            )

            issues_text = "\n".join(f"- {issue}" for issue in reflection["top_issues"])
            dims_feedback = "\n".join(
                f"- {k}: {v}/10" for k, v in reflection["dimensions"].items()
            )

            revision_prompt = (
                f"【质量审查反馈 — 第{round_num}轮】\n\n"
                f"总分: {reflection['total_score']}/10\n\n"
                f"各维度得分:\n{dims_feedback}\n\n"
                f"需要改进的问题:\n{issues_text}\n\n"
                f"请根据以上反馈，重新生成一份改进后的回复。"
                f"重点关注低分维度和上述问题。"
            )

            # 将反思意见注入 messages，附带上一轮 Agent 的输出上下文
            prev_output_msgs = result.get("messages", [])
            revise_messages = list(messages) + list(prev_output_msgs)
            revise_messages.append(HumanMessage(content=revision_prompt))

            try:
                result = agent.invoke({"messages": revise_messages})
            except Exception as e:
                logger.warning("Agent 第 %d 轮修订失败: %s，返回上一轮结果", round_num + 1, e)
                return result

        return result

    # 兼容 supervisor._invoke_agent_maybe_stream 的 agent.invoke() / agent.stream() 调用
    wrapper = lambda input_data: _run(input_data)
    wrapper.invoke = _run
    wrapper.stream = lambda input_data, **kwargs: _stream_to_invoke(_run, input_data, **kwargs)
    return wrapper
