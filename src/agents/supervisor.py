"""
Supervisor Agent — LangGraph 层级调度主控。

接收学员消息，经过 Probe → Decide → Dispatch → Aggregate → Recovery 五节点流水线，
将任务路由到 6 个下游子 Agent 或自行回复。

使用方式：
    from src.agents.supervisor import build_supervisor_graph, run_supervisor
    result = run_supervisor(graph, student_id=1, message="我最近学得怎么样？")
    # result == {"content": "...", "emotion": "neutral", "emotion_confidence": 0.9}
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Annotated

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from src.config import config
from src.llm.base import LLMProvider, CoachStyle, get_coach_prompt
from src.emotion.detector import EmotionDetector
from src.memory.store import get_store
from src.vectordb.hybrid_search import quick_vector_search
from src.perf import log_timing
from src.agents.stream_events import (
    emit_status,
    emit_token,
    chunk_text,
    chunk_has_tool_calls,
    has_stream_callback,
    set_stream_callback,
    reset_stream_callback,
)

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────

# Agent 路由名称
QA_AGENT = "qa_agent"
PROGRESS_AGENT = "progress_agent"
RECOMMEND_AGENT = "recommend_agent"
JOBMATCH_AGENT = "jobmatch_agent"
RESUME_AGENT = "resume_agent"
INTERVIEW_AGENT = "interview_agent"
SHARED_TOOLS = "shared_tools"
SUPERVISOR_SELF = "supervisor"  # Supervisor 自行回复

ALL_AGENTS = [
    QA_AGENT, PROGRESS_AGENT, RECOMMEND_AGENT,
    JOBMATCH_AGENT, RESUME_AGENT, INTERVIEW_AGENT,
]

# 尚未实现 dispatch 的 Agent；探路命中课程时应改派 QA
# Interview 已接通文字主链路；语音多模态见 src/speech + interview-multimodal.md
UNIMPLEMENTED_AGENTS = frozenset()

# 向量探路 top_score 超过此阈值且有条目 → 视为课程知识可答疑
PROBE_COURSE_OVERRIDE_MIN_SCORE = 0.35

# 同一 Agent 最大连续调用次数（防循环）
MAX_CALLS_PER_AGENT = 2

# LLM 路由分类置信度阈值
HIGH_CONFIDENCE_THRESHOLD = 0.85
LOW_CONFIDENCE_THRESHOLD = 0.5

# ── Pydantic 路由输出模型 ─────────────────────────────────

class AgentRoute(BaseModel):
    """单条路由决策"""
    agent: str = Field(description="目标 Agent 名称: qa_agent/progress_agent/recommend_agent/jobmatch_agent/resume_agent/interview_agent/shared_tools/supervisor")
    confidence: float = Field(description="置信度 0.0-1.0", ge=0.0, le=1.0)
    reason: str = Field(description="路由原因，简要说明为什么选择这个 Agent")


class RoutingDecision(BaseModel):
    """LLM 结构化路由输出 — 支持多意图"""
    primary: AgentRoute = Field(description="主路由（最匹配的 Agent）")
    secondary: list[AgentRoute] = Field(default_factory=list, description="次路由（多意图时列出，按优先级排序）")
    is_parallel: bool = Field(default=False, description="多个意图是否可以并行执行")
    is_chitchat: bool = Field(default=False, description="是否为闲聊/寒暄，需要 Supervisor 自行处理")
    summary: str = Field(default="", description="一句话概括学员意图")


# ── Supervisor State ─────────────────────────────────────

class SupervisorState(TypedDict):
    """Supervisor 状态 — 在 StateGraph 各节点间流转（按 thread_id 隔离）"""
    messages: Annotated[list, add_messages]      # 完整对话历史
    student_id: int                               # 学员 ID
    coach_style: str                              # 从 Store 读取的导师人格
    emotion: str                                  # 当前消息的情绪标签
    emotion_confidence: float                     # 情绪置信度
    next_agent: str                               # 当前路由目标
    called: list[str]                             # 已调用的 Agent 名称列表
    call_count: dict[str, int]                    # 每个 Agent 调用次数
    task_queue: list[dict]                        # 多意图任务队列 [{"agent":..., "input":..., "depends_on":...}]
    task_results: list[dict]                      # 已完成任务的结果 [{"agent":..., "output":...}]
    final_response: str                           # 最终输出给学员的文本
    citations: list[dict]                         # 本轮 QA 检索来源（跳转视频用）
    needs_reroute: bool                           # 子 Agent 是否请求重路由
    reroute_reason: str                           # 重路由原因
    probe_evidence: dict                          # Probe 节点提取的路由证据
    is_chitchat: bool                             # 是否闲聊
    routing_confidence: float                     # 路由置信度
    # 会话级对话状态（随 Checkpointer 按 thread_id 持久化，会话间互不干扰）
    pending_options: list[dict]                   # [{"id": 1, "text": "..."}]
    pending_agent: str                            # 选号后粘性路由的 Agent
    selected_option_id: int | None                # 本轮前端点击传入的选项 id
    thread_id: str                                # 与 Checkpointer / Store.summaries 共用
    conversation_summary: str                     # 本轮从 Store 读取的会话摘要（进模型用）
    # 课程作用域：Hard 正式选课 / Soft 临时聊课（见 docs/architecture/rag/course-scope.md）
    active_course_id: str                         # Hard：已确认报名的课
    focus_course_id: str                          # 最近激活话题缓存（非永久锁课）
    analogy_citations: list[dict]                 # 类比课来源（与 citations 分区）
    resume_artifact_id: str                       # 本轮 Resume 终稿 artifact
    resume_mode: str                              # fact | target
    resume_title: str                             # Dock 标题


# ── Python 确定性路由 ─────────────────────────────────────
#
# 高置信度关键词匹配，不调 LLM，直接决定目标 Agent。
# 关键词提取自各 Agent 的核心职责描述。

DETERMINISTIC_RULES: list[tuple[list[str], str, str]] = [
    # 顺序很重要：更具体的模式放前面，避免被通用关键词误匹配。
    # 匹配到第一个规则即停止。

    # ── 导师人格切换（最具体，放最前） ──
    (["切换人格", "换风格", "换个导师", "换语气", "改风格", "温柔一点",
      "严厉一点", "幽默一点", "专业一点"],
     SHARED_TOOLS, "关键词命中: 切换人格/换风格"),

    # ── 简历课知识（优先于 Resume，避免「简历怎么写」进优化）──
    (["简历怎么写", "简历要注意", "简历技巧", "简历模板怎么", "写简历注意"],
     QA_AGENT, "关键词命中: 简历课程答疑"),

    # ── 简历优化（已接通；强信号，去掉单字「简历」宽松命中）──
    (["修改简历", "优化简历", "我的简历", "帮我改简历", "改简历", "润色简历",
      "简历优化", "简历反馈", "简历建议", "做简历", "写简历",
      "目标简历", "蓝图简历", "编一版简历", "理想简历", "定向简历"],
     RESUME_AGENT, "关键词命中: 简历优化/蓝图"),

    # ── 职业跃迁 / 求职课程知识（CAREER201 等）──
    (["职业跃迁", "程序员职业", "怎么跳槽", "跳槽方法", "跳槽时机", "晋升方法",
      "晋升技巧", "谈薪技巧", "面试技巧", "面试方法", "面试要注意",
      "职业发展路径", "技术线", "资源线", "骑驴找马", "个人利益"],
     QA_AGENT, "关键词命中: 职业跃迁课程答疑"),

    # ── 模拟面试（仅「发起练习」类强信号）──
    (["模拟面试", "面试题", "面试评估", "面试报告",
      "开始面试", "面试练习", "来场面试", "来一场面试"],
     INTERVIEW_AGENT, "关键词命中: 模拟面试"),

    # ── 岗位/课程覆盖匹配（已接通；勿再被探路改派 QA）──
    (["技能差距", "还差什么", "差什么技能", "对照课程", "课程覆盖",
      "岗位匹配", "职位要求", "找工作", "求职方向", "目标岗位",
      "目标是做", "转行建议", "技术栈要求", "RAG工程师", "RAG 工程师",
      "AI应用工程师", "就业前景", "职业发展"],
     JOBMATCH_AGENT, "关键词命中: 岗位/匹配/技能差距"),

    # ── 进度相关 ──
    (["学习进度", "查看进度", "我的成绩", "学习报告", "学了多久",
      "学习时间", "完成率", "薄弱点", "我擅长", "学了什么",
      "学到哪了", "掌握情况", "知识点掌握", "测验成绩", "做题记录",
      "正确率", "错误率", "错题", "学习记录", "我的排名", "达标了吗",
      "进度报告", "成绩报告"],
     PROGRESS_AGENT, "关键词命中: 进度/成绩/报告"),

    # ── 推荐相关 ──
    (["推荐课程", "下一节课", "该学什么", "下一步学", "课程推荐",
      "有什么课", "选什么课", "学习路径", "进阶路线", "前置课程", "先修课程",
      "接着学", "继续学", "接下来学", "之后学什么"],
     RECOMMEND_AGENT, "关键词命中: 推荐/课程选择"),

    # ── 岗位宽松匹配 ──
    (["岗位", "招聘", "职位", "前端", "后端", "全栈", "数据分析", "测试", "运维"],
     JOBMATCH_AGENT, "关键词命中: 岗位/职位"),

    # ── 进度宽松匹配 ──
    (["进度", "成绩", "报告", "学了多久", "学习时间", "分数"],
     PROGRESS_AGENT, "关键词命中: 进度/成绩"),

    # ── 推荐宽松匹配 ──
    (["推荐", "下一课", "该学什么", "学什么", "下一步"],
     RECOMMEND_AGENT, "关键词命中: 推荐"),
]

# 疑问词模式 — 匹配课程知识问答
QA_PATTERNS = [
    "什么是", "怎么用", "为什么", "如何理解", "解释一下",
    "区别", "对比", "原理", "概念", "定义", "含义",
    "怎么实现", "怎么做", "怎么写", "怎么配置", "怎么部署",
]

# 纯闲聊整句匹配（禁止用松散子串，避免误伤「你好，什么是X」）
CHITCHAT_EXACT = frozenset({
    "你好", "您好", "嗨", "哈喽", "hello", "hi",
    "谢谢", "谢谢你", "谢谢啦", "感谢",
    "再见", "拜拜", "晚安", "早安", "早上好",
    "哈哈", "嗯嗯", "嗯", "好的", "知道了", "明白了",
    "ok", "okay", "不错", "厉害",
})

# 可剥离的问候前缀（按长度降序匹配；不含单字「早」，避免误伤「早上学的…」）
GREETING_PREFIXES = (
    "你好呀", "你好啊", "您好", "你好", "嗨", "哈喽",
    "hello", "hi", "好的", "嗯嗯",
)


def _normalize_utterance(text: str) -> str:
    """归一化学员话术：小写、去首尾空白与常见标点。"""
    t = text.lower().strip()
    return t.strip("，,。.!！？?~～、 \t\n\r")


def _strip_greeting_shell(text: str) -> str:
    """剥离开头问候壳，返回剩余实质内容（可能为空）。"""
    t = _normalize_utterance(text)
    for prefix in sorted(GREETING_PREFIXES, key=len, reverse=True):
        p = prefix.lower()
        if t.startswith(p):
            return t[len(p):].lstrip("，,。.!！？?~～、 \t")
    return t


def _classify_chitchat(text: str, has_history: bool = False) -> bool:
    """
    判定是否为纯闲聊（不调 LLM）。

    仅当整句寒暄，或去掉问候壳后无实质内容时返回 True。
    有对话历史时，不对 ≤3 字超短消息做闲聊拦截——可能是追问。
    调用方须保证：业务确定性规则 / QA 已先跑过（业务优先）。
    注意：pending_options 选号须在调用本函数之前处理，不得进入闲聊。
    """
    normalized = _normalize_utterance(text)
    if not normalized:
        return True
    if normalized in CHITCHAT_EXACT:
        return True

    rest = _strip_greeting_shell(text)
    if not rest:
        return True
    if _normalize_utterance(rest) in CHITCHAT_EXACT:
        return True

    # 超短消息：有历史时不拦截（可能是追问"是什么""怎么用"）
    if len(normalized) <= 3:
        return not has_history
    return False


# ── 结构化选项（会话级 pending_options）──────────────────

# 助教回复中的编号列表行：1. / 1、 / 1) / **1.**
_OPTION_LINE_RE = re.compile(
    r"^\s*(?:\*\*)?(\d{1,2})(?:\*\*)?\s*[.、)\]]\s+(.+?)\s*$",
    re.MULTILINE,
)

# 仅当列表前有「请学员拍板」类话术时，才提取为可点选项
_CHOICE_CUE_RE = re.compile(
    r"(请选择|请选|选一[个下]|二选一|多选一|更偏向|以下哪[种个]|你希望|你想|"
    r"需要你确认|回复编号|点选|拍板|选哪个|选哪条|先走哪|从下面选)",
)

# 诊断/建议编号列表：不当作选项（简历「问题 1.2.3」误触发）
_NON_CHOICE_CUE_RE = re.compile(
    r"(问题|需要优化|待优化|不足之处|致命|建议训练|训练题|面试深挖|"
    r"学习闭环|改前|改后|覆盖与|还有几点|以下几个问题|重点改写|"
    r"结构建议|内容建议|红旗)",
)

# 学员手输选号：1 / 选项2 / 第3个 / 二
_CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_SELECTION_RE = re.compile(
    r"^(?:选项\s*|第\s*)?"
    r"([1-9]|10|[一二三四五六七八九十])"
    r"(?:\s*[.、)]|\s*个|\s*项)?$"
)


def _parse_option_id_from_text(text: str) -> int | None:
    """从学员短回复解析选项 id；无法解析则返回 None。"""
    normalized = _normalize_utterance(text)
    if not normalized:
        return None
    m = _SELECTION_RE.match(normalized)
    if not m:
        return None
    token = m.group(1)
    if token.isdigit():
        return int(token)
    return _CN_NUM.get(token)


def _group_option_blocks(matches: list[re.Match]) -> list[list[re.Match]]:
    """将编号行按「连续列表」分块（新列表常从 1. 重新开始）。"""
    blocks: list[list[re.Match]] = []
    current: list[re.Match] = []
    for m in matches:
        if not current:
            current = [m]
            continue
        prev = current[-1]
        gap = m.start() - prev.end()
        prev_id = int(prev.group(1))
        cur_id = int(m.group(1))
        # 新列表：间隔过大，或重新从 1 起且上一项已 ≥2
        if gap > 120 or (cur_id == 1 and prev_id >= 2) or cur_id < prev_id:
            blocks.append(current)
            current = [m]
        elif cur_id == prev_id + 1 or gap <= 120:
            current.append(m)
        else:
            blocks.append(current)
            current = [m]
    if current:
        blocks.append(current)
    return blocks


def _score_option_block(text: str, block: list[re.Match]) -> int:
    """选择意向越高分；诊断/问题列表为负分。"""
    if len(block) < 2:
        return -100
    start = block[0].start()
    prefix = text[max(0, start - 220):start]
    score = 0
    if _CHOICE_CUE_RE.search(prefix):
        score += 12
    if _NON_CHOICE_CUE_RE.search(prefix):
        score -= 12
    first = block[0].group(2)
    # 诊断口吻的条目
    if re.search(r"(太长|太短|太啰|太单|缺少|不足|需要精|需要补|需要展|有问题)", first):
        score -= 6
    # 选项口吻：方向/模块/路径
    if re.search(r"(方向|路径|模块|课程|先学|投递|岗位)", first):
        score += 2
    return score


def extract_options_from_text(text: str) -> list[dict]:
    """
    从助教回复中提取「需要学员拍板」的编号选项。

    规则：
    - 只提取带选择话术（请选择/更偏向/以下哪种…）的列表
    - 诊断类编号（简历问题 1.2.3、训练题清单等）不进入可点选项
    - 多段列表时取得分最高且靠后的选择块
    """
    if not text:
        return []
    matches = list(_OPTION_LINE_RE.finditer(text))
    if len(matches) < 2:
        return []

    blocks = _group_option_blocks(matches)
    scored: list[tuple[int, int, list[re.Match]]] = []
    for idx, block in enumerate(blocks):
        scored.append((_score_option_block(text, block), idx, block))

    # 仅保留「像选择」的块
    candidates = [x for x in scored if x[0] > 0]
    if not candidates:
        return []

    # 同分取更靠后的块（通常真正决策在文末）
    candidates.sort(key=lambda x: (x[0], x[1]))
    _, _, best = candidates[-1]

    found: dict[int, str] = {}
    for m in best:
        opt_id = int(m.group(1))
        opt_text = m.group(2).strip()
        # 去掉 markdown 加粗，按钮文案更干净
        opt_text = opt_text.replace("**", "").strip()
        if opt_id < 1 or opt_id > 20 or not opt_text:
            continue
        if opt_id not in found:
            found[opt_id] = opt_text
    if len(found) < 2:
        return []
    return [{"id": i, "text": found[i]} for i in sorted(found)]


def _resolve_option_selection(
    text: str,
    selected_option_id: int | None,
    pending_options: list[dict],
) -> tuple[str, int, str] | None:
    """
    解析本轮是否选中了 pending 中的选项。

    返回 (改写后的 input, option_id, option_text)；未命中返回 None。
    """
    if not pending_options:
        return None

    by_id = {int(o["id"]): str(o.get("text", "")).strip() for o in pending_options if "id" in o}
    if not by_id:
        return None

    opt_id: int | None = None
    if selected_option_id is not None:
        try:
            opt_id = int(selected_option_id)
        except (TypeError, ValueError):
            opt_id = None
    if opt_id is None:
        opt_id = _parse_option_id_from_text(text)

    if opt_id is None or opt_id not in by_id:
        return None

    opt_text = by_id[opt_id] or f"选项 {opt_id}"
    rewritten = (
        f"学员选择了选项 {opt_id}：{opt_text}。"
        f"请基于该选项继续讲解或执行对应任务，不要再把整句当成新话题重新分类。"
    )
    return rewritten, opt_id, opt_text


def _pending_updates_from_reply(reply: str, fallback_agent: str) -> dict:
    """根据助教回复是否含列表，生成 pending_options / pending_agent 更新。"""
    options = extract_options_from_text(reply)
    if options:
        agent = fallback_agent if fallback_agent and fallback_agent != SUPERVISOR_SELF else QA_AGENT
        return {"pending_options": options, "pending_agent": agent}
    return {"pending_options": [], "pending_agent": ""}


# ── 确定性路由 ────────────────────────────────────────────

def _deterministic_route(text: str, has_history: bool = False) -> tuple[str | None, float, str]:
    """
    用关键词匹配做高置信度确定性路由。

    判定顺序（业务优先，对齐 supervisor.md「闲聊分流」）：
    1. DETERMINISTIC_RULES
    2. QA_PATTERNS
    3. 纯闲聊判定
    4. 无法匹配 → 交 LLM

    返回 (agent_name | None, confidence, reason)
    None 表示无确定性匹配，需要 LLM 分类。
    """
    text_stripped = text.strip()

    for keywords, agent, reason_template in DETERMINISTIC_RULES:
        matched = [k for k in keywords if k in text_stripped]
        if not matched:
            continue
        best_match = max(matched, key=len)
        confidence = min(0.8 + (len(matched) - 1) * 0.05 + (len(best_match) - 1) * 0.01, 0.99)
        return agent, confidence, f"{reason_template}: '{best_match}'"

    for pattern in QA_PATTERNS:
        if pattern in text_stripped:
            return QA_AGENT, 0.85, f"疑问模式命中: {pattern}"

    if _classify_chitchat(text_stripped, has_history=has_history):
        return SUPERVISOR_SELF, 0.95, "纯闲聊/寒暄消息"

    return None, 0.0, ""


def _override_unimplemented_with_probe(
    agent: str,
    probe_evidence: dict,
    reason: str = "",
) -> tuple[str, str]:
    """
    未实现 Agent 且向量探路命中课程 → 改派 QA。

    避免「面试技巧」「职业发展」等课程关键词误进 interview/jobmatch 占位回复。
    """
    if agent not in UNIMPLEMENTED_AGENTS:
        return agent, reason
    top_score = float(probe_evidence.get("top_score") or 0)
    sections = [s for s in (probe_evidence.get("sections") or []) if s]
    if top_score >= PROBE_COURSE_OVERRIDE_MIN_SCORE and sections:
        sec_text = ", ".join(sections[:3])
        new_reason = (
            f"探路命中课程 [{sec_text}] score={top_score}，"
            f"未实现 {agent} 改派 qa_agent"
        )
        logger.info(new_reason)
        return QA_AGENT, new_reason
    return agent, reason


# ── Probe 辅助 ───────────────────────────────────────────

def _quick_vector_probe(query: str) -> dict:
    """
    快速向量探路：只取 Top 3，提取章节/标签分布作为路由证据。

    仅 embed + Milvus，不经过查询重写与重排序。
    返回 {"sections": [...], "tags": [...], "top_score": float, "score_spread": float}
    """
    try:
        results = quick_vector_search(query, top_k=3)
    except Exception as e:
        logger.warning("向量探路失败: %s", e)
        return {"sections": [], "tags": [], "top_score": 0.0, "score_spread": 0.0}

    if not results:
        return {"sections": [], "tags": [], "top_score": 0.0, "score_spread": 0.0}

    sections = [r.get("section", "") for r in results if r.get("section")]
    course_ids = [
        str(r.get("course_id") or "").strip()
        for r in results
        if str(r.get("course_id") or "").strip()
    ]
    top_score = results[0].get("score", 0.0) if results else 0.0
    scores = [r.get("score", 0.0) for r in results]
    score_spread = max(scores) - min(scores) if len(scores) >= 2 else 0.0
    # 探路 Top 命中同一门课 → 可作为 Soft 焦点候选
    dominant_course = ""
    if course_ids and len(set(course_ids)) == 1:
        dominant_course = course_ids[0]

    return {
        "sections": sections,
        "tags": sections,  # 简化：用章节分布代替标签分布
        "top_score": round(top_score, 4),
        "score_spread": round(score_spread, 4),
        "course_ids": course_ids,
        "dominant_course_id": dominant_course,
    }


def _read_student_context(student_id: int) -> dict:
    """
    从 MemoryStore 读取学员上下文：coach_style、weak_areas、preferences。
    返回默认值如果 Store 中无数据。
    """
    store = get_store()
    result = {}

    coach_data = store.get(["students", str(student_id), "coach_style"])
    result["coach_style"] = (
        coach_data.get("style", "encouraging")
        if coach_data else "encouraging"
    )

    weak_areas = store.get(["students", str(student_id), "weak_areas"])
    result["weak_areas"] = weak_areas if weak_areas else {}

    prefs = store.get(["students", str(student_id), "preferences"])
    result["preferences"] = prefs if prefs else {}

    return result


# ── LLM 路由 ──────────────────────────────────────────────

_ROUTING_SYSTEM_PROMPT = """你是 AI 助教系统的意图路由器。分析学员消息，选择最合适的 Agent 处理。

