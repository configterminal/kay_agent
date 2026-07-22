"""
简历工具 — 证据驱动解析 / 定向审计 / 整页优化 / 画像同步。

供 ResumeAgent 调用。对照站内 job_roles +（可选）公开网络侧重点；
非招聘平台实时 ATS。终稿驱动训练题与面试重点种子。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.tools import tool

from src.db.init_db import get_session
from src.db.schema import JobRole
from src.llm.base import LLMProvider
from src.resume.artifact import save_resume_artifact
from src.schemas.resume import ResumeDocument

logger = logging.getLogger(__name__)

_MIN_BULLETS = 10
_MIN_BULLETS_PER_BLOCK = 3

# 课练面/求职辅导内容：只进聊天，禁止写进简历正文
_COACHING_LEAK_RE = re.compile(
    r"(简历优化|技术面试|跳槽策略|谈薪|晋升策略|职业规划|学习闭环|课程推荐|"
    r"程序员职业跃迁|综合实践|模拟面试|投递计划|跟进计划|训练题|面试准备|"
    r"站内课程|课练面|如何兑现)"
)
_SOFT_SKILL_KEYWORDS = frozenset({
    "简历优化", "技术面试", "跳槽策略", "谈薪晋升", "职业规划",
    "择业副业", "在职成长",
})

# 畸形量化占位：如 [量化待补：%] / [量化待补：] / [量化待补：123]
_PLACEHOLDER_RE = re.compile(r"\[量化待补[：:]\s*([^\]]*)\]")
_PLACEHOLDER_GOOD_HINT = re.compile(r"[\u4e00-\u9fffA-Za-z]{2,}")


def _get_llm(temperature: float = 0.3):
    """获取 LLM 实例。"""
    provider = LLMProvider.create()
    return provider.get_model(temperature=temperature)


def _extract_json(content: str) -> dict:
    """从 LLM 回复中抽出 JSON 对象。"""
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )
    return json.loads(text)


def _safe_json_loads(raw: str) -> dict | None:
    """尽力解析 JSON。"""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text) if text.lstrip().startswith("{") else _extract_json(text)
        return data if isinstance(data, dict) else None
    except Exception:
        try:
            data = _extract_json(text)
            return data if isinstance(data, dict) else None
        except Exception:
            return None


def _load_role(role_id: str) -> dict[str, Any]:
    """加载站内岗位模板。"""
    with get_session() as session:
        role = session.query(JobRole).filter(JobRole.role_id == role_id).first()
    if not role:
        return {
            "role_id": role_id,
            "title": role_id,
            "required_skills": [],
            "preferred_skills": [],
            "description": "",
        }
    return {
        "role_id": role.role_id,
        "title": role.title or role_id,
        "required_skills": list(role.required_skills or []),
        "preferred_skills": list(role.preferred_skills or []),
        "description": role.description or "",
    }


def _count_bullets(doc: dict) -> int:
    """统计终稿 bullet 总数。"""
    n = 0
    for sec in doc.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        for block in sec.get("blocks") or []:
            if isinstance(block, dict):
                n += len([b for b in (block.get("bullets") or []) if b])
    return n


def _density_report(doc: dict) -> dict[str, Any]:
    """密度门禁报告。"""
    bullets = _count_bullets(doc)
    sections = [s for s in (doc.get("sections") or []) if isinstance(s, dict)]
    headings = " ".join(str(s.get("heading") or "") + str(s.get("type") or "") for s in sections)
    has_skills = "skill" in headings.lower() or "技能" in headings
    has_exp = any(
        t in headings.lower() or k in headings
        for t, k in (("experience", "经历"), ("project", "项目"), ("work", "工作"))
    )
    thin_blocks = []
    for sec in sections:
        sec_type = str(sec.get("type") or "").lower()
        heading = str(sec.get("heading") or "")
        # 教育 / 纯技能行：不强制每块 ≥3 bullets
        if "education" in sec_type or "教育" in heading or "学历" in heading:
            continue
        if "skill" in sec_type or "技能" in heading:
            continue
        for block in sec.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            bs = [b for b in (block.get("bullets") or []) if b]
            if block.get("skills_line") and not bs:
                continue
            label = block.get("company") or block.get("title") or sec.get("heading") or "?"
            if 0 < len(bs) < _MIN_BULLETS_PER_BLOCK:
                thin_blocks.append(str(label))
            elif not bs and (block.get("company") or block.get("title")):
                thin_blocks.append(str(label))
    ok = (
        bullets >= _MIN_BULLETS
        and bool(doc.get("intention"))
        and has_skills
        and has_exp
        and len(thin_blocks) == 0
    )
    reasons = []
    if bullets < _MIN_BULLETS:
        reasons.append(f"bullets={bullets}<{_MIN_BULLETS}")
    if not doc.get("intention"):
        reasons.append("缺求职意向")
    if not has_skills:
        reasons.append("缺技能区")
    if not has_exp:
        reasons.append("缺经历/项目")
    if thin_blocks:
        reasons.append(f"过瘦块:{','.join(thin_blocks[:5])}")
    return {"ok": ok, "bullets": bullets, "reasons": reasons}


def _normalize_doc(data: dict, mode: str) -> dict:
    """规范 ResumeDocument 并补 footer。"""
    data = dict(data or {})
    mode = mode if mode in ("fact", "target") else "fact"
    data["mode"] = mode
    if mode == "target" and not data.get("footer_note"):
        data["footer_note"] = (
            "【目标蓝图】完成对应课程/项目前，请勿当作已有任职经历投递。"
        )
    elif mode == "fact" and not data.get("footer_note"):
        data["footer_note"] = (
            "按目标方向定向优化；未改动任职公司/年限/真实 title。"
            "对照含站内课程方向与公开资料侧重点，非招聘平台实时 ATS。"
        )
    try:
        return ResumeDocument.model_validate(data).model_dump()
    except Exception as e:
        logger.warning("ResumeDocument 校验失败，尽力保存: %s", e)
        return data


def _save_doc(payload: dict) -> dict:
    """保存 artifact 并返回标准元信息。"""
    aid = save_resume_artifact(payload)
    title = str(payload.get("title") or payload.get("role_title") or "优化简历")
    return {
        "ok": True,
        "artifact_id": aid,
        "mode": payload.get("mode") or "fact",
        "title": title,
        "preview_path": f"/api/resume/preview/{aid}",
        "pdf_path": f"/api/resume/pdf/{aid}",
    }


# ── 简历解析 ────────────────────────────────────────

@tool
def parse_resume(text: str) -> dict:
    """
    将简历解析为事实底稿（只提取原文已有信息，不编造）。

    返回含 contact / experience_blocks / project_blocks / skills / evidence 等，
    供定向优化与画像同步使用。
    """
    empty = {
        "contact": {},
        "intention": "",
        "sections": [],
        "skills_found": [],
        "skills": [],
        "years": None,
        "education": None,
        "education_detail": {},
        "projects": [],
        "project_blocks": [],
        "employers": [],
        "experience_blocks": [],
        "persona_hint": "",
        "evidence_flags": [],
    }
    if not text or not text.strip():
        return empty

    prompt = f"""你是中文互联网技术岗简历解析助手。只提取原文已有信息，禁止编造。

