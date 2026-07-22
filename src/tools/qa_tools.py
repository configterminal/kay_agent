"""
QAAgent 工具 — 智能答疑所需的检索和查询函数。

每个工具用 @tool 装饰器注册，供 LangChain Agent 调用。

使用方式：
    from src.tools.qa_tools import search_course_content, get_lesson_content, get_qa_history
    tools = [search_course_content, get_lesson_content, get_qa_history]
"""

from datetime import datetime

from langchain_core.tools import tool

from src.db.init_db import get_session
from src.db.schema import QAHistory
from src.vectordb.retriever import retrieve
from src.vectordb.schema import get_client, ensure_collection, COLLECTION_NAME


# ── 核心检索工具 ──────────────────────────────────

@tool
def search_course_content(
    query: str,
    top_k: int = 5,
    course_id: str = "",
) -> list[dict]:
    """
    在课程知识库中语义搜索相关内容。支持自然语言查询。

    参数：
        query: 学员的问题（自然语言）
        top_k: 返回结果数，默认 5
        course_id: 可选，限定单课(如 RAG101)；有会话焦点时应传入

    返回：
        [{content, source, score, section, title, is_web_search}, ...]
        - content: 文档内容（父文档完整上下文）
        - source: 来源标注（"课程 第X章 第X节"）
        - score: 相关性得分（0-1）
    """
    cid = (course_id or "").strip() or None
    return retrieve(query, top_k=top_k, course_id=cid)


# ── 课程原文加载 ──────────────────────────────────

@tool
def get_lesson_content(module_id: str, lesson_id: str) -> str:
    """
    获取指定课程的完整讲义内容。

    参数：
        module_id: 课程ID（如 "RAG101"）
        lesson_id: 课时ID（如 "2-3"）

    返回：
        课程全文，未找到返回空字符串
    """
    client = get_client()
    ensure_collection()

    # 用 (module_id, lesson_id) 拼接父文档ID前缀来搜索
    # 父文档 ID 格式: {course_id}_{chapter_short}_{section}_full
    results = client.query(
        collection_name=COLLECTION_NAME,
        filter=f'course_id == "{module_id}" and section == "{lesson_id}" and chunk_index == -1',
        output_fields=["content", "title", "chapter"],
        limit=1,
    )
    if results:
        return results[0].get("content", "")
    return ""


# ── 问答历史 ──────────────────────────────────────

@tool
def get_qa_history(student_id: int, limit: int = 10) -> list[dict]:
    """
    查询学员最近 N 条问答记录，用于追问理解和避免重复回答。

    参数：
        student_id: 学员ID
        limit: 返回条数，默认 10

    返回：
        [{question, answer, created_at}, ...]
    """
    with get_session() as session:
        records = (
            session.query(QAHistory)
            .filter(QAHistory.student_id == student_id)
            .order_by(QAHistory.created_at.desc())
            .limit(limit)
            .all()
        )

    return [
        {
            "question": r.question,
            "answer": r.answer,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reversed(records)  # 按时间正序返回
    ]