可选 Agent：
- qa_agent: 课程知识问答，概念解释，技术原理讲解，代码调试
- progress_agent: 学习进度查询，成绩报告，薄弱点/擅长点分析，学习统计
- recommend_agent: 课程推荐，学习路径规划，下一步建议，前置课程检查
- jobmatch_agent: 个人相对站内课程方向的技能差距/补课匹配（非实时招聘市场）
- resume_agent: 优化/定向呈现真实简历，或生成目标蓝图简历并给课/练/面闭环（非伪造任职）
- interview_agent: 「开始/进行模拟面试、出题练习」等实操请求（已接通）
- shared_tools: 切换导师人格风格，无需调用领域 Agent 的系统设置
- supervisor: 纯闲聊寒暄、感谢告别等不需要领域知识的消息

路由规则：
1. 如果消息包含明确的领域关键词 → 路由到对应 Agent，confidence >= 0.85
2. 询问课程里的面试/求职/职业发展/简历知识（如「面试要注意什么」「简历怎么写」「怎么跳槽」）→ qa_agent
3. 「帮我改/优化这份简历」「目标/蓝图简历」→ resume_agent，即使探路命中章节也不改派 qa
4. 「我目标是做X还差什么/技能差距/对照课程」→ jobmatch_agent，即使探路命中章节也不改派 qa
5. 向量探路已命中课程章节时，纯知识类问题优先 qa_agent
6. 如果消息可以同时由多个 Agent 处理 → 列出 primary 和 secondary，标记 is_parallel
7. 如果其中一个 Agent 的结果是另一个的前置条件 → secondary agent 的顺序排在后面，is_parallel=false
8. 仅当消息是纯粹闲聊或感谢（无业务问题）→ is_chitchat=true，agent=supervisor
9. 「你好，什么是X」「好的，我想学Y」等问候+业务 → 路由业务 Agent，is_chitchat=false
10. 如果消息含糊，选最可能的 Agent，confidence 0.5-0.7，不要硬判闲聊