返回纯 JSON：
{{
  "contact": {{"name": "", "phone": "", "email": "", "city": ""}},
  "intention": "求职意向原文或空",
  "sections": ["段落标题..."],
  "skills_found": ["技能..."],
  "skills": ["技能..."],
  "years": 数字或null,
  "education": "最高学历一句话或null",
  "education_detail": {{"school": "", "major": "", "degree": "", "period": ""}},
  "projects": ["项目一句话..."],
  "project_blocks": [
    {{"title": "", "period": "", "raw_bullets": ["原文要点..."], "context": "一句话背景或空"}}
  ],
  "employers": [{{"company": "", "title": "真实title", "years_hint": ""}}],
  "experience_blocks": [
    {{"company": "", "title": "", "period": "", "raw_bullets": ["..."], "context": ""}}
  ],
  "persona_hint": "university_student 或 working_professional 或空",
  "evidence_flags": ["空窗/时间冲突/只有职责无结果 等线索，无则空数组"]
}}

规则：
- title/company/period 必须来自原文，勿改成目标岗 title
- raw_bullets 尽量保留原文句，勿润色
- years 为总工作年限估算，不确定则 null

简历文本：
{text}"""

    try:
        llm = _get_llm(temperature=0)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        result = _extract_json(content)
        skills = result.get("skills") or result.get("skills_found") or []
        return {
            "contact": result.get("contact") or {},
            "intention": result.get("intention") or "",
            "sections": result.get("sections") or [],
            "skills_found": result.get("skills_found") or skills,
            "skills": skills,
            "years": result.get("years"),
            "education": result.get("education"),
            "education_detail": result.get("education_detail") or {},
            "projects": result.get("projects") or [],
            "project_blocks": result.get("project_blocks") or [],
            "employers": result.get("employers") or [],
            "experience_blocks": result.get("experience_blocks") or [],
            "persona_hint": result.get("persona_hint") or "",
            "evidence_flags": result.get("evidence_flags") or [],
        }
    except Exception as e:
        logger.warning("parse_resume 失败: %s", e)
        return empty


# ── 画像同步 ────────────────────────────────────────

@tool
def sync_resume_profile(student_id: int, parse_json: str) -> dict:
    """
    将 parse_resume 结果中的高置信字段写入学员画像。

    参数：
        student_id: 学员 ID
        parse_json: parse_resume 返回的 JSON 字符串（或子集）

    返回：
        {ok, updated_fields, profile} 或 error
    """
    from src.tools.shared_tools import update_student_profile

    data = _safe_json_loads(parse_json) or {}
    contact = data.get("contact") if isinstance(data.get("contact"), dict) else {}
    edu = data.get("education_detail") if isinstance(data.get("education_detail"), dict) else {}
    employers = data.get("employers") or []
    first_emp = employers[0] if employers and isinstance(employers[0], dict) else {}

    kwargs: dict[str, Any] = {"student_id": int(student_id)}
    updated: list[str] = []

    name = (contact.get("name") or "").strip()
    if name:
        kwargs["display_name"] = name
        updated.append("display_name")

    company = (first_emp.get("company") or "").strip()
    if company:
        kwargs["company"] = company
        updated.append("company")

    job_title = (first_emp.get("title") or "").strip()
    if job_title:
        kwargs["job_title"] = job_title
        updated.append("job_title")

    years = data.get("years")
    if years is not None:
        try:
            kwargs["years_of_experience"] = int(years)
            updated.append("years_of_experience")
        except (TypeError, ValueError):
            pass

    school = (edu.get("school") or "").strip()
    if school:
        kwargs["university"] = school
        updated.append("university")

    major = (edu.get("major") or "").strip()
    if major:
        kwargs["major"] = major
        updated.append("major")

    persona = (data.get("persona_hint") or "").strip()
    if persona in ("university_student", "working_professional"):
        kwargs["persona"] = persona
        updated.append("persona")
    elif years is not None:
        try:
            kwargs["persona"] = (
                "working_professional" if int(years) >= 1 else "university_student"
            )
            updated.append("persona")
        except (TypeError, ValueError):
            pass

    # 粗估 skill_level
    try:
        y = int(years) if years is not None else None
        if y is not None:
            if y <= 1:
                kwargs["skill_level"] = "beginner"
            elif y <= 4:
                kwargs["skill_level"] = "intermediate"
            else:
                kwargs["skill_level"] = "advanced"
            updated.append("skill_level")
    except (TypeError, ValueError):
        pass

    if len(updated) == 0:
        return {"ok": True, "updated_fields": [], "profile": {}, "note": "无可写入的高置信字段"}

    result = update_student_profile.invoke(kwargs)
    return {
        "ok": not bool(result.get("error")),
        "updated_fields": updated,
        "profile": result,
    }


# ── JobMatch 定向 brief ─────────────────────────────

@tool
def build_resume_direct_brief(
    role_id: str,
    student_id: int = 0,
    resume_text: str = "",
) -> dict:
    """
    汇聚 JobMatch 定向信号：站内 role 关键词 + skill_gap + 简历主题保留/压缩清单。

    有目标方向时在 optimize 前调用。匹配为站内课程能力模型，非实时市场。
    """
    role = _load_role(role_id)
    must = list(role["required_skills"]) + list(role["preferred_skills"])
    mastered: list[str] = []
    gaps: list[str] = []
    match_pct = 0.0

    if student_id:
        try:
            from src.tools.jobmatch_tools import analyze_skill_gap

            gap_res = analyze_skill_gap.invoke(
                {"student_id": int(student_id), "role_id": role_id}
            )
            if isinstance(gap_res, dict) and not gap_res.get("error"):
                mastered = list(gap_res.get("mastered") or [])
                gaps = [
                    g.get("skill") if isinstance(g, dict) else str(g)
                    for g in (gap_res.get("gaps") or [])
                ]
                match_pct = float(gap_res.get("match_pct") or 0)
        except Exception as e:
            logger.warning("build_resume_direct_brief skill_gap 失败: %s", e)

    keep_themes: list[str] = []
    compress_themes: list[str] = []
    text_l = (resume_text or "").lower()

    # 关键词命中 → keep；常见弱相关主题 → compress 候选
    for kw in must:
        if kw and (kw.lower() in text_l or kw in (resume_text or "")):
            keep_themes.append(kw)
    weak_hints = ["渲染", "游戏", "图形", "美工", "运维值班", "测试用例执行"]
    for w in weak_hints:
        if w in (resume_text or "") and w not in keep_themes:
            # 仅当目标不是这些方向时标压缩
            if not any(w in m for m in must):
                compress_themes.append(w)

    return {
        "source": "course",
        "role_id": role["role_id"],
        "role_title": role["title"],
        "must_keywords": must,
        "mastered": mastered,
        "gaps": gaps,
        "match_pct": match_pct,
        "keep_themes": keep_themes or must[:6],
        "compress_themes": compress_themes,
        "note": "基于站内课程方向模板与学习进度，非实时招聘市场。",
    }


# ── 网络侧重点 ──────────────────────────────────────

def _web_search_snippets(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo 文本摘要；失败返回空。"""
    try:
        from ddgs import DDGS

        rows = list(DDGS().text(query, max_results=max_results))
        out = []
        for r in rows or []:
            out.append({
                "title": (r.get("title") or "")[:200],
                "body": (r.get("body") or r.get("snippet") or "")[:400],
                "href": r.get("href") or r.get("link") or "",
            })
        return out
    except Exception as e:
        logger.warning("web search 失败: %s", e)
        return []


