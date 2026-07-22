# JobMatchAgent 工具

> MVP：课程覆盖匹配。`get_industry_trends` 保留实现但**不挂到 Agent**。

## 工具（Agent 挂载）

```
get_job_roles(industry: str) → list[dict]
    查询行业下的课程对齐岗位模板
    industry 别名归一：人工智能/互联网/IT → "IT"
    [{role_id, title, required_skills, preferred_skills, salary_range, description}]

analyze_skill_gap(student_id, role_id) → dict
    对照 learning_progress(completed) 与 skill_mapping
    {match_pct, mastered, gaps: [{skill, recommended_module}]}
```

## 未挂载（后续）

```
get_industry_trends(industry: str) → str
    MVP 静态文案；无可靠数据源前禁止对学员宣称「市场趋势」
```

## 数据来源

| 表 / 文件 | 用途 |
|-----------|------|
| `resources/job_roles/{industry}/roles.json` | 岗位模板 + skill_mappings |
| `job_roles` / `skill_mapping` | 启动 `sync_job_catalog()` upsert |
| `learning_progress` | 已完成 module_id → mastered |

空表时 `get_job_roles` 返回 `[]`；Agent Prompt 引导学员说明目标方向或先选课。