重要：primary.agent 必须是上述列表中的一个，不要编造 Agent 名称。"""


def _llm_route(text: str, called: list[str], probe_evidence: dict, chat_history: list | None = None) -> RoutingDecision:
    """
    用 LLM 结构化输出做路由决策。

    called 列表用于排除已调用的 Agent，probe_evidence 作为辅助上下文。
    chat_history 传入完整对话历史，让 LLM 理解当前消息的语境（如"1"可能是选择项）。
    """
    llm_provider = LLMProvider.create()
    model = llm_provider.get_model(temperature=0)

    # 使用结构化输出
    structured_model = model.with_structured_output(RoutingDecision)

    evidence_text = ""
    if probe_evidence.get("sections"):
        sections_str = ", ".join(probe_evidence["sections"])
        top_score = probe_evidence.get("top_score", 0)
        evidence_text = f"向量探路结果：匹配章节 [{sections_str}]，最高分 {top_score}"

    called_hint = ""
    if called:
        called_hint = f"注意：以下 Agent 已被调用过，优先考虑其他 Agent：{', '.join(called)}"

    # 构建对话历史上下文
    history_text = ""
    if chat_history and len(chat_history) > 1:
        recent = chat_history[-6:]  # 最近 3 轮对话
        lines = []
        for msg in recent:
            role = "学员" if isinstance(msg, HumanMessage) else "助教"
            content = msg.content[:100] if hasattr(msg, "content") else str(msg)[:100]
            lines.append(f"{role}: {content}")
        history_text = "对话历史（供判断语境）：\n" + "\n".join(lines)

    user_message = f"""学员消息：{text}