@tool
def research_target_role_signals(target_role: str, role_id: str = "") -> dict:
    """
    有目标岗位时，联网归纳「同类岗位常见经历/技能侧重点」。

    只指导写透/压缩主题，禁止把检索内容写成学员事实。
    标注：公开资料归纳，非实时招聘平台 JD / ATS。
    """
    role = _load_role(role_id) if role_id else {}
    label = (target_role or role.get("title") or role_id or "").strip()
    if not label:
        return {
            "ok": False,
            "error": "缺少 target_role",
            "emphasize_checklist": [],
            "deprioritize_hints": [],
            "sources_note": "未检索",
        }

    queries = [
        f"{label} 简历 项目经验 技能要求",
        f"{label} resume skills experience requirements",
    ]
    snippets: list[dict] = []
    for q in queries:
        snippets.extend(_web_search_snippets(q, max_results=4))
        if len(snippets) >= 6:
            break

    if not snippets:
        # 降级：仅用站内 role 关键词
        must = list(role.get("required_skills") or []) + list(role.get("preferred_skills") or [])
        return {
            "ok": True,
            "degraded": True,
            "typical_experience_patterns": must[:5],
            "emphasize_checklist": must[:8],
            "deprioritize_hints": ["与目标无关的旧技术栈细节", "纯职责罗列无产物的条目"],
            "sources_note": "网络检索不可用，已降级为站内方向关键词；非实时招聘市场。",
            "snippets_used": 0,
        }

    snip_text = "\n".join(
        f"- {s.get('title')}: {s.get('body')}" for s in snippets[:8]
    )
    prompt = f"""根据下列公开网页摘要，归纳「{label}」同类岗位简历侧重点。
不要编造具体公司名或个人项目；只提炼经历类型与技能主题。

站内方向补充：{role.get('title') or ''}
必需技能参考：{role.get('required_skills') or []}

网页摘要：
{snip_text}

返回纯 JSON：
{{
  "typical_experience_patterns": ["同类岗常见等价经历类型..."],
  "emphasize_checklist": ["简历应写透的主题..."],
  "deprioritize_hints": ["可压缩的弱相关主题..."]
}}"""
    try:
        llm = _get_llm(temperature=0.2)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        result = _extract_json(content)
        return {
            "ok": True,
            "degraded": False,
            "typical_experience_patterns": result.get("typical_experience_patterns") or [],
            "emphasize_checklist": result.get("emphasize_checklist") or [],
            "deprioritize_hints": result.get("deprioritize_hints") or [],
            "sources_note": "公开网络资料归纳，仅指导篇幅与侧重点；非实时招聘平台 JD/ATS，不得写入学员虚构经历。",
            "snippets_used": len(snippets),
        }
    except Exception as e:
        logger.warning("research 归纳失败: %s", e)
        must = list(role.get("required_skills") or [])
        return {
            "ok": True,
            "degraded": True,
            "typical_experience_patterns": must[:5],
            "emphasize_checklist": must[:8],
            "deprioritize_hints": [],
            "sources_note": f"归纳失败已降级（{e}）；非实时市场。",
            "snippets_used": len(snippets),
        }


# ── 简历反馈 ────────────────────────────────────────

