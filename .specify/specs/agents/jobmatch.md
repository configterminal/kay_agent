# JobMatchAgent — 岗位/课程覆盖匹配

> 状态：**课程匹配 MVP 已落地并验收** | 最后更新：2026-07-16  
> 工具：[jobmatch.md](../tools/jobmatch.md) · 数据种子：`resources/job_roles/` · 同步：`sync_job_catalog()`  
> 验收：目标 RAG 方向差距 → `jobmatch_agent`；「面试要注意什么」→ 仍 `qa_agent`

## 1. 定位

| 形态 | 说明 |
|------|------|
| **本阶段（MVP）** | **已有课程覆盖匹配**：岗位模板包装「站内能教什么」，对照 `learning_progress` 算差距并推荐补课 |
| **目标态（未做）** | 按真实招聘市场 JD / 技能需求匹配（需可靠数据源）；见下文「升级预留」 |

**禁止伪称**：回复不得声称「最新招聘行情 / 实时市场」；须说明基于站内课程能力模型。

## 2. 架构

```
┌─────────────────────────────────────────────────────────────┐
│                   JobMatchAgent                              │
├─────────────────────────────────────────────────────────────┤
│  System Prompt（多层组装）                                    │
│  L2-L5 shared + L6 coach + L7 emotion + L1 jobmatch.py      │
│                                                             │
│  工具：get_student_profile, update_student_profile,         │
│        get_job_roles, analyze_skill_gap                     │
│        （不含 get_industry_trends — 避免静态假趋势）          │
│                                                             │
│  实现：create_react_agent；首版自然语言输出                   │
└─────────────────────────────────────────────────────────────┘
```

```
学员 → Supervisor → JobMatchAgent
         │
         ├── get_job_roles(industry)     → job_roles（课程模板）
         └── analyze_skill_gap(...)      → skill_mapping + learning_progress
```

## 3. 与 QA / Recommend 边界

| 意图 | 路由 |
|------|------|
| 课程里的面试/求职/RAG **知识** | `qa_agent` |
| 「我该学哪门课」路径推荐 | `recommend_agent` |
| 「我离某方向还差什么 / 岗位技能差距」 | `jobmatch_agent` |

## 4. 数据

- 种子：`resources/job_roles/IT/roles.json`（含 `skill_mappings`）
- 启动：`sync_job_catalog()`（见 [catalog_sync](../../src/db/catalog_sync.py) 旁岗位同步）
- 首版 2 岗：`rag_ai_engineer`↔RAG101，`career_transition_engineer`↔CAREER201

## 5. 升级预留（有数据源后再做）

1. 可插拔 **MarketSkillProvider**（`static_seed` 当前 / 后续招聘 API）
2. `analyze_skill_gap` 增加 `source=course|market`
3. 外部 JD 与 `resources/job_roles` 课程模板分离存储

## 6. Schema

见 [schemas.md](schemas.md) `SkillGapResult`（首版不强制 structured output）。