{evidence_text}
{history_text}
{called_hint}

请分析学员意图并输出路由决策。注意：如果对话历史中助教列出了选项，学员回复"1""2"等可能是选择对应的选项——这种情况下优先考虑对话历史中正在讨论的话题，不要判为闲聊。"""

    try:
        decision: RoutingDecision = structured_model.invoke([
            ("system", _ROUTING_SYSTEM_PROMPT),
            ("user", user_message),
        ])
    except Exception as e:
        logger.warning("LLM 结构化路由失败，回退到 QA Agent: %s", e)
        return RoutingDecision(
            primary=AgentRoute(agent=QA_AGENT, confidence=0.3, reason=f"LLM 路由失败回退: {e}"),
            is_chitchat=False,
            summary="路由失败，回退到问答",
        )

    # 部分模型/解析器会返回 None 而非抛错
    if decision is None or getattr(decision, "primary", None) is None:
        logger.warning("LLM 结构化路由返回空，回退到 QA Agent")
        return RoutingDecision(
            primary=AgentRoute(agent=QA_AGENT, confidence=0.3, reason="LLM 路由空结果回退"),
            is_chitchat=False,
            summary="路由空结果，回退到问答",
        )

    # 校验 Agent 名称合法性
    valid_agents = ALL_AGENTS + [SHARED_TOOLS, SUPERVISOR_SELF]
    if decision.primary.agent not in valid_agents:
        logger.warning("LLM 返回了非法 Agent '%s'，回退到 QA Agent", decision.primary.agent)
        decision.primary.agent = QA_AGENT
        decision.primary.confidence = 0.3
        decision.primary.reason = "LLM 返回非法 Agent，回退"

    return decision


# ── 节点实现 ──────────────────────────────────────────────

def probe_node(state: SupervisorState) -> dict:
    """
    Probe 节点 — 探路 + 情绪检测 + Store 上下文读取。

    1. 向量快速检索 Top 3，提取路由证据
    2. 情绪检测（EmotionDetector）—— 全链路唯一一次，API 层不再重复检测
    3. 从 MemoryStore 读取 coach_style + weak_areas + 本 thread 会话摘要
    """
    from src.memory.context import get_thread_summary

    emit_status("probe", "正在理解问题…")

    messages = state.get("messages", [])
    student_id = state.get("student_id", 0)
    thread_id = state.get("thread_id") or ""

    # 获取最后一条用户消息
    last_user_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content
            break

    if not last_user_msg:
        return {
            "probe_evidence": {"sections": [], "tags": [], "top_score": 0.0, "score_spread": 0.0},
            "emotion": "neutral",
            "emotion_confidence": 0.0,
            "coach_style": "encouraging",
            "conversation_summary": "",
        }

    # ① 向量探路
    t = time.time()
    probe_evidence = _quick_vector_probe(last_user_msg)
    log_timing("supervisor.probe.vector", time.time() - t)

    # ② 情绪检测
    try:
        detector = EmotionDetector()
        emotion_result = detector.detect(last_user_msg)
        emotion = emotion_result.state
        emotion_confidence = emotion_result.confidence
    except Exception as e:
        logger.warning("情绪检测失败: %s", e)
        emotion = "neutral"
        emotion_confidence = 0.0

    # ③ 读取 Store 上下文（含本会话摘要）
    t = time.time()
    context = _read_student_context(student_id)
    coach_style = context.get("coach_style", "encouraging")
    summary_entry = get_thread_summary(student_id, thread_id) if thread_id else None
    conversation_summary = str((summary_entry or {}).get("text") or "")
    log_timing(
        "supervisor.probe.store",
        time.time() - t,
        summary_chars=len(conversation_summary),
    )

    logger.info(
        "Probe 完成 — 情绪=%s(%.2f) 人格=%s 探路=top_score=%.2f sections=%s",
        emotion, emotion_confidence, coach_style,
        probe_evidence.get("top_score", 0), probe_evidence.get("sections", []),
    )

    # ④ 本轮话题缓存（TurnHint）：禁止探路 dominant 写死 Soft 锁课
    from src.agents.course_scope import update_focus_from_message

    focus_upd = update_focus_from_message(state, int(student_id or 0), last_user_msg)
    if focus_upd.get("focus_course_id"):
        logger.info(
            "本轮话题缓存 focus=%s (临时聊不锁死，下轮重新解析)",
            focus_upd.get("focus_course_id"),
        )

    hard_cid = str(focus_upd.get("active_course_id") or "").strip()
    if hard_cid and student_id:
        try:
            from src.tools.shared_tools import update_student_profile
            update_student_profile.invoke({
                "student_id": int(student_id),
                "primary_course_id": hard_cid,
            })
        except Exception as e:
            logger.warning("Hard 选课写画像失败: %s", e)

    return {
        "probe_evidence": probe_evidence,
        "emotion": emotion,
        "emotion_confidence": emotion_confidence,
        "coach_style": coach_style,
        "conversation_summary": conversation_summary,
        **focus_upd,
    }


def decide_node(state: SupervisorState) -> dict:
    """
    Decide 节点 — 路由决策。

    优先级：
    0. 本线程 pending_options 选号（点击 id / 手输 id）→ 粘性路由，禁止闲聊
    1. 如果是重路由请求 → 用 reroute_reason 作为意图信号，排除已调用 Agent
    2. 确定性关键词匹配（Python 规则，高置信度）→ 直接路由
    3. 置信度不够 → LLM 结构化分类
    4. 多意图 → 填充 task_queue

    同时更新 called 和 call_count，防止循环。
    """
    emit_status("route", "正在匹配助教…")

    messages = state.get("messages", [])
    needs_reroute = state.get("needs_reroute", False)
    reroute_reason = state.get("reroute_reason", "")
    called: list[str] = state.get("called", [])
    call_count: dict[str, int] = state.get("call_count", {}).copy()
    probe_evidence = state.get("probe_evidence", {})
    pending_options: list[dict] = list(state.get("pending_options") or [])
    pending_agent = state.get("pending_agent") or ""
    selected_option_id = state.get("selected_option_id")

    # 获取需要分析的文本
    if needs_reroute and reroute_reason:
        text_to_analyze = reroute_reason
        logger.info("重路由模式，原因: %s", reroute_reason)
    else:
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                text_to_analyze = msg.content
                break
        else:
            text_to_analyze = ""

    if not text_to_analyze and selected_option_id is None:
        return {
            "next_agent": SUPERVISOR_SELF,
            "is_chitchat": True,
            "routing_confidence": 1.0,
            "task_queue": [],
            "selected_option_id": None,
        }

    # ── ⓪ 本线程结构化选项续聊（会话隔离：只看本 thread 的 pending）──
    if not needs_reroute:
        resolved = _resolve_option_selection(
            text_to_analyze or "",
            selected_option_id,
            pending_options,
        )
        if resolved is not None:
            rewritten, opt_id, opt_text = resolved
            agent = pending_agent if pending_agent in ALL_AGENTS else QA_AGENT
            if call_count.get(agent, 0) >= MAX_CALLS_PER_AGENT:
                agent = QA_AGENT
            logger.info(
                "选项续聊 → %s (id=%s text=%s)",
                agent, opt_id, opt_text[:40],
            )
            return {
                "next_agent": agent,
                "is_chitchat": False,
                "routing_confidence": 0.99,
                "task_queue": [{
                    "agent": agent,
                    "input": rewritten,
                    "depends_on": None,
                }],
                # 选号后清空，等本轮回复若再带列表则由 dispatch 重写
                "pending_options": [],
                "pending_agent": "",
                "selected_option_id": None,
            }

    # ── 确定性路由 ──
    t_det = time.time()
    has_history = any(isinstance(m, AIMessage) for m in messages)
    det_agent, det_conf, det_reason = _deterministic_route(
        text_to_analyze or "", has_history=has_history,
    )
    log_timing("supervisor.decide.deterministic", time.time() - t_det)

    # ── 排除已超调用上限的 Agent ──
    def _agent_available(agent_name: str) -> bool:
        return call_count.get(agent_name, 0) < MAX_CALLS_PER_AGENT

    if det_agent is not None and det_conf >= HIGH_CONFIDENCE_THRESHOLD:
        # 高置信度确定性路由
        if det_agent == SUPERVISOR_SELF:
            logger.info("确定性路由 → Supervisor (闲聊)")
            return {
                "next_agent": SUPERVISOR_SELF,
                "is_chitchat": True,
                "routing_confidence": det_conf,
                "task_queue": [],
                "selected_option_id": None,
            }

        if not _agent_available(det_agent):
            logger.info("确定性路由 Agent '%s' 已达调用上限，尝试回退", det_agent)
            # 回退到 Supervisor 自行处理
            return {
                "next_agent": SUPERVISOR_SELF,
                "is_chitchat": False,
                "routing_confidence": 0.3,
                "task_queue": [],
                "reroute_reason": f"{det_agent} 已达调用上限，回退到 Supervisor",
                "selected_option_id": None,
            }

        logger.info("确定性路由 → %s (置信度=%.2f): %s", det_agent, det_conf, det_reason)
        det_agent, det_reason = _override_unimplemented_with_probe(
            det_agent, probe_evidence, det_reason,
        )
        # 单意图也要写入 task_queue.input，否则 dispatch 会把空字符串传给子 Agent
        return {
            "next_agent": det_agent,
            "is_chitchat": False,
            "routing_confidence": det_conf,
            "task_queue": [{
                "agent": det_agent,
                "input": text_to_analyze,
                "depends_on": None,
            }],
            "selected_option_id": None,
        }

    # ── LLM 路由 ──
    t_llm = time.time()
    decision = _llm_route(text_to_analyze, called, probe_evidence, chat_history=messages)
    log_timing("supervisor.decide.llm", time.time() - t_llm)

    # ── 处理 LLM 路由结果 ──
    if decision.is_chitchat or decision.primary.agent == SUPERVISOR_SELF:
        logger.info("LLM 路由 → Supervisor (闲聊/寒暄)")
        return {
            "next_agent": SUPERVISOR_SELF,
            "is_chitchat": True,
            "routing_confidence": decision.primary.confidence,
            "task_queue": [],
            "selected_option_id": None,
        }

    primary_agent = decision.primary.agent
    primary_agent, _ = _override_unimplemented_with_probe(primary_agent, probe_evidence)

    # 检查调用上限
    if not _agent_available(primary_agent):
        # 尝试次选
        for secondary in decision.secondary:
            if _agent_available(secondary.agent):
                primary_agent = secondary.agent
                logger.info("主 Agent 已达上限，改用次选: %s", primary_agent)
                break
        else:
            logger.info("所有候选 Agent 均达上限，回退到 Supervisor")
            return {
                "next_agent": SUPERVISOR_SELF,
                "is_chitchat": False,
                "routing_confidence": 0.3,
                "task_queue": [],
                "selected_option_id": None,
            }

    # 构建任务队列
    task_queue: list[dict] = []

    if decision.secondary and len(decision.secondary) > 0:
        # 多意图场景
        task_queue.append({
            "agent": primary_agent,
            "input": text_to_analyze,
            "depends_on": None,
        })
        for secondary in decision.secondary:
            if secondary.agent != primary_agent and _agent_available(secondary.agent):
                task_queue.append({
                    "agent": secondary.agent,
                    "input": text_to_analyze,
                    "depends_on": None if decision.is_parallel else primary_agent,
                })

        logger.info(
            "LLM 路由 → 多意图: %d 个任务 %s | %s",
            len(task_queue),
            "(并行)" if decision.is_parallel else "(串行)",
            decision.summary,
        )
    else:
        # 单意图
        task_queue.append({
            "agent": primary_agent,
            "input": text_to_analyze,
            "depends_on": None,
        })
        logger.info(
            "LLM 路由 → %s (置信度=%.2f): %s",
            primary_agent, decision.primary.confidence, decision.summary,
        )

    return {
        "next_agent": primary_agent,
        "is_chitchat": False,
        "routing_confidence": decision.primary.confidence,
        "task_queue": task_queue,
        "selected_option_id": None,
    }


def dispatch_node(state: SupervisorState) -> dict:
    """
    Dispatch 节点 — 执行单任务 / 并行分派多任务 / 串行执行。

    对于并行任务，同时启动（当前简化：按顺序 mock 执行）。
    对于串行任务，执行第一个，将结果存入 task_results，后续由 aggregate 继续。
    """
    t0 = time.time()
    task_queue: list[dict] = state.get("task_queue", [])
    next_agent = state.get("next_agent", SUPERVISOR_SELF)
    is_chitchat = state.get("is_chitchat", False)

    emit_status(
        "generate",
        "正在闲聊回复…" if (is_chitchat or next_agent == SUPERVISOR_SELF) else "正在作答…",
        agent=next_agent or "",
    )

    # 闲聊 → Supervisor 自行回复
    if is_chitchat or next_agent == SUPERVISOR_SELF:
        messages = state.get("messages", [])
        last_user_msg = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_msg = msg.content
                break

        # 纯问候词 → 简短固定文案；其他情况 → LLM 回复
        normalized = _normalize_utterance(last_user_msg)
        if normalized in CHITCHAT_EXACT:
            reply = _handle_chitchat(last_user_msg, state.get("coach_style", "encouraging"))
            emit_token(reply)
        else:
            reply = _llm_chitchat(last_user_msg, state.get("coach_style", "encouraging"))

        log_timing("supervisor.dispatch.chitchat", time.time() - t0)
        # 闲聊回复一般不含任务列表；有则写入，无则清空本线程 pending
        pending_upd = _pending_updates_from_reply(reply, SUPERVISOR_SELF)
        return {
            "messages": [AIMessage(content=reply)],
            "final_response": reply,
            "task_results": [],
            "citations": [],
            "analogy_citations": [],
            "resume_artifact_id": "",
            "resume_mode": "",
            "resume_title": "",
            **pending_upd,
        }

    # 兜底：从对话历史取学员最新消息（防止 input 为空）
    last_user_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content
            break

    if not task_queue:
        # 单任务兜底：无 task_queue 时用 next_agent + 学员原话
        task_queue = [{"agent": next_agent, "input": last_user_msg, "depends_on": None}]

    # ── 更新调用计数 ──
    called: list[str] = state.get("called", [])
    call_count: dict[str, int] = state.get("call_count", {}).copy()

    task_results: list[dict] = []

    for task in task_queue:
        agent_name = task.get("agent", "")
        task_input = task.get("input") or last_user_msg

        called.append(agent_name)
        call_count[agent_name] = call_count.get(agent_name, 0) + 1

        t_agent = time.time()
        from src.agents.course_scope import resolve_course_scope
        scope = resolve_course_scope(
            state,
            int(state.get("student_id") or 0),
            message=task_input or last_user_msg,
        )
        dispatched = _dispatch_to_agent(
            agent_name=agent_name,
            task_input=task_input,
            student_id=state.get("student_id", 0),
            coach_style=state.get("coach_style", "encouraging"),
            emotion=state.get("emotion", "neutral"),
            chat_history=state.get("messages", []),
            conversation_summary=state.get("conversation_summary") or "",
            course_id=scope.get("course_id"),
            scope_mode=str(scope.get("mode") or "open"),
        )
        log_timing(
            "supervisor.dispatch.agent",
            time.time() - t_agent,
            agent=agent_name,
        )
        task_results.append({
            "agent": agent_name,
            "output": dispatched["output"],
            "citations": dispatched.get("citations") or [],
            "analogy_citations": dispatched.get("analogy_citations") or [],
            "resume_artifact_id": dispatched.get("resume_artifact_id") or "",
            "resume_mode": dispatched.get("resume_mode") or "",
            "resume_title": dispatched.get("resume_title") or "",
            "status": "routed",
        })

        logger.info("Dispatch → %s (第 %d 次)", agent_name, call_count[agent_name])

    # ── 聚合结果 ──
    final = _aggregate_results(task_results, state)
    # 本线程：回复含编号列表则写入 pending，供下一轮选号 / 前端可点选项
    sticky_agent = next_agent if next_agent in ALL_AGENTS else (
        task_results[-1]["agent"] if task_results else QA_AGENT
    )
    pending_upd = _pending_updates_from_reply(final, sticky_agent)

    # 写回 AIMessage 后的全量视图（用于滚动摘要；本轮 reply 尚未经 reducer 合并）
    messages_after = list(state.get("messages") or []) + [AIMessage(content=final)]
    try:
        from src.memory.context import maybe_update_thread_summary
        maybe_update_thread_summary(
            student_id=int(state.get("student_id") or 0),
            thread_id=str(state.get("thread_id") or ""),
            messages=messages_after,
        )
    except Exception as e:
        logger.warning("滚动摘要更新失败（不阻塞主回复）: %s", e)

    # 合并本轮 QA 主 citations / 类比 citations（非 QA 为空）
    from src.agents.citations import normalize_citations
    merged_citations: list[dict] = []
    merged_analogy: list[dict] = []
    for tr in task_results:
        if tr.get("agent") == QA_AGENT:
            merged_citations.extend(tr.get("citations") or [])
            merged_analogy.extend(tr.get("analogy_citations") or [])
    citations = normalize_citations(merged_citations)
    analogy_citations = normalize_citations(merged_analogy)

    # 本轮 Resume 终稿（取最后一次非空）
    resume_artifact_id = ""
    resume_mode = ""
    resume_title = ""
    for tr in task_results:
        if tr.get("agent") == RESUME_AGENT and tr.get("resume_artifact_id"):
            resume_artifact_id = str(tr.get("resume_artifact_id") or "")
            resume_mode = str(tr.get("resume_mode") or "")
            resume_title = str(tr.get("resume_title") or "")

    return {
        "messages": [AIMessage(content=final)],
        "called": called,
        "call_count": call_count,
        "task_results": task_results,
        "final_response": final,
        "citations": citations,
        "analogy_citations": analogy_citations,
        "resume_artifact_id": resume_artifact_id,
        "resume_mode": resume_mode,
        "resume_title": resume_title,
        **pending_upd,
    }


def _dispatch_to_agent(
    agent_name: str,
    task_input: str,
    student_id: int,
    coach_style: str,
    emotion: str,
    chat_history: list | None = None,
    conversation_summary: str = "",
    course_id: str | None = None,
    scope_mode: str = "open",
) -> dict:
    """
    调用子 Agent。

    返回 {"output": str, "citations": list}；citations 仅 QA 检索轮次非空。

    已实现：QA / Progress / Recommend / JobMatch / Resume
    待实现：Interview / SharedTools

    上下文预算：只传「摘要 + 近窗 + 本轮 input」，禁止全量 history。
    """
    from src.memory.context import build_agent_messages

    if agent_name == QA_AGENT:
        from src.agents.qa import build_qa_agent
        agent = build_qa_agent(coach_style=coach_style, emotion=emotion)

    elif agent_name == PROGRESS_AGENT:
        from src.agents.progress import build_progress_agent
        agent = build_progress_agent(coach_style=coach_style, emotion=emotion)

    elif agent_name == RECOMMEND_AGENT:
        from src.agents.recommend import build_recommend_agent
        agent = build_recommend_agent(coach_style=coach_style, emotion=emotion)

    elif agent_name == JOBMATCH_AGENT:
        from src.agents.jobmatch import build_jobmatch_agent
        agent = build_jobmatch_agent(
            coach_style=coach_style,
            emotion=emotion,
            student_id=int(student_id or 1),
        )

    elif agent_name == RESUME_AGENT:
        from src.agents.resume import build_resume_agent
        agent = build_resume_agent(
            coach_style=coach_style,
            emotion=emotion,
            student_id=int(student_id or 1),
        )

    elif agent_name == INTERVIEW_AGENT:
        from src.agents.interview import build_interview_agent
        agent = build_interview_agent(
            coach_style=coach_style,
            emotion=emotion,
            student_id=int(student_id or 1),
        )

    else:
        agent_display = {
            SHARED_TOOLS: "系统工具",
        }
        display = agent_display.get(agent_name, agent_name)
        return {
            "output": f"[{display}] 功能正在开发中，敬请期待。",
            "citations": [],
            "analogy_citations": [],
            "resume_artifact_id": "",
            "resume_mode": "",
            "resume_title": "",
        }

    try:
        full_n = len(chat_history or [])
        # 有焦点时提示 Agent 只依据该课；类比仅口头/独立区
        scoped_input = task_input
        # 当前登录学员：注入上下文，禁止 Agent 向用户要 student_id
        if agent_name in (
            RESUME_AGENT, JOBMATCH_AGENT, PROGRESS_AGENT, RECOMMEND_AGENT,
            QA_AGENT, INTERVIEW_AGENT,
        ):
            from src.agents.student_context import student_id_context_prefix
            scoped_input = student_id_context_prefix(int(student_id or 1)) + scoped_input
        if agent_name == QA_AGENT and course_id:
            scoped_input = (
                f"[课程作用域 mode={scope_mode} course_id={course_id}]\n"
                f"请只依据该课资料回答；可口头类比学员已学其他课，但不要把其他课当成本课进度。\n"
                f"检索时请传 course_id={course_id}。\n\n"
                f"{scoped_input}"
            )
        input_messages = build_agent_messages(
            chat_history or [],
            scoped_input,
            summary_text=conversation_summary or None,
        )
        logger.info(
            "[dispatch] 传给 %s 的消息数: %d (全量历史=%d, 已裁剪, summary=%s, course=%s)",
            agent_name, len(input_messages), full_n, bool(conversation_summary),
            course_id or "",
        )
        t_invoke = time.time()
        result = _invoke_agent_maybe_stream(agent, input_messages, agent_name=agent_name)
        log_timing(
            "supervisor.agent.invoke",
            time.time() - t_invoke,
            agent=agent_name,
        )
        messages = result.get("messages", [])
        citations: list[dict] = []
        analogy_citations: list[dict] = []
        resume_meta = {"artifact_id": "", "mode": "", "title": ""}
        if agent_name == QA_AGENT:
            from src.agents.citations import ensure_qa_citations, fetch_analogy_citations
            emit_status("cite", "正在整理引文…")
            citations = ensure_qa_citations(
                task_input,
                chat_history,
                messages,
                course_id=course_id,
            )
            # Soft/Hard/Profile 有焦点时才跑类比路
            if course_id and scope_mode in ("hard", "turn_hint", "soft"):
                analogy_citations = fetch_analogy_citations(
                    task_input,
                    chat_history,
                    int(student_id or 0),
                    focus_course_id=course_id,
                    top_k=3,
                )
        if agent_name == RESUME_AGENT:
            from src.tools.resume_tools import extract_resume_artifact_from_messages
            resume_meta = extract_resume_artifact_from_messages(messages)
        if messages:
            last_msg = messages[-1]
            text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
            return {
                "output": text,
                "citations": citations,
                "analogy_citations": analogy_citations,
                "resume_artifact_id": resume_meta.get("artifact_id") or "",
                "resume_mode": resume_meta.get("mode") or "",
                "resume_title": resume_meta.get("title") or "",
            }
        return {
            "output": "抱歉，我暂时无法处理这个请求。",
            "citations": citations,
            "analogy_citations": analogy_citations,
            "resume_artifact_id": resume_meta.get("artifact_id") or "",
            "resume_mode": resume_meta.get("mode") or "",
            "resume_title": resume_meta.get("title") or "",
        }
    except Exception as e:
        logger.error("子 Agent 调用失败: %s -> %s", agent_name, e)
        return {
            "output": "处理请求时出错，请稍后重试。",
            "citations": [],
            "analogy_citations": [],
            "resume_artifact_id": "",
            "resume_mode": "",
            "resume_title": "",
        }


def _invoke_agent_maybe_stream(agent, input_messages: list, *, agent_name: str) -> dict:
    """
    调用子 Agent：有流式回调时用 stream 转发正文 token，否则 invoke。
    返回与 agent.invoke 相同结构 {"messages": [...]}。

    关键：ReAct 会先产出「我去查一下」+ tool_call，再产出最终答案。
    若把工具轮文本也 emit，前端会拼出错乱（甚至夹杂 tool 碎片如 direct）。
    策略：工具轮整段丢弃；见过工具后的 AI 文本才直播；无工具的首轮等该轮结束后再发。
    """
    if not has_stream_callback():
        return agent.invoke({"messages": input_messages})

    emit_status("generate", "正在作答…", agent=agent_name)
    last_values: dict | None = None
    # message.id → 是否因 tool_call 被抑制
    suppressed_ids: set[str] = set()
    saw_tool = False
    current_id: str | None = None
    pending: list[str] = []

    def _flush_pending() -> None:
        nonlocal pending
        for part in pending:
            emit_token(part)
        pending = []

    def _on_message_boundary() -> None:
        """上一轮 AI 消息结束：无工具则把缓冲发出（直接作答）。"""
        nonlocal pending, current_id
        if current_id and current_id not in suppressed_ids and not saw_tool:
            _flush_pending()
        else:
            pending = []

    try:
        for item in agent.stream(
            {"messages": input_messages},
            stream_mode=["messages", "values"],
        ):
            if isinstance(item, tuple) and len(item) == 2 and item[0] in ("messages", "values"):
                mode, data = item
            else:
                mode, data = "messages", item

            if mode == "values" and isinstance(data, dict):
                last_values = data
                continue

            if mode != "messages":
                continue

            chunk = data[0] if isinstance(data, tuple) else data
            mid = str(getattr(chunk, "id", None) or "") or f"anon-{id(chunk)}"

            if current_id is not None and mid != current_id:
                _on_message_boundary()
            current_id = mid

            if chunk_has_tool_calls(chunk):
                suppressed_ids.add(mid)
                saw_tool = True
                pending = []
                continue

            if mid in suppressed_ids:
                continue

            text = chunk_text(chunk)
            if not text:
                continue

            # 已走过工具 → 后续 AI 文本即最终作答，直播
            if saw_tool:
                emit_token(text)
            else:
                # 尚不知本轮是否会带 tool_call，先缓冲
                pending.append(text)

        # 流结束：刷掉最后一轮（无工具的直接回答）
        _on_message_boundary()
    except Exception as e:
        logger.warning("Agent stream 失败，回退 invoke: %s", e)
        return agent.invoke({"messages": input_messages})

    if last_values is not None:
        return last_values
    return agent.invoke({"messages": input_messages})


def _llm_chitchat(user_message: str, coach_style: str) -> str:
    """用 LLM 生成闲聊回复（非问候词时调用，按 CoachStyle 礼貌简短回应）"""
    prompt = _build_chitchat_prompt(user_message, coach_style)
    try:
        provider = LLMProvider.create()
        model = provider.get_model(temperature=0.5)
        if has_stream_callback():
            parts: list[str] = []
            for chunk in model.stream(prompt):
                text = chunk_text(chunk)
                if text:
                    parts.append(text)
                    emit_token(text)
            return "".join(parts).strip()
        response = model.invoke(prompt)
        return response.content.strip() if hasattr(response, "content") else str(response).strip()
    except Exception as e:
        logger.warning("LLM 闲聊生成失败: %s，降级到固定文案", e)
        return _handle_chitchat(user_message, coach_style)


def _build_chitchat_prompt(user_message: str, coach_style: str) -> str:
    """构建闲聊 prompt，保持角色一致性"""
    coach_prompt = get_coach_prompt(coach_style)
    return f"""{coach_prompt}