@tool
def get_resume_feedback(
    text: str,
    role_id: str,
    direct_brief_json: str = "",
    research_json: str = "",
) -> dict:
    """
    对照站内方向（及可选定向/网络信号）审计简历。

    ats_score = 相对站内方向匹配分，不是大厂实时 ATS。
    返回覆盖矩阵、价值提炼、改写示例（示例不能当整份 PDF）。
    """
    if not text or not text.strip():
        return {
            "ats_score": 0.0,
            "missing_keywords": [],
            "matched_keywords": [],
            "coverage_matrix": [],
            "value_extract": [],
            "red_flags": ["简历内容为空"],
            "structural_suggestions": ["请提供完整简历文本"],
            "content_suggestions": [],
            "trim_suggestions": [],
            "rewrite_examples": [],
        }

    role = _load_role(role_id)
    brief = _safe_json_loads(direct_brief_json) or {}
    research = _safe_json_loads(research_json) or {}

    skills_text = "\n".join(f"- {s}" for s in role["required_skills"]) or "（未设置）"
    preferred_text = "\n".join(f"- {s}" for s in role["preferred_skills"]) or "（未设置）"
    emphasize = research.get("emphasize_checklist") or brief.get("keep_themes") or []
    deprior = research.get("deprioritize_hints") or brief.get("compress_themes") or []

    prompt = f"""你是中国互联网技术岗简历审计官。对照站内方向模板做证据驱动审计（非招聘网站实时 JD）。

目标方向：{role['title']}（role_id={role_id}）
方向说明：{role['description']}
必需技能：
{skills_text}
加分技能：
{preferred_text}
应写透主题：{emphasize}
可压缩主题：{deprior}
JobMatch gaps：{brief.get('gaps') or []}

硬性约束：
1. 不伪造公司/在职/title；支持定向呈现
2. 项目须有上下文；bullet 逼近 动作+产物+结果；缺量化标待补
3. 覆盖标记：已覆盖/弱覆盖/未覆盖/可追问/不建议硬凑
4. ats_score 0-100 相对站内方向，勿称大厂 ATS

返回纯 JSON：
{{
  "ats_score": 0,
  "missing_keywords": [],
  "matched_keywords": [],
  "coverage_matrix": [
    {{"skill": "...", "status": "已覆盖|弱覆盖|未覆盖|可追问|不建议硬凑", "evidence": "简历证据或空"}}
  ],
  "value_extract": [
    {{"original": "...", "deliverable": "...", "result": "...", "missing_metric": "...", "rewrite_direction": "..."}}
  ],
  "red_flags": ["..."],
  "structural_suggestions": ["..."],
  "content_suggestions": ["..."],
  "trim_suggestions": ["..."],
  "rewrite_examples": [
    {{"original": "...", "rewritten": "...", "rationale": "..."}}
  ]
}}

rewrite_examples 2～4 条，必须来自原文。

简历全文：
{text}"""

    try:
        llm = _get_llm(temperature=0.3)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        result = _extract_json(content)
        rewrites = result.get("rewrite_examples") or []
        if not isinstance(rewrites, list):
            rewrites = []
        return {
            "ats_score": float(result.get("ats_score", 0)),
            "missing_keywords": result.get("missing_keywords") or [],
            "matched_keywords": result.get("matched_keywords") or [],
            "coverage_matrix": result.get("coverage_matrix") or [],
            "value_extract": result.get("value_extract") or [],
            "red_flags": result.get("red_flags") or [],
            "structural_suggestions": result.get("structural_suggestions") or [],
            "content_suggestions": result.get("content_suggestions") or [],
            "trim_suggestions": result.get("trim_suggestions") or [],
            "rewrite_examples": rewrites[:4],
            "source_note": "站内方向+公开侧重点（若有）；非实时 ATS",
        }
    except Exception as e:
        logger.warning("get_resume_feedback 失败: %s", e)
        return {
            "ats_score": 0.0,
            "missing_keywords": [],
            "matched_keywords": [],
            "coverage_matrix": [],
            "value_extract": [],
            "red_flags": ["简历分析失败，请稍后重试"],
            "structural_suggestions": ["简历分析失败，请稍后重试"],
            "content_suggestions": [],
            "trim_suggestions": [],
            "rewrite_examples": [],
        }


# ── 整页优化（主路径）────────────────────────────────

def _is_soft_skill_role(role_id: str) -> bool:
    """站内求职软技能方向（课练面），不是技术岗简历项目主题。"""
    return (role_id or "").strip() == "career_transition_engineer"


def _filter_tech_themes(items: list) -> list[str]:
    """去掉求职辅导类主题，避免写进简历正文。"""
    out: list[str] = []
    for x in items or []:
        s = str(x).strip()
        if not s:
            continue
        if s in _SOFT_SKILL_KEYWORDS or _COACHING_LEAK_RE.search(s):
            continue
        out.append(s)
    return out


def _block_blob(block: dict) -> str:
    """块文本拼接，供泄漏检测。"""
    parts = [
        str(block.get("company") or ""),
        str(block.get("title") or ""),
        str(block.get("period") or ""),
        str(block.get("skills_line") or ""),
        " ".join(str(b) for b in (block.get("bullets") or []) if b),
    ]
    return " ".join(parts)


def _fix_placeholder_text(text: str) -> tuple[str, list[str]]:
    """修正畸形 [量化待补：…]；返回 (新文本, 问题列表)。"""
    issues: list[str] = []
    s = text or ""

    def _repl(m: re.Match) -> str:
        inner = (m.group(1) or "").strip()
        raw = m.group(0)
        if not inner or not _PLACEHOLDER_GOOD_HINT.search(inner):
            issues.append(f"畸形占位「{raw}」")
            return "（具体数据待补充）"
        if re.fullmatch(r"[%\d.\s\-×xX/~]+", inner):
            issues.append(f"畸形占位「{raw}」")
            return "（具体数据待补充）"
        return raw

    s = _PLACEHOLDER_RE.sub(_repl, s)
    # 「覆盖（具体数据待补充）的常见图元」→ 通顺句
    awkward = re.compile(
        r"([\u4e00-\u9fffA-Za-z]{1,12})（具体数据待补充）的([\u4e00-\u9fffA-Za-z0-9]{1,16})"
    )
    if awkward.search(s):
        issues.append("不通顺嵌入占位已改写")
        s = awkward.sub(r"\1\2（具体范围/规模待补充）", s)
    # 「覆盖[量化待补：xxx]的常见图元」仍夹在中间 → 外置
    mid = re.compile(
        r"([\u4e00-\u9fffA-Za-z]{1,12})\[量化待补[：:][^\]]+\]的([\u4e00-\u9fffA-Za-z0-9]{1,16})"
    )
    if mid.search(s):
        issues.append("句中嵌入占位已外置")
        s = mid.sub(r"\1\2（具体范围/规模待补充）", s)
    return s, issues


