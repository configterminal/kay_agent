# ResumeAgent 工具

> 设计：[agents/resume.md](../agents/resume.md) — 证据驱动加强版。

## Agent 挂载

```
get_student_profile / update_student_profile / get_job_roles

parse_resume(text)
  → 事实底稿：contact, experience_blocks, project_blocks, skills, persona_hint, …

sync_resume_profile(student_id, parse_json)
  → 高置信字段写入画像

build_resume_direct_brief(role_id, student_id, resume_text)
  → JobMatch 定向：must_keywords, mastered, gaps, keep_themes, compress_themes
  → source=course（站内能力模型）

research_target_role_signals(target_role, role_id?)
  → 公开网络侧重点：emphasize_checklist, deprioritize_hints
  → 失败降级为站内关键词；sources_note 诚实标注

get_resume_feedback(text, role_id, direct_brief_json?, research_json?)
  → ats_score（站内方向分）, coverage_matrix, value_extract, red_flags, rewrite_examples
  → rewrite_examples 仅供聊天，不能当整份 PDF

optimize_resume_document(text, role_id, mode, student_id?, …)   # 主路径
  → artifact_id + practice_topics + interview_focus + open_questions
  → 密度门禁 → **审核关**（规则修畸形占位 + LLM 质检；不通过则重写或 ok:false）
  → 辅导内容禁止进 PDF sections

review_resume_document(document_json, original_text?, role_id?)
  → 独立复审；修 [量化待补：%] 类畸形占位、不通顺句、辅导泄漏

compose_resume_document(document_json)   # 次路径：已有合格完整 JSON
```

## 数据与边界

- `role_id` ← `job_roles`（`sync_job_catalog`）
- 网络检索用 ddgs；仅调篇幅焦点，不写入虚构经历
- MVP 不落库完整简历正文；artifact 进程内存 LRU