学员给你发了一条消息，看起来不像是具体的课程问题。请用你的风格简短、自然地回应。不需要介绍自己是谁，也不需要提供课程帮助——学员只是在闲聊。

学员消息：{user_message}

你的回复："""


def _handle_chitchat(user_message: str, coach_style: str) -> str:
    """
    处理纯闲聊 — Supervisor 自行回复。

    按寒暄类型 + CoachStyle 选短回复；不用「我是谁」顶替一切。
    """
    n = _normalize_utterance(user_message)
    kind = "greet"
    if n in {"谢谢", "谢谢你", "谢谢啦", "感谢"}:
        kind = "thanks"
    elif n in {"再见", "拜拜", "晚安"}:
        kind = "bye"

    replies = {
        "encouraging": {
            "greet": "你好呀！有什么学习上的问题我可以帮你吗？慢慢来，不着急～",
            "thanks": "不客气～有问题随时再来问我。",
            "bye": "再见，下次继续加油～",
        },
        "pushing": {
            "greet": "你好。有什么事直接说，别浪费时间。",
            "thanks": "嗯，继续保持。",
            "bye": "走了？记得把练习做完再回来。",
        },
        "humorous": {
            "greet": "嗨！有什么问题尽管砸过来～",
            "thanks": "哈哈客气啦，随时召唤为师。",
            "bye": "拜啦，下次见～",
        },
        "professional": {
            "greet": "你好。请问有什么学习问题需要帮助？",
            "thanks": "不客气。还有问题可以继续提问。",
            "bye": "再见。",
        },
    }
    style = replies.get(coach_style, replies["encouraging"])
    return style.get(kind, style["greet"])


def _aggregate_results(task_results: list[dict], state: SupervisorState) -> str:
    """
    聚合多个任务结果为最终回复。

    单任务直接透传，多任务按顺序拼接。
    """
    if not task_results:
        return "抱歉，我暂时无法处理这个请求。"

    if len(task_results) == 1:
        return task_results[0].get("output", "")

    # 多任务聚合
    parts = []
    for i, tr in enumerate(task_results, 1):
        agent_name = tr.get("agent", "unknown")
        output = tr.get("output", "")
        parts.append(f"**【任务 {i}】** ({agent_name})\n{output}")

    return "\n\n".join(parts)


def aggregate_node(state: SupervisorState) -> dict:
    """
    Aggregate 节点 — 检查串行任务是否需要继续执行下一步。

    如果是串行任务且有未完成的任务，将结果注入后续任务 context。
    如果全部完成，生成最终回复。
    """
    task_queue: list[dict] = state.get("task_queue", [])
    task_results: list[dict] = state.get("task_results", [])

    # 如果没有多步骤任务，直接返回
    if len(task_queue) <= 1:
        return {}

    # 检查是否还有未完成的任务
    completed = len(task_results)
    if completed >= len(task_queue):
        # 全部完成
        final = _aggregate_results(task_results, state)
        return {"final_response": final}

    # 还有未完成的串行任务 → 标记需要继续 dispatch
    # (当前简化处理，在 dispatch_node 中一次性处理所有任务)
    return {}


def recovery_node(state: SupervisorState) -> dict:
    """
    Recovery 节点 — 处理子 Agent 退回重路由。

    1. 读取 needs_reroute / reroute_reason
    2. 将当前 Agent 加入 called 列表（防循环）
    3. 重置 next_agent，触发 decide 重新路由
    """
    needs_reroute = state.get("needs_reroute", False)

    if not needs_reroute:
        # 无重路由需求，直接通过
        return {}

    reroute_reason = state.get("reroute_reason", "")
    next_agent = state.get("next_agent", "")
    called: list[str] = state.get("called", [])
    call_count: dict[str, int] = state.get("call_count", {}).copy()

    # 记录原路由
    if next_agent and next_agent not in called:
        called.append(next_agent)
    call_count[next_agent] = call_count.get(next_agent, 0) + 1

    logger.info("Recovery — 原路由=%s 原因=%s called=%s", next_agent, reroute_reason, called)

    # 如果所有 Agent 都达到上限，回退到 Supervisor
    all_exhausted = all(
        call_count.get(agent, 0) >= MAX_CALLS_PER_AGENT
        for agent in ALL_AGENTS
    )
    if all_exhausted:
        logger.warning("所有 Agent 达到调用上限，回退到 Supervisor")
        return {
            "called": called,
            "call_count": call_count,
            "next_agent": SUPERVISOR_SELF,
            "needs_reroute": False,
            "final_response": "抱歉，我暂时无法确定如何处理这个请求。请换个方式描述你的问题？",
        }

    # 清除重路由标记，交由 decide 重新路由
    return {
        "called": called,
        "call_count": call_count,
        "needs_reroute": False,
        "next_agent": "",  # 清空，由 decide 重新填充
    }


# ── 条件边：Dispatch 后路由 ───────────────────────────────

def _after_dispatch(state: SupervisorState) -> str:
    """在 dispatch 之后判断下一步：有重路由需求 → recovery，否则 → END"""
    if state.get("needs_reroute", False):
        return "recovery"
    return END


def _after_recovery(state: SupervisorState) -> str:
    """在 recovery 之后判断：如果需重新路由则回 decide，否则 END"""
    if state.get("next_agent", "") == "":
        # 清空了 next_agent，需要重新 decide
        return "decide"
    return END


def _after_decide(state: SupervisorState) -> str:
    """在 decide 之后判断：如果是 supervisor → END，否则 → dispatch"""
    next_agent = state.get("next_agent", "")
    is_chitchat = state.get("is_chitchat", False)

    if next_agent == SUPERVISOR_SELF or is_chitchat:
        # Supervisor 自行回复，dispatch 会生成 final_response
        return "dispatch"
    if next_agent:
        return "dispatch"
    # 无法决定
    return END


# ── 图构建 ────────────────────────────────────────────────

def build_supervisor_graph() -> StateGraph:
    graph = StateGraph(SupervisorState)

    # 注册节点
    graph.add_node("probe", probe_node)
    graph.add_node("decide", decide_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("aggregate", aggregate_node)
    graph.add_node("recovery", recovery_node)

    # 设置入口
    graph.set_entry_point("probe")

    # probe → decide (无条件)
    graph.add_edge("probe", "decide")

    # decide → 条件路由
    graph.add_conditional_edges(
        "decide",
        _after_decide,
        {
            "dispatch": "dispatch",
            END: END,
        },
    )

    # dispatch → aggregate (无条件)
    graph.add_edge("dispatch", "aggregate")

    # aggregate → 条件路由
    graph.add_conditional_edges(
        "aggregate",
        _after_dispatch,
        {
            "recovery": "recovery",
            END: END,
        },
    )

    # recovery → 条件路由
    graph.add_conditional_edges(
        "recovery",
        _after_recovery,
        {
            "decide": "decide",
            END: END,
        },
    )

    # 编译 — 接入 RedisSaver Checkpointer，对话持久化
    from src.memory.checkpointer import get_checkpointer
    try:
        checkpointer = get_checkpointer()
        compiled_graph = graph.compile(checkpointer=checkpointer)
        logger.info("Supervisor 图编译完成（RedisSaver checkpointer 已接入）")
    except Exception as e:
        logger.warning("RedisSaver 连接失败，使用内存模式: %s", e)
        compiled_graph = graph.compile()
        logger.info("Supervisor 图编译完成（内存模式）")

    return compiled_graph


# ── 便捷入口 ──────────────────────────────────────────────

def run_supervisor(
    graph,
    student_id: int,
    message: str,
    thread_id: str | None = None,
    selected_option_id: int | None = None,
) -> dict:
    """
    运行 Supervisor 处理单条学员消息的便捷入口。

    graph 参数由调用方传入（启动时编译一次，请求中复用）。

    Checkpointer 按 thread_id 隔离会话状态（messages / pending_options 等）：
    - 调用前：从 Redis 恢复该 thread 的完整历史与 pending
    - 调用后：将本次更新写回同一 thread
    - **禁止**用 stu_{student_id} 让多会话共享状态

    调用方只需传入当前消息与 thread_id，不需要手动维护 chat_history。
    情绪仅在 probe_node 检测一次，经本返回值交给 API。

    参数：
        graph: 编译好的 Supervisor StateGraph（从 app.state.graph 获取）
        student_id: 学员 ID
        message: 学员的最新消息
        thread_id: 会话 ID（与前端 / QAHistory 一致）；缺省时退化为单学员单会话
        selected_option_id: 前端点击选项时传入的 id

    返回：
        {content, emotion, emotion_confidence, options, pending_agent,
         thread_id, agent, citations}
    """
    tid = (thread_id or "").strip() or f"stu_{student_id}"

    # 只传本轮输入字段；pending_options / pending_agent 故意省略，保留 checkpoint
    initial_state: dict = {
        "messages": [HumanMessage(content=message)],
        "student_id": student_id,
        "thread_id": tid,
        "coach_style": "encouraging",
        "emotion": "neutral",
        "emotion_confidence": 0.0,
        "next_agent": "",
        "called": [],
        "call_count": {},
        "task_queue": [],
        "task_results": [],
        "final_response": "",
        "citations": [],
        "analogy_citations": [],
        "resume_artifact_id": "",
        "resume_mode": "",
        "resume_title": "",
        "needs_reroute": False,
        "reroute_reason": "",
        "probe_evidence": {},
        "is_chitchat": False,
        "routing_confidence": 0.0,
        "selected_option_id": selected_option_id,
        "conversation_summary": "",
        # active/focus 故意省略，保留 checkpoint 中的会话焦点
    }

    config_dict = {
        "configurable": {"thread_id": tid},
        "recursion_limit": 25,
    }

    t_invoke = time.time()
    try:
        result = graph.invoke(initial_state, config_dict)
    except Exception as e:
        log_timing("supervisor.invoke", time.time() - t_invoke, error=str(e))
        logger.exception("Supervisor 执行异常: %s", e)
        return {
            "content": f"抱歉，处理你的消息时出现了问题。请稍后重试。（错误: {e}）",
            "emotion": "neutral",
            "emotion_confidence": 0.0,
            "options": [],
            "pending_agent": "",
            "thread_id": tid,
            "agent": "",
            "citations": [],
            "analogy_citations": [],
            "resume_artifact_id": "",
            "resume_mode": "",
            "resume_title": "",
        }

    log_timing(
        "supervisor.invoke",
        time.time() - t_invoke,
        agent=result.get("next_agent") or "",
        thread_id=tid,
    )

    final = result.get("final_response", "")
    if not final:
        next_agent = result.get("next_agent", "")
        routing_conf = result.get("routing_confidence", 0)
        final = f"[已决策] 路由到 {next_agent}（置信度 {routing_conf:.2f}）"

    options = list(result.get("pending_options") or [])
    return {
        "content": final,
        "emotion": result.get("emotion", "neutral"),
        "emotion_confidence": float(result.get("emotion_confidence") or 0.0),
        "options": options,
        "pending_agent": result.get("pending_agent") or "",
        "thread_id": tid,
        "agent": result.get("next_agent") or "",
        "citations": list(result.get("citations") or []),
        "analogy_citations": list(result.get("analogy_citations") or []),
        "resume_artifact_id": str(result.get("resume_artifact_id") or ""),
        "resume_mode": str(result.get("resume_mode") or ""),
        "resume_title": str(result.get("resume_title") or ""),
    }


def get_thread_dialog_state(graph, thread_id: str) -> dict:
    """
    读取指定会话的对话状态（pending_options 等）。

    用于切换会话时恢复可点选项；只读，不修改 checkpoint。
    """
    tid = (thread_id or "").strip()
    if not tid:
        return {"thread_id": "", "pending_options": [], "pending_agent": ""}
    try:
        snap = graph.get_state({"configurable": {"thread_id": tid}})
        values = getattr(snap, "values", None) or {}
        return {
            "thread_id": tid,
            "pending_options": list(values.get("pending_options") or []),
            "pending_agent": values.get("pending_agent") or "",
        }
    except Exception as e:
        logger.warning("读取线程状态失败 thread=%s: %s", tid, e)
        return {"thread_id": tid, "pending_options": [], "pending_agent": ""}


def delete_thread_checkpoint(graph, thread_id: str) -> bool:
    """删除指定会话的 Checkpointer 状态，避免残留 pending 干扰。"""
    tid = (thread_id or "").strip()
    if not tid:
        return False
    try:
        checkpointer = getattr(graph, "checkpointer", None)
        if checkpointer is None:
            return False
        # langgraph / langgraph-checkpoint 常见 API
        if hasattr(checkpointer, "delete_thread"):
            checkpointer.delete_thread(tid)
            return True
        if hasattr(graph, "update_state"):
            # 无 delete 时尽力清空 pending，避免幽灵选项
            graph.update_state(
                {"configurable": {"thread_id": tid}},
                {"pending_options": [], "pending_agent": ""},
            )
            return True
    except Exception as e:
        logger.warning("删除线程 checkpoint 失败 thread=%s: %s", tid, e)
    return False


# ── 异步版本 ──────────────────────────────────────────────

async def run_supervisor_async(
    graph,
    student_id: int,
    message: str,
    thread_id: str | None = None,
    selected_option_id: int | None = None,
) -> dict:
    """
    异步运行 Supervisor（用于 FastAPI / 异步上下文）。

    内部调用同步版 run_supervisor，通过 asyncio.to_thread 避免阻塞事件循环。
    """
    return await asyncio.to_thread(
        run_supervisor, graph, student_id, message, thread_id, selected_option_id,
    )