def _iter_doc_strings(doc: dict):
    """遍历终稿可写文字字段，yield (path, value)。"""
    if doc.get("intention"):
        yield ("intention", str(doc["intention"]))
    if doc.get("footer_note"):
        yield ("footer_note", str(doc["footer_note"]))
    for si, sec in enumerate(doc.get("sections") or []):
        if not isinstance(sec, dict):
            continue
        for bi, block in enumerate(sec.get("blocks") or []):
            if not isinstance(block, dict):
                continue
            base = f"sections[{si}].blocks[{bi}]"
            for key in ("company", "title", "period", "skills_line"):
                if block.get(key):
                    yield (f"{base}.{key}", str(block[key]))
            for bj, b in enumerate(block.get("bullets") or []):
                if b:
                    yield (f"{base}.bullets[{bj}]", str(b))


def _set_doc_string(doc: dict, path: str, value: str) -> None:
    """按 _iter_doc_strings 的 path 写回。"""
    if path in ("intention", "footer_note"):
        doc[path] = value
        return
    m = re.match(
        r"sections\[(\d+)\]\.blocks\[(\d+)\]\.(company|title|period|skills_line|bullets\[(\d+)\])$",
        path,
    )
    if not m:
        return
    si, bi = int(m.group(1)), int(m.group(2))
    field = m.group(3)
    sec = (doc.get("sections") or [])[si]
    block = (sec.get("blocks") or [])[bi]
    if field.startswith("bullets["):
        bj = int(m.group(4))
        bullets = list(block.get("bullets") or [])
        if 0 <= bj < len(bullets):
            bullets[bj] = value
            block["bullets"] = bullets
    else:
        block[field] = value


def _rule_audit_and_fix(doc: dict) -> tuple[dict, list[str], list[str]]:
    """
    规则审核并尽量自动修复。

    返回 (文档, 已修复问题, 未修复/需重写问题)。
    """
    doc = dict(doc or {})
    sections = []
    for sec in doc.get("sections") or []:
        sections.append(dict(sec) if isinstance(sec, dict) else sec)
    doc["sections"] = sections
    # 深拷贝 blocks
    for sec in doc["sections"]:
        if isinstance(sec, dict):
            sec["blocks"] = [
                dict(b) if isinstance(b, dict) else b
                for b in (sec.get("blocks") or [])
            ]

    fixed: list[str] = []
    hard: list[str] = []

    # 1) 占位符
    for path, val in list(_iter_doc_strings(doc)):
        new_val, issues = _fix_placeholder_text(val)
        if issues:
            fixed.extend(issues)
            _set_doc_string(doc, path, new_val)

    # 2) 辅导内容泄漏（再扫一遍）
    doc, removed = _strip_coaching_from_document(doc)
    for r in removed:
        fixed.append(f"剔除辅导块「{r}」")

    # 3) 空 bullet / 纯占位 bullet
    for path, val in list(_iter_doc_strings(doc)):
        if ".bullets[" not in path:
            continue
        s = val.strip()
        if not s:
            hard.append(f"空要点 {path}")
        elif s.startswith("[量化待补") and len(s) < 40 and s.endswith("]"):
            hard.append(f"要点几乎只有占位 {path}")
        # 「覆盖[量化待补：…]的…」修复后若仍别扭，留给 LLM

    # 4) 密度
    dens = _density_report(doc)
    if not dens["ok"]:
        hard.extend([f"密度:{x}" for x in dens["reasons"]])

    return doc, fixed, hard


def _llm_review_document(doc: dict, original_text: str, role: dict) -> dict:
    """
    LLM 审核官：找残留问题并给出可落盘修正版 document。

    返回 {pass, issues, document, chat_notes}。
    """
    doc_json = json.dumps(doc, ensure_ascii=False)[:12000]
    prompt = f"""你是简历终稿审核官（投递前质检）。对照学员原文，审查下列结构化简历。

目标方向：{role.get('title')}（{role.get('role_id')}）

硬性不合格（任一即 pass=false，并在 document 中修好）：
1. 畸形量化占位：如「[量化待补：%]」「[量化待补：]」「[量化待补：数字]」——必须改成有中文含义的占位，如「[量化待补：覆盖的图元类型或数量]」，或删掉生硬嵌入、改成通顺表述
2. 把「简历优化/面试准备/跳槽/谈薪/职业规划/课程实战辅导」写成项目或技能
3. 编造原文没有的具体数字（百分比、倍数、ms 等）
4. 句子不通：如「覆盖[量化待补：…]的常见图元」——改为通顺中文
5. fact 模式改动了真实公司/年限/title

可放行：合理的「[量化待补：延迟从多少到多少]」这类带说明的占位。

返回纯 JSON：
{{
  "pass": true或false,
  "issues": ["问题简述..."],
  "document": {{ ...完整修正后的 ResumeDocument... }},
  "chat_notes": ["可在聊天提醒学员补充的点..."]
}}

学员原文（节选）：
{(original_text or '')[:3500]}

待审终稿 JSON：
{doc_json}
"""
    try:
        llm = _get_llm(temperature=0.1)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        result = _extract_json(content)
        out_doc = result.get("document")
        if not isinstance(out_doc, dict):
            out_doc = doc
        else:
            out_doc = _normalize_doc(out_doc, str(doc.get("mode") or "fact"))
            out_doc, _ = _strip_coaching_from_document(out_doc)
            out_doc, _, _ = _rule_audit_and_fix(out_doc)
        return {
            "pass": bool(result.get("pass")),
            "issues": result.get("issues") or [],
            "document": out_doc,
            "chat_notes": result.get("chat_notes") or [],
        }
    except Exception as e:
        logger.warning("LLM 审核失败: %s", e)
        return {
            "pass": False,
            "issues": [f"审核调用失败: {e}"],
            "document": doc,
            "chat_notes": [],
        }


