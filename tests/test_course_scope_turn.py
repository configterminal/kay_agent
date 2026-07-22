"""课程作用域 TurnHint / 代称近窗 — 对照 course-scope-dialogues.md。"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.course_scope import (
    detect_course_mention,
    detect_content_clue,
    is_followup_utterance,
    resolve_turn_course,
    resolve_course_scope,
    infer_activated_topic,
)


def _state(*pairs: tuple[str, str]) -> dict:
    """pairs: ('h'|'a', text)"""
    messages = []
    for role, text in pairs:
        messages.append(HumanMessage(content=text) if role == "h" else AIMessage(content=text))
    return {"messages": messages, "focus_course_id": "", "active_course_id": "", "citations": []}


def test_explicit_rag_mention():
    assert detect_course_mention("rag和 graph rag 区别是什么？") == "RAG101"
    assert not is_followup_utterance("rag和 graph rag 区别是什么？")
    t = resolve_turn_course({}, "rag和 graph rag 区别是什么？")
    assert t["course_id"] == "RAG101" and t["mode"] == "turn_hint"


def test_sample1_anaphora_stays_rag():
    st = _state(
        ("h", "rag和 graph rag 区别是什么？"),
        ("a", "普通 RAG 用向量检索，Graph RAG 用图遍历……"),
    )
    t = resolve_turn_course(st, "详细点都讲解一下")
    assert t["course_id"] == "RAG101"
    assert t["reason"] == "anaphora"


def test_sample2_switch_career_to_rag():
    st = _state(
        ("h", "程序员第几年跳槽比较合适？"),
        ("a", "常见窗口是第三年、第五年……"),
    )
    # 新主题必须离开 CAREER
    t = resolve_turn_course(st, "rag 和 graph rag 有什么区别？")
    assert t["course_id"] == "RAG101"
    st2 = {
        **st,
        "messages": st["messages"]
        + [
            HumanMessage(content="rag 和 graph rag 有什么区别？"),
            AIMessage(content="RAG 是检索增强……"),
        ],
    }
    t2 = resolve_turn_course(st2, "详细点")
    assert t2["course_id"] == "RAG101"


def test_sample9_same_anaphora_different_courses():
    """同一句「详细点」先后落 CAREER 与 RAG。"""
    st = _state(
        ("h", "三年程序员，什么时候跳比较合适？"),
        ("a", "跳槽时机……第三年窗口……"),
    )
    assert resolve_turn_course(st, "详细点")["course_id"] == "CAREER201"

    st2 = {
        **st,
        "messages": st["messages"]
        + [
            HumanMessage(content="详细点"),
            AIMessage(content="再展开跳槽……"),
            HumanMessage(content="对了我想问检索增强生成是啥"),
            AIMessage(content="RAG 就是先查资料再生成……"),
        ],
    }
    assert resolve_turn_course(st2, "那个再展开说说")["course_id"] == "RAG101"
    assert resolve_turn_course(st2, "继续")["course_id"] == "RAG101"


def test_sample10_anaphora_follows_activation():
    st_rag = _state(
        ("h", "跳槽节奏怎么规划？"),
        ("a", "跳槽规划……"),
        ("h", "RAG 三大核心是什么？"),
        ("a", "知识库、检索、大模型……"),
    )
    assert resolve_turn_course(st_rag, "那个呢？再讲细点")["course_id"] == "RAG101"

    st_career = _state(
        ("h", "Graph RAG 和普通 RAG 差别？"),
        ("a", "图遍历……"),
        ("h", "谈薪一般怎么开场？"),
        ("a", "谈薪开场……"),
    )
    assert resolve_turn_course(st_career, "那个呢？再讲细点")["course_id"] == "CAREER201"


def test_sample10c_content_clue_disambiguates():
    st = _state(
        ("h", "什么是 RAG？"),
        ("a", "先查资料再生成……图遍历……"),
        ("h", "跳槽的最佳时机是什么？"),
        ("a", "第三年窗口……"),
    )
    assert detect_content_clue("那个「图遍历」再来一句") == "RAG101"
    assert resolve_turn_course(st, "那个「图遍历」再来一句")["course_id"] == "RAG101"
    assert resolve_turn_course(st, "那个「第三年窗口」再展开")["course_id"] == "CAREER201"


def test_sample3_clue_back_to_rag():
    st = _state(
        ("h", "什么是 RAG？"),
        ("a", "RAG 让模型先查资料再生成……"),
        ("h", "跳槽的最佳时机是什么？"),
        ("a", "第三年……"),
    )
    t = resolve_turn_course(st, "刚才那个「先查资料再生成」能再展开吗？")
    assert t["course_id"] == "RAG101"


def test_open_without_lock():
    t = resolve_turn_course({}, "今天天气怎么样")
    assert t["mode"] == "open" and t["course_id"] is None


def test_hard_overrides_in_resolve_scope():
    st = {
        "active_course_id": "RAG101",
        "focus_course_id": "CAREER201",
        "messages": [HumanMessage(content="跳槽时机？")],
    }
    scope = resolve_course_scope(st, student_id=1, message="跳槽时机？")
    assert scope["mode"] == "hard" and scope["course_id"] == "RAG101"


def test_clear_focus():
    t = resolve_turn_course({"focus_course_id": "RAG101"}, "先不限定课程，随便看看")
    assert t["mode"] == "open"


def test_infer_skips_pure_anaphora():
    st = _state(
        ("h", "什么是 embedding？"),
        ("a", "向量表示……"),
        ("h", "详细点"),
        ("a", "再展开 embedding……"),
        ("h", "群面一般注意什么？"),
        ("a", "群面技巧……"),
    )
    assert infer_activated_topic(st) == "CAREER201"
    assert resolve_turn_course(st, "详细点")["course_id"] == "CAREER201"
