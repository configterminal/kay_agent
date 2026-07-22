"""
Graph 检索工具 — 供 Agent 调用的图数据库搜索。
"""

from langchain_core.tools import tool

from src.graph.retriever import graph_search


@tool
def search_course_graph(
    query: str,
    top_k: int = 5,
    course_id: str = "",
) -> list[dict]:
    """
    在课程知识图谱中查找关系型内容。

    适合的问题类型：
    - 对比关系："X 和 Y 有什么区别"
    - 依赖关系："学 A 之前要掌握什么"
    - 关联查询："哪些章节教了 B""XX 涉及哪些知识点"
    - 结构化查询："XX 的组成部分有哪些"

    不适合：纯事实定义类问题（如"什么是 RAG"）→ 请用 search_course_content。

    参数：
        query: 学员的问题（自然语言）
        top_k: 返回结果数，默认 5
        course_id: 可选，限定单课(如 RAG101)

    返回：
        [{content, source, score, section, title, kp_title, ...}, ...]
    """
    cid = (course_id or "").strip() or None
    return graph_search(query, top_k=top_k, course_id=cid)