def _has_malformed_placeholder(doc: dict) -> list[str]:
    """扫描仍不合格的量化占位。"""
    bad: list[str] = []
    for path, val in _iter_doc_strings(doc):
        for m in _PLACEHOLDER_RE.finditer(val or ""):
            inner = (m.group(1) or "").strip()
            if (
                not inner
                or not _PLACEHOLDER_GOOD_HINT.search(inner)
                or re.fullmatch(r"[%\d.\s\-×xX/~]+", inner)
            ):
                bad.append(f"{path}: {m.group(0)}")
    return bad


def review_and_gate_document(
    doc: dict,
    original_text: str,
    role: dict,
) -> dict:
    """
    审核关：规则修复 → LLM 质检 → 再规则扫一遍。

    返回 {ok, document, review_issues, fixed_issues, chat_notes, review_pass}
    """
    doc1, fixed, hard = _rule_audit_and_fix(doc)
    llm_res = _llm_review_document(doc1, original_text, role)
    doc2 = llm_res.get("document") or doc1
    doc3, fixed2, hard2 = _rule_audit_and_fix(doc2)
    dens = _density_report(doc3)
    malformed = _has_malformed_placeholder(doc3)

    issues: list[str] = []
    issues.extend(hard)
    issues.extend(llm_res.get("issues") or [])
    issues.extend(hard2)
    if not dens["ok"]:
        issues.extend([f"密度:{x}" for x in dens["reasons"]])
    for m in malformed:
        issues.append(f"仍残留畸形占位「{m}」")

    # 放行条件：密度 OK + 无畸形占位 +（LLM pass 或 仅有已自动修复项）
    review_pass = dens["ok"] and not malformed
    if review_pass and llm_res.get("pass") is False:
        # LLM 明确不通过时，若硬伤只剩「空要点」等也拦
        blocking = [
            x for x in (llm_res.get("issues") or [])
            if any(k in x for k in ("编造", "辅导", "公司", "title", "不通", "畸形"))
        ]
        if blocking:
            review_pass = False
            issues.extend(blocking)

    return {
        "ok": review_pass,
        "document": doc3,
        "review_pass": review_pass,
        "fixed_issues": (fixed + fixed2)[:12],
        "review_issues": issues[:12],
        "chat_notes": llm_res.get("chat_notes") or [],
    }


@tool
def review_resume_document(document_json: str, original_text: str = "", role_id: str = "") -> dict:
    """
    简历终稿审核官：检查畸形占位、辅导内容误入、编造数字、不通顺句。

    optimize 主路径会自动调用；也可对已有 JSON 复审。
    返回 {ok, document, review_issues, fixed_issues, chat_notes}。
    """
    data = _safe_json_loads(document_json)
    if not data:
        return {"ok": False, "error": "document_json 无效"}
    role = _load_role(role_id or str(data.get("role_id") or ""))
    mode = str(data.get("mode") or "fact")
    doc = _normalize_doc(data, mode)
    gate = review_and_gate_document(doc, original_text, role)
    return {
        "ok": gate["ok"],
        "review_pass": gate["review_pass"],
        "document": gate["document"],
        "fixed_issues": gate["fixed_issues"],
        "review_issues": gate["review_issues"],
        "chat_notes": gate["chat_notes"],
    }


def _strip_coaching_from_document(doc: dict) -> tuple[dict, list[str]]:
    """
    从终稿剔除误写入的「课练面/求职辅导」块。

    返回 (清洗后文档, 被剔除块的摘要，可并入聊天 practice_topics)。
    """
    removed: list[str] = []
    sections_out: list[dict] = []
    for sec in doc.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        blocks_out: list[dict] = []
        for block in sec.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            blob = _block_blob(block)
            if _COACHING_LEAK_RE.search(blob):
                title = block.get("title") or block.get("company") or sec.get("heading") or "辅导内容"
                removed.append(str(title)[:80])
                continue
            # 清洗 skills_line / bullets 内夹带的辅导词条
            skills = str(block.get("skills_line") or "")
            if skills and _COACHING_LEAK_RE.search(skills):
                # 软技能串整段丢掉
                if all(
                    tok.strip() in _SOFT_SKILL_KEYWORDS or _COACHING_LEAK_RE.search(tok)
                    for tok in re.split(r"[/、,，|]", skills)
                    if tok.strip()
                ):
                    block = dict(block)
                    block["skills_line"] = ""
            clean_bullets = []
            for b in block.get("bullets") or []:
                if b and not _COACHING_LEAK_RE.search(str(b)):
                    clean_bullets.append(b)
                elif b:
                    removed.append(str(b)[:60])
            block = dict(block)
            block["bullets"] = clean_bullets
            if block.get("skills_line") or block.get("bullets") or block.get("company"):
                blocks_out.append(block)
        if blocks_out or (sec.get("heading") and sec.get("type") == "education"):
            sec2 = dict(sec)
            sec2["blocks"] = blocks_out
            sections_out.append(sec2)
    out = dict(doc)
    out["sections"] = sections_out
    return out, removed


