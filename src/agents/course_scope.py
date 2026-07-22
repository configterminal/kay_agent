"""
课程作用域 — Hard / 本轮 TurnHint / Open。

临时聊不锁课：每轮按「本轮话 + 近窗」解析 turn_course。
代称（那个/详细点/继续）跟当前激活主题或内容线索，可跨课；禁止探路写死 Soft。
正式选课 Hard 仍严格单课。
见 docs/architecture/rag/course-scope.md 与 course-scope-dialogues.md。
"""

from __future__ import annotations

import re
from typing import Any

from src.db.init_db import get_session
from src.db.schema import CourseModule, Student

# 对比 / 清焦点话术
_CLEAR_FOCUS_RE = re.compile(
    r"(两门课|对比|比较一下|怎么选|先不选|不限定|随便看看|换一门|另一门课)",
)
# 确认选课 → Hard
_HARD_COMMIT_RE = re.compile(
    r"(就学这|就选这|报名|我要学这|开始学这|确定选|就它了|正式学)",
)
_COURSE_ID_RE = re.compile(r"\b([A-Z]{2,}[0-9]{3,})\b", re.I)
# 代称 / 追问（字面可无课名）
_FOLLOWUP_RE = re.compile(
    r"(详细|展开|继续|再说说|再说一下|更清楚|为什么|怎么理解|举例|"
    r"那个|上面|刚才|前面|之前|这个|这些|深入|补充|讲讲|"
    r"还有呢|然后呢|接着|具体点|都讲解|再讲|再来|补两句|一口)",
)
# 内容线索 → 课（代称消歧）
_CLUE_RAG_RE = re.compile(
    r"(图遍历|先查资料|检索增强|embedding|向量|rerank|精排|切块|"
    r"知识库|graph\s*rag|hybrid|混合检索|召回)",
    re.I,
)
_CLUE_CAREER_RE = re.compile(
    r"(跳槽|谈薪|群面|第三年|第\s*3\s*年|职业窗口|面试开场|"
    r"简历项目|怎么吹|求职|职场故事)",
)


def list_catalog_courses() -> list[dict[str, str]]:
    """目录中的 course 级模块：[{course_id, title}, ...]。"""
    with get_session() as session:
        rows = (
            session.query(CourseModule)
            .filter(CourseModule.level == "course")
            .all()
        )
        out: list[dict[str, str]] = []
        for m in rows:
            cid = (m.course_id or m.module_id or "").strip()
            if not cid:
                continue
            out.append({
                "course_id": cid,
                "title": str(m.title or ""),
            })
        return out


def get_enrolled_course_ids(student_id: int) -> list[str]:
    """学员 enrolled_modules 中解析出的 course 级 id（保序去重）。"""
    with get_session() as session:
        student = session.query(Student).filter_by(id=student_id).first()
        if student is None:
            return []
        enrolled = list(student.enrolled_modules or [])
    catalog = {c["course_id"] for c in list_catalog_courses()}
    result: list[str] = []
    seen: set[str] = set()
    for raw in enrolled:
        mid = str(raw or "").strip()
        if not mid:
            continue
        cid = mid if mid in catalog else mid.split("-")[0]
        if cid in catalog and cid not in seen:
            result.append(cid)
            seen.add(cid)
        elif mid.startswith(("mksz", "RAG", "CAREER")) and mid not in seen:
            result.append(mid if "-" not in mid else mid.split("-")[0])
            seen.add(result[-1])
    return result


def get_profile_primary_course(student_id: int) -> str | None:
    """画像主课 = enrolled 中第一个 course 级 id（正式学/推荐用；临时答疑不锁课）。"""
    ids = get_enrolled_course_ids(student_id)
    return ids[0] if ids else None


