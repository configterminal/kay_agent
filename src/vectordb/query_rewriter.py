"""
查询重写器 — 条件路由 + 三种重写策略。

根据问题类型自动选择最合适的重写方式：
  AMBIGUOUS → 历史感知改写（指代消解）
  FUZZY     → HyDE（假答案生成）
  VERBOSE   → MultiQuery（多角度重写）
  DIRECT    → 透传

使用方式：
    from src.vectordb.query_rewriter import rewrite_query
    queries = rewrite_query("它怎么工作的", chat_history=["RAG三大核心是什么"])
    # → ["RAG三大核心中检索模块的工作原理"]
"""

import json
import re
from enum import Enum

from langchain_core.messages import HumanMessage, AIMessage

from src.llm.base import LLMProvider


# ── 问题类型 ──────────────────────────────────────

class QueryType(str, Enum):
    AMBIGUOUS = "ambiguous"  # 有指代词，依赖上下文
    FUZZY = "fuzzy"          # 太短太泛，缺少术语
    VERBOSE = "verbose"       # 有术语但表达啰嗦
    DIRECT = "direct"         # 已经很清晰


# ── 分类 Prompt ───────────────────────────────────

_CLASSIFY_PROMPT = """判断以下学员问题的类型，只输出一个词：

- ambiguous：包含指代词（那个、这个、它、前面讲的）或依赖对话上下文才能理解
- fuzzy：太简短或太口语化，缺少具体术语
- verbose：有明确术语但表达啰嗦，需要多角度重写
- direct：已经很清晰，可以直接用于搜索

问题：{query}"""


# ── 历史感知改写 Prompt ───────────────────────────

_HISTORY_REWRITE_PROMPT = """你是查询重写助手。结合对话历史，把学员的模糊问题改写成适合知识库检索的精确查询。

规则：
1. 把指代词（那个、这个、它、他说的、前面讲的）替换成历史中的具体内容
2. 补全口语化表达，但不要添加学员没问的内容
3. 保留课程编号（如 "2-3"、"第2章"），不要改掉
4. 只输出改写后的问题，不要任何解释

对话历史：
{history}

学员当前问题：{query}

改写后："""


# ── HyDE Prompt ──────────────────────────────────

_HYDE_PROMPT = """假设你是这门课程的老师。请用一段话回答学生的问题。
不需要回答得完全准确，但要用课程讲义的风格和术语来表达。

问题：{query}

假答案："""


# ── MultiQuery Prompt ─────────────────────────────

_MULTIQUERY_PROMPT = """你是一个搜索查询专家。把下面这个问题改写成 3 个不同角度的搜索查询，
帮助从课程知识库中找到最全面的答案。

要求：
- 3 个查询用不同的措辞和角度
- 如果问题有技术术语，至少一个查询用通俗表达
- 如果问题太简短，至少一个查询补全相关上下文
- 输出严格 JSON 数组格式：["查询1", "查询2", "查询3"]

问题：{query}"""


# ── 格式化对话历史 ────────────────────────────────

def _format_history(history: list[str]) -> str:
    """把对话历史列表转成可读文本"""
    if not history:
        return "（无历史对话）"
    lines = []
    for i, msg in enumerate(history):
        role = "学员" if i % 2 == 0 else "助教"
        lines.append(f"{role}：{msg}")
    return "\n".join(lines)


# ── 分类 ──────────────────────────────────────────

def classify_query(query: str) -> QueryType:
    """判断查询属于哪种类型（1 次轻量 LLM 调用）"""
    llm = LLMProvider.create().get_model(temperature=0)
    prompt = _CLASSIFY_PROMPT.format(query=query)
    response = llm.invoke(prompt)
    content = response.content.strip().lower() if hasattr(response, 'content') else str(response).strip().lower()

    # 归一化输出
    for qt in QueryType:
        if qt.value in content:
            return qt
    return QueryType.DIRECT


# ── 三种重写策略 ──────────────────────────────────

def history_rewrite(query: str, history: list[str]) -> str:
    """历史感知改写：消解指代词，补全上下文"""
    llm = LLMProvider.create().get_model(temperature=0)
    prompt = _HISTORY_REWRITE_PROMPT.format(
        history=_format_history(history),
        query=query,
    )
    response = llm.invoke(prompt)
    result = response.content.strip() if hasattr(response, 'content') else str(response).strip()
    # 如果 LLM 返回了多余解释，只取第一行
    return result.split("\n")[0]


def hyde(query: str) -> str:
    """HyDE：生成假答案，用假答案去搜索"""
    llm = LLMProvider.create().get_model(temperature=0.3)
    prompt = _HYDE_PROMPT.format(query=query)
    response = llm.invoke(prompt)
    return response.content.strip() if hasattr(response, 'content') else str(response).strip()


def multiquery(query: str, count: int = 3) -> list[str]:
    """多角度重写：生成 count 个不同措辞的查询"""
    llm = LLMProvider.create().get_model(temperature=0.5)
    prompt = _MULTIQUERY_PROMPT.format(query=query)
    response = llm.invoke(prompt)
    content = response.content.strip() if hasattr(response, 'content') else str(response).strip()

    # 尝试解析 JSON 数组
    try:
        # 提取第一个 JSON 数组
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            queries = json.loads(content[start:end])
            if isinstance(queries, list) and len(queries) > 0:
                return queries[:count]
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback：按行拆分
    lines = [l.strip("-• 0123456789. ") for l in content.split("\n") if l.strip()]
    return lines[:count] if lines else [query]


# ── 主入口 ────────────────────────────────────────

def rewrite_query(
    raw_query: str,
    chat_history: list[str] | None = None,
) -> list[str]:
    """
    查询重写主入口 — 条件路由，只执行一种重写策略。

    返回：1~3 条优化后的查询字符串
    """
    import time
    from src.perf import log_timing

    if chat_history is None:
        chat_history = []

    t0 = time.perf_counter()
    try:
        qtype = classify_query(raw_query)
    except Exception:
        # LLM 分类失败 → 默认用原始查询
        log_timing("rag.rewrite.classify_fail", time.perf_counter() - t0)
        return [raw_query]

    try:
        match qtype:
            case QueryType.AMBIGUOUS:
                rewritten = history_rewrite(raw_query, chat_history)
                log_timing("rag.rewrite.strategy", time.perf_counter() - t0, type="ambiguous")
                return [rewritten]

            case QueryType.FUZZY:
                fake_answer = hyde(raw_query)
                log_timing("rag.rewrite.strategy", time.perf_counter() - t0, type="hyde")
                return [fake_answer]

            case QueryType.VERBOSE:
                queries = multiquery(raw_query)
                log_timing("rag.rewrite.strategy", time.perf_counter() - t0, type="multiquery")
                return queries if queries else [raw_query]

            case QueryType.DIRECT:
                log_timing("rag.rewrite.strategy", time.perf_counter() - t0, type="direct")
                return [raw_query]

    except Exception:
        # 单个重写失败 → 降级到原始查询
        return [raw_query]