def _optimize_once(
    text: str,
    role: dict,
    mode: str,
    brief: dict,
    research: dict,
    reinforce_note: str = "",
) -> dict:
    """调用 LLM 生成完整 ResumeDocument + 下游信号。"""
    raw_emphasize = research.get("emphasize_checklist") or brief.get("keep_themes") or role["required_skills"]
    raw_gaps = brief.get("gaps") or []
    # 软技能方向 / 辅导关键词：只进聊天种子，不进简历写透清单
    coaching_for_chat = [
        str(x) for x in (raw_gaps + list(role.get("required_skills") or []))
        if str(x) in _SOFT_SKILL_KEYWORDS or _COACHING_LEAK_RE.search(str(x))
    ]
    if _is_soft_skill_role(role.get("role_id") or ""):
        emphasize = _filter_tech_themes(research.get("emphasize_checklist") or [])
        # 软技能岗：简历仍按原文技术经历写，辅导类 gaps 全部进聊天
        tech_skills_note = "（当前 role 为求职软技能课方向：简历正文只写学员真实技术/项目经历，勿写课程辅导项）"
        skill_list_for_body = []
    else:
        emphasize = _filter_tech_themes(raw_emphasize)
        tech_skills_note = ""
        skill_list_for_body = _filter_tech_themes(role["required_skills"])
    deprior = research.get("deprioritize_hints") or brief.get("compress_themes") or []
    gaps_for_chat = _filter_tech_themes(raw_gaps) if not _is_soft_skill_role(role.get("role_id") or "") else []
    gaps_for_chat = list(dict.fromkeys(gaps_for_chat + coaching_for_chat))

    prompt = f"""你是资深中文技术岗简历写手。根据原文生成**完整一页可投递终稿**的结构化 JSON（不是 2～4 句示例）。

模式：{mode}  （fact=真实经历定向呈现；target=目标蓝图，禁止假公司/假在职）
目标方向：{role['title']}（{role['role_id']}）
{tech_skills_note}
应写透（技术主题）：{emphasize}
应压缩：{deprior}
站内技术关键词参考：{skill_list_for_body}
{('补强要求：' + reinforce_note) if reinforce_note else ''}

【聊天 vs 简历 — 最高优先级】
- document.sections 只能写：求职意向、联系方式、技能、真实工作/项目、教育
- **禁止**把下列内容写入 document 任何 section/bullet：
  简历优化过程、技术面试准备、跳槽策略、谈薪晋升、职业规划、课程推荐、
  「程序员职业跃迁综合实践」、学习闭环、训练题、投递计划、如何兑现课练面
- 上述辅导内容只能出现在 practice_topics / interview_focus / open_questions（给聊天用）
- JobMatch 的软技能缺口（简历优化/面试/跳槽等）≠ 项目经历，绝不能编成「课程实战项目」塞进简历

写法硬标准：
1. 每条经历/项目：先有一句话上下文（系统定位+服务谁+解决什么），再 3～5 条 bullet
2. bullet = 动作动词 + 交付产物 + 方法/工具 + 可验证结果；缺量化写「[量化待补：…]」勿编假数
3. fact：保留真实公司/年限/真实 title；相关写透，弱相关压 1 行；项目必须来自原文已有经历
4. target：仅可写「完成后可写进简历」的**技术**课内项目骨架，仍禁止假雇主；禁止把求职辅导课写成项目
5. 必含：intention、技能分层、经历或项目、教育（有则写）
6. 全文 bullets 总数 ≥ {_MIN_BULLETS}
7. 仅使用原文已确认事实；网络/站内信号只调侧重点
8. 原文没有的百分比/毫秒/人数等数字一律写成「[量化待补：…]」，严禁编造具体数字

同时给出下游信号（仅聊天，不进 document）：
- practice_topics：可含求职辅导/课练主题，3～5 条
- interview_focus：终稿技术高光深挖，3～5 条
- open_questions：2～5 条
- profile_patch：高置信画像字段

返回纯 JSON：
{{
  "document": {{
    "mode": "{mode}",
    "role_id": "{role['role_id']}",
    "role_title": "{role['title']}",
    "title": "姓名或学员_方向",
    "contact": {{"name": "", "phone": "", "email": "", "city": ""}},
    "intention": "求职意向一行",
    "sections": [
      {{"type": "summary|skills|experience|projects|education", "heading": "...",
        "blocks": [{{"company": "", "title": "", "period": "", "skills_line": "",
          "bullets": ["上下文或要点...", "..."]}}]}}
    ],
    "footer_note": ""
  }},
  "practice_topics": ["..."],
  "interview_focus": ["..."],
  "open_questions": ["..."],
  "profile_patch": {{}}
}}

简历原文：
{text}"""

    llm = _get_llm(temperature=0.35)
    response = llm.invoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)
    result = _extract_json(content)
    doc = result.get("document") if isinstance(result.get("document"), dict) else result
    if not isinstance(doc, dict):
        raise ValueError("optimize 未返回 document 对象")
    doc = _normalize_doc(doc, mode)
    doc.setdefault("role_id", role["role_id"])
    doc.setdefault("role_title", role["title"])
    doc, removed = _strip_coaching_from_document(doc)
    practice = list(result.get("practice_topics") or [])
    for r in removed:
        practice.append(f"（已从简历剔除，改在对话跟进）{r}")
    for g in gaps_for_chat:
        if g not in practice:
            practice.append(str(g))
    return {
        "document": doc,
        "practice_topics": practice[:8],
        "interview_focus": result.get("interview_focus") or [],
        "open_questions": result.get("open_questions") or [],
        "profile_patch": result.get("profile_patch") if isinstance(result.get("profile_patch"), dict) else {},
        "stripped_coaching_blocks": removed,
    }