def detect_course_mention(text: str) -> str | None:
    """从用户话术检测课程 id（显式 id、标题、或技术/职业主题词）。"""
    raw = (text or "").strip()
    if not raw:
        return None
    m = _COURSE_ID_RE.search(raw)
    if m:
        cid = m.group(1)
        up = cid.upper()
        if up.startswith(("RAG", "CAREER")):
            return up
        return cid

    upper = raw.upper()
    compact = upper.replace(" ", "").replace("-", "")
    if "GRAPHRAG" in compact or "GRAPH RAG" in upper:
        return "RAG101"
    if re.search(r"(?<![A-Z])RAG(?![A-Z])", upper) or "检索增强" in raw or "向量库" in raw:
        return "RAG101"
    if "职业跃迁" in raw or "程序员职业" in raw:
        return "CAREER201"
    # 职业主题（临时聊可点名，不要求带「课」）
    if any(k in raw for k in ("跳槽", "谈薪", "群面", "求职面试", "职业规划")):
        return "CAREER201"
    if ("面试技巧" in raw and "课" in raw) or ("面试" in raw and "准备" in raw and "RAG" not in upper):
        # 「面试怎么准备」偏 CAREER；含 RAG 时已在上面命中
        if "检索" not in raw and "向量" not in raw:
            return "CAREER201"

    try:
        catalog = list_catalog_courses()
    except Exception:
        catalog = []
    for c in catalog:
        title = (c.get("title") or "").strip()
        cid = c["course_id"]
        if title and title in raw:
            return cid
        if title and len(title) >= 4 and title[:6] in raw:
            return cid
    return None


def detect_content_clue(text: str) -> str | None:
    """代称句里的内容线索 → 课（可跳过中间轮回指）。"""
    raw = text or ""
    # 两边都有时：更具体的线索优先（图遍历/切块 > 泛「面试」）
    if _CLUE_RAG_RE.search(raw):
        return "RAG101"
    if _CLUE_CAREER_RE.search(raw):
        return "CAREER201"
    return None


def is_followup_utterance(text: str) -> bool:
    """是否像代称/追问（未显式点名新课）。"""
    t = (text or "").strip()
    if not t:
        return False
    if detect_course_mention(t) and not _FOLLOWUP_RE.search(t):
        # 纯新问题点名课
        return False
    # 「那回到跳槽…」含主题词 → 当显式换题，不是纯代称
    if detect_course_mention(t) and not _is_mostly_anaphora(t):
        return False
    if len(t) <= 24:
        return True
    return bool(_FOLLOWUP_RE.search(t))


def _is_mostly_anaphora(text: str) -> bool:
    """短句且以代称为主（可附带内容线索）。"""
    t = (text or "").strip()
    if len(t) <= 40 and _FOLLOWUP_RE.search(t):
        return True
    return False


def _msg_text(msg: Any) -> str:
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content")
    return str(content or "")


def _course_id_from_path(text: str) -> str | None:
    m = re.search(r"\b(RAG\d+|CAREER\d+|mksz\d+)\b", text or "", re.I)
    if not m:
        return None
    raw = m.group(1)
    if raw.lower().startswith("mksz"):
        return "RAG101"
    return raw.upper() if raw.upper().startswith(("RAG", "CAREER")) else raw


def infer_activated_topic(state: dict[str, Any] | None) -> str | None:
    """
    当前激活主题 = 近窗中最近一次「非纯代称」发言所涉课程。

    倒序扫 Human / AI；纯代称短句跳过，避免把「详细点」当成主题源。
    """
    st = state or {}
    messages = list(st.get("messages") or [])
    for msg in reversed(messages[-16:]):
        text = _msg_text(msg)
        if not text.strip():
            continue
        # 跳过几乎只有代称、无线索的短句
        if is_followup_utterance(text) and not detect_content_clue(text) and not detect_course_mention(text):
            continue
        hit = (
            detect_content_clue(text)
            or detect_course_mention(text)
            or _course_id_from_path(text)
        )
        if hit:
            return hit
    # citations 兜底
    for c in st.get("citations") or []:
        if not isinstance(c, dict):
            continue
        blob = " ".join(str(c.get(k) or "") for k in ("media_path", "source", "title"))
        hit = detect_course_mention(blob) or _course_id_from_path(blob)
        if hit:
            return hit
    cache = str(st.get("focus_course_id") or "").strip()
    return cache or None


def infer_course_from_history(state: dict[str, Any] | None) -> str | None:
    """兼容旧名：等同激活主题推断。"""
    return infer_activated_topic(state)


def should_clear_focus(text: str) -> bool:
    """用户是否要求对比 / 取消限定。"""
    return bool(_CLEAR_FOCUS_RE.search(text or ""))


def should_hard_commit(text: str) -> bool:
    """用户是否确认选课。"""
    return bool(_HARD_COMMIT_RE.search(text or ""))


def resolve_turn_course(
    state: dict[str, Any] | None,
    message: str,
) -> dict[str, Any]:
    """
    解析本轮临时聊应用的课（不含 Hard；Hard 由 resolve_course_scope 先判）。

    返回：
        {course_id: str|None, mode: turn_hint|open, reason: str}
    """
    text = (message or "").strip()
    st = state or {}

    if should_clear_focus(text):
        return {"course_id": None, "mode": "open", "reason": "clear"}

    # 显式点名 / 主题词（非「代称+线索」优先已含在 mention）
    mentioned = detect_course_mention(text)
    clue = detect_content_clue(text)

    # 代称 + 内容线索 → 线索课（可跨轮回指）
    if clue and (is_followup_utterance(text) or _FOLLOWUP_RE.search(text)):
        return {"course_id": clue, "mode": "turn_hint", "reason": "clue"}

    # 明确新主题（含跳槽/RAG 等）且不是纯代称粘连
    if mentioned and not (is_followup_utterance(text) and _is_mostly_anaphora(text) and not clue):
        # 「详细点讲 RAG」→ mention+followup → mention
        return {"course_id": mentioned, "mode": "turn_hint", "reason": "explicit"}

    if mentioned:
        return {"course_id": mentioned, "mode": "turn_hint", "reason": "explicit"}

    if clue:
        return {"course_id": clue, "mode": "turn_hint", "reason": "clue"}

    # 纯代称 → 当前激活主题
    if is_followup_utterance(text):
        activated = infer_activated_topic(st)
        if activated:
            return {"course_id": activated, "mode": "turn_hint", "reason": "anaphora"}
        return {"course_id": None, "mode": "open", "reason": "anaphora_miss"}

    # 独立新问题、无点名 → Open（不锁 Profile）
    return {"course_id": None, "mode": "open", "reason": "open"}


def resolve_course_scope(
    state: dict[str, Any] | None,
    student_id: int,
    message: str | None = None,
) -> dict[str, Any]:
    """
    解析本轮检索作用域。

    返回：
        {course_id: str|None, mode: hard|turn_hint|open,
         active_course_id, focus_course_id}
    """
    st = state or {}
    active = str(st.get("active_course_id") or "").strip()
    if active:
        return {
            "course_id": active,
            "mode": "hard",
            "active_course_id": active,
            "focus_course_id": str(st.get("focus_course_id") or "").strip(),
        }

    text = (message or "").strip()
    if not text:
        text = _last_user_text(st)

    turn = resolve_turn_course(st, text)
    return {
        "course_id": turn.get("course_id"),
        "mode": turn.get("mode") or "open",
        "active_course_id": "",
        "focus_course_id": str(st.get("focus_course_id") or "").strip(),
        "reason": turn.get("reason") or "",
    }


def _last_user_text(state: dict[str, Any]) -> str:
    from langchain_core.messages import HumanMessage

    for msg in reversed(list(state.get("messages") or [])):
        if isinstance(msg, HumanMessage) or (
            isinstance(msg, dict) and msg.get("role") == "user"
        ):
            return _msg_text(msg)
        if getattr(msg, "type", None) == "human":
            return _msg_text(msg)
    return ""


def update_focus_from_message(
    state: dict[str, Any] | None,
    student_id: int,
    message: str,
) -> dict[str, str]:
    """
    根据本轮解析更新话题缓存（focus=最近激活主题，非永久锁课）。

    Hard 确认时写 active；清焦点话术清空 focus。
    """
    st = state or {}
    active = str(st.get("active_course_id") or "").strip()
    text = message or ""

    if should_clear_focus(text):
        return {"focus_course_id": ""}

    mentioned = detect_course_mention(text)
    if mentioned and should_hard_commit(text):
        return {"active_course_id": mentioned, "focus_course_id": mentioned}

    turn = resolve_turn_course(st, text)
    cid = turn.get("course_id")
    if cid:
        # 本轮解析到课 → 更新激活缓存，供下轮纯代称参考
        upd: dict[str, str] = {"focus_course_id": str(cid)}
        # 临时聊换题不改 Hard
        if active and cid != active and not should_hard_commit(text):
            pass
        return upd

    # Open 新问题：不强制清缓存（近窗仍可用于代称）；也不再写 Soft 锁
    return {}


def analogy_course_ids(student_id: int, focus_course_id: str | None) -> list[str]:
    """类比候选：enrolled 中排除焦点课。"""
    focus = (focus_course_id or "").strip()
    return [c for c in get_enrolled_course_ids(student_id) if c != focus]