@tool
def optimize_resume_document(
    text: str,
    role_id: str,
    mode: str = "fact",
    student_id: int = 0,
    direct_brief_json: str = "",
    research_json: str = "",
) -> dict:
    """
    【主路径】将简历优化为完整一页结构化终稿并保存 artifact。

    有优化结果时优先调用本工具（不要手拼瘦 JSON 给 compose）。
    返回 artifact_id + practice_topics + interview_focus（供训练题/面试）。
    """
    if not text or not text.strip():
        return {"ok": False, "error": "简历正文为空"}

    mode = (mode or "fact").lower().strip()
    if mode not in ("fact", "target"):
        mode = "fact"

    role = _load_role(role_id)
    brief = _safe_json_loads(direct_brief_json) or {}
    research = _safe_json_loads(research_json) or {}

    if not brief:
        brief = build_resume_direct_brief.invoke({
            "role_id": role_id,
            "student_id": int(student_id or 0),
            "resume_text": text[:4000],
        })

    try:
        packed = _optimize_once(text, role, mode, brief, research)
    except Exception as e:
        logger.exception("optimize_resume_document 失败")
        return {"ok": False, "error": f"优化失败: {e}"}

    report = _density_report(packed["document"])
    if not report["ok"]:
        try:
            packed = _optimize_once(
                text,
                role,
                mode,
                brief,
                research,
                reinforce_note=(
                    f"上一版过瘦（{'; '.join(report['reasons'])}）。"
                    f"必须补满：每段经历/项目≥{_MIN_BULLETS_PER_BLOCK}条bullet，"
                    f"全文≥{_MIN_BULLETS}条，含意向与技能分层。"
                ),
            )
            report = _density_report(packed["document"])
        except Exception as e:
            logger.warning("补强失败: %s", e)

    if not report["ok"]:
        return {
            "ok": False,
            "error": "密度门禁未通过",
            "thin_reason": report["reasons"],
            "bullets": report["bullets"],
            "document_preview": packed["document"],
            "practice_topics": packed.get("practice_topics") or [],
            "interview_focus": packed.get("interview_focus") or [],
            "open_questions": packed.get("open_questions") or [],
        }

    # ── 审核关（规则 + LLM 质检）──
    gate = review_and_gate_document(packed["document"], text, role)
    packed["document"] = gate["document"]
    if not gate["ok"]:
        try:
            packed = _optimize_once(
                text,
                role,
                mode,
                brief,
                research,
                reinforce_note=(
                    "审核未通过，请重写终稿并修复："
                    + "；".join((gate.get("review_issues") or [])[:6])
                    + "。禁止畸形占位如[量化待补：%]；辅导内容勿进项目；句子必须通顺。"
                ),
            )
            gate = review_and_gate_document(packed["document"], text, role)
            packed["document"] = gate["document"]
        except Exception as e:
            logger.warning("审核后重写失败: %s", e)

    if not gate["ok"]:
        return {
            "ok": False,
            "error": "审核关未通过，未生成可下载终稿",
            "review_issues": gate.get("review_issues") or [],
            "fixed_issues": gate.get("fixed_issues") or [],
            "document_preview": packed["document"],
            "practice_topics": packed.get("practice_topics") or [],
            "interview_focus": packed.get("interview_focus") or [],
            "open_questions": (packed.get("open_questions") or [])
            + list(gate.get("chat_notes") or []),
            "bullets": _count_bullets(packed["document"]),
        }

    meta = _save_doc(packed["document"])
    report = _density_report(packed["document"])

    # 可选：同步画像
    profile_sync = {}
    patch = packed.get("profile_patch") or {}
    if student_id and patch:
        try:
            from src.tools.shared_tools import update_student_profile

            kwargs = {"student_id": int(student_id)}
            for key in (
                "display_name", "company", "job_title", "years_of_experience",
                "major", "university", "target_role", "persona", "skill_level",
            ):
                if key == "display_name" and patch.get("name"):
                    kwargs["display_name"] = patch["name"]
                elif patch.get(key) is not None and patch.get(key) != "":
                    kwargs[key] = patch[key]
            if len(kwargs) > 1:
                if "target_role" not in kwargs:
                    kwargs["target_role"] = role["title"]
                profile_sync = update_student_profile.invoke(kwargs)
        except Exception as e:
            profile_sync = {"error": str(e)}

    open_q = list(packed.get("open_questions") or [])
    for note in gate.get("chat_notes") or []:
        if note and note not in open_q:
            open_q.append(note)

    return {
        **meta,
        "bullets": report["bullets"],
        "practice_topics": (packed.get("practice_topics") or [])[:5],
        "interview_focus": (packed.get("interview_focus") or [])[:5],
        "open_questions": open_q[:6],
        "review_pass": True,
        "fixed_issues": gate.get("fixed_issues") or [],
        "direct_brief_summary": {
            "role_id": brief.get("role_id") or role_id,
            "keep_themes": brief.get("keep_themes") or [],
            "gaps": brief.get("gaps") or [],
        },
        "research_note": research.get("sources_note") or "",
        "profile_sync": profile_sync,
    }


# ── 终稿落库（次路径）────────────────────────────────

@tool
def compose_resume_document(document_json: str) -> dict:
    """
    将已有完整 ResumeDocument JSON 落库为 artifact。

    优先使用 optimize_resume_document；仅当已有合格完整 JSON 时用本工具。
    禁止用手拼 2～4 条示例冒充整份简历。
    """
    raw = (document_json or "").strip()
    if not raw:
        return {"ok": False, "error": "document_json 为空"}

    data = _safe_json_loads(raw)
    if not data:
        return {"ok": False, "error": "JSON 解析失败"}

    mode = str(data.get("mode") or "fact").lower().strip()
    payload = _normalize_doc(data, mode)
    report = _density_report(payload)
    if not report["ok"]:
        return {
            "ok": False,
            "error": "密度不足，请改用 optimize_resume_document",
            "thin_reason": report["reasons"],
            "bullets": report["bullets"],
        }
    return _save_doc(payload)


def extract_resume_artifact_from_messages(messages: list) -> dict[str, Any]:
    """
    从本轮 Agent messages 抽取 optimize/compose 的 artifact。

    返回 {artifact_id, mode, title}；无则空字符串字段。
    """
    empty = {"artifact_id": "", "mode": "", "title": ""}
    if not messages:
        return empty

    last: dict[str, Any] | None = None
    for msg in messages:
        name = getattr(msg, "name", None) or ""
        content = getattr(msg, "content", None)
        parsed: Any = None
        if isinstance(content, dict):
            parsed = content
        elif isinstance(content, str) and content.strip():
            text = content.strip()
            if text.startswith("{") or "artifact_id" in text:
                parsed = _safe_json_loads(text)
        if not isinstance(parsed, dict):
            continue
        if parsed.get("artifact_id") and (
            name in ("compose_resume_document", "optimize_resume_document")
            or parsed.get("ok") is True
            or "preview_path" in parsed
        ):
            last = parsed

    if not last:
        return empty
    return {
        "artifact_id": str(last.get("artifact_id") or ""),
        "mode": str(last.get("mode") or ""),
        "title": str(last.get("title") or ""),
    }
