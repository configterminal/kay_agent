# 课程目录同步与画像推荐

> 状态：**Phase 1 已落地** | 最后更新：2026-07-16  
> 关联：[数据库](database.md) · [RecommendAgent](agents/recommend.md) · [推荐工具](tools/recommend.md) · [RAG 索引](rag/indexer.md)

## 1. 问题与目标

### 1.1 落地现状（2026-07-16）

| 能力 | 设计位置 | 实际状态 |
|------|----------|----------|
| 课程内容检索（答疑） | Milvus `course_content` | ✅ 已索引（优先 `.knowledge.json` 知识点；无则规则窗） |
| 课程目录（推荐选课） | SQLite `course_modules` | ✅ `sync_course_catalog()` 启动同步（现网约 2 课 + 章行） |
| 学员画像持久化 | `students` + `update_student_profile` | ✅ QA/Recommend 可写；字段随对话填充（未填则为 null） |
| 课程作用域 / 类比 | Soft/Hard + `analogy_citations` | ✅ 见 [course-scope](rag/course-scope.md) |
| 岗位 ↔ 课程映射 | `job_roles` + `skill_mapping` | ✅ `sync_job_catalog()` + `resources/job_roles/`（课程模板 MVP；见 [jobmatch](agents/jobmatch.md)） |

### 1.2 目标（回顾）

1. **课程目录索引**：从 `resources/courses/` 自动同步到 `course_modules`（与向量库解耦、可重复执行）。
2. **画像写入**：学员在对话中透露的身份、水平、目标等，结构化写入 `students`。
3. **可解释匹配**：基于画像 + 进度 + 目录元数据推荐**课程**与**章节**，理由可追踪。

---

## 2. 两套索引的分工

```
resources/courses/
├── RAG101 …/index.json          ──► course_modules（course 级行）
├── RAG101 …/02 …/module.json    ──► course_modules（chapter 级行）
└── …/02-03 xxx.md (+ .knowledge.json) ──► Milvus（知识点子块 / fallback 规则窗）

学员问「RAG 是什么」     → QAAgent + Milvus 检索（可带 course_id 作用域）
学员问「我该学什么课」   → RecommendAgent + course_modules 匹配
```

| 索引 | 粒度 | 存储 | 更新方式 |
|------|------|------|----------|
| **目录索引** | 课程 / 章 | SQLite `course_modules` | 启动时 `sync_course_catalog()` upsert |
| **内容索引** | 知识点 / cue 块 | Milvus | `build_index()`：新节增量；改旧节需 `force=True` 或按课重建 |

目录索引**不做 Embedding**；匹配用规则 + 可选 LLM 排序（`get_next_recommendations`）。

---

## 3. 课程目录同步

### 3.1 数据源规范

**课程级** — `resources/courses/{dir}/index.json`（已有，扩展可选字段）：

```json
{
  "course_id": "CAREER201",
  "title": "12年程序员职业跃迁技术与技巧",
  "full_title": "…",
  "industry": "IT",
  "persona_target": "working_professional",
  "difficulty": "beginner",
  "tags": ["职业跃迁", "跳槽", "面试", "晋升", "谈薪"],
  "description": "面向在职程序员的职业发展与求职实战"
}
```

| 字段 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `course_id` | ✅ | — | 与目录名前缀一致（见 indexer 正则） |
| `title` | ✅ | — | 短标题 |
| `industry` | ✅ | `IT` | 行业过滤 |
| `persona_target` | 否 | `all` | `university_student` / `working_professional` / `all` |
| `difficulty` | 否 | `beginner` | 与学员 `skill_level` 比较 |
| `tags` | 否 | `[]` | 目标/话题匹配 |
| `description` | 否 | `full_title` 或 `title` | 推荐展示与 LLM 排序 |

**章级** — `{章目录}/module.json`（已有）：

```json
{
  "module_id": "RAG101-ch02",
  "chapter": "02",
  "title": "掌握未来AI趋势：…",
  "difficulty": "beginner",
  "tags": []
}
```

章级 `module_id` 建议保持 `{course_id}-ch{NN}`，便于解析所属课程。

### 3.2 同步算法 `sync_course_catalog()`

模块：`src/db/catalog_sync.py`（已完成）

```
扫描 resources/courses/
  对每个课目录：
    ① 校验目录名 ↔ index.json course_id（同 indexer 规则）
    ② upsert course 级行：module_id = course_id
    ③ 扫描章目录 module.json → upsert chapter 级行
    ④ 统计 lesson_count = 该章下合规 *.md 数量
    ⑤ 推断 prerequisites（首版见下）
  提交事务；返回 {courses, chapters, updated}
```

**首版前置关系（自动推断，不写死课程名）**：

| 层级 | 规则 |
|------|------|
| course 级 | `prerequisites = []` |
| chapter 级 | 同课 `chapter-1` 为前置（ch02 → ch01，ch01 无前置） |

**`course_modules` 行映射**：

| DB 字段 | course 级来源 | chapter 级来源 |
|---------|---------------|----------------|
| `module_id` | `course_id` | `module.json.module_id` |
| `title` | `index.title` | `module.json.title` |
| `description` | `index.description` | 章标题或空 |
| `industry` | `index.industry` | 继承课程 |
| `difficulty` | `index.difficulty` | `module.json.difficulty` |
| `prerequisites` | `[]` | 上一章 `module_id` |
| `estimated_hours` | 章 `lesson_count` 之和 × 系数（或 null） | `lesson_count × 0.5h` 估算 |
| `lesson_count` | 全课 md 数 | 该章 md 数 |
| `persona_target` | `index.persona_target` | 继承课程 |

**扩展字段（首版用 JSON 或后续 migration）**：

在 `course_modules` 增加 `course_id`（VARCHAR）、`level`（`course` | `chapter`）、`tags`（JSON），便于查询「只推荐课程」或「推荐下一章」。若暂不迁表，可用约定：`module_id == course_id` 表示课程级。

### 3.3 触发时机

| 时机 | 行为 |
|------|------|
| 应用 `lifespan` | `sync_course_catalog()`（幂等 upsert，轻量） |
| 运维命令 | `python -m src.db.catalog_sync` 或 `build_index` 前可选 `--sync-catalog` |
| 课程资源变更后 | 开发者手动执行同步 |

不与 Milvus `build_index` 强绑定——目录同步无 Embedding，耗时可忽略。

---

## 4. 学员画像持久化

### 4.1 写入时机

```
学员消息（含自叙画像）
    ↓
Supervisor → recommend_agent（或 progress / 首次 onboarding）
    ↓
RecommendAgent 工具链：
  ① get_student_profile(student_id)     读现状
  ② update_student_profile(...)         合并写入（对话中提取的字段）
  ③ get_next_recommendations(...)       基于更新后画像推荐
```

**原则**：画像以 **SQLite `students` 为权威**；Redis MemoryStore 可存 `profile_notes` 补充自由文本（Phase 2）。

### 4.2 工具 `update_student_profile`（已完成）

位置：`src/tools/shared_tools.py`

```python
@tool
def update_student_profile(
    student_id: int,
    persona: str | None = None,              # university_student | working_professional
    skill_level: str | None = None,          # beginner | intermediate | advanced
    target_role: str | None = None,          # 如「AI应用开发」「后端工程师」
    display_name: str | None = None,
    major: str | None = None,
    university: str | None = None,
    company: str | None = None,
    job_title: str | None = None,
    years_of_experience: int | None = None,
    enrolled_modules: list[str] | None = None,  # 追加模式见实现
) -> dict:
    """部分更新；仅非 None 字段覆盖。返回更新后 profile 摘要。"""
```

| 规则 | 说明 |
|------|------|
| 部分更新 | 只改传入字段，禁止整行覆盖丢数据 |
| `enrolled_modules` | 追加去重，不删除历史 |
| 校验 | persona / skill_level 枚举校验，非法值拒绝 |
| 权限 | 仅 Agent 工具调用，不对前端裸开全字段 API（首版） |

### 4.3 Prompt 约束（RecommendAgent）

在 `RECOMMEND_ROLE_PROMPT` 增加：

- 学员首次描述背景或目标时，**必须先** `update_student_profile` 再推荐。
- 推荐前**必须** `get_student_profile`；禁止仅凭对话记忆推荐。
- 信息不足时先追问 1～2 个关键字段（在校生/在职、目标方向），再写入。

### 4.4 可选：画像抽取（Phase 2）

Probe 后增加轻量规则/LLM 抽取节点，自动填充 `update_student_profile`——首版不实现，避免与 Recommend 职责重叠。

---

## 5. 推荐匹配逻辑

### 5.1 总流程

```
get_next_recommendations(student_id, count=5)
    │
    ├─ 读 students + learning_progress + quiz_attempts
    ├─ 读 course_modules（依赖 catalog_sync）
    ├─ 过滤：未完成、难度适配、persona_target 兼容
    ├─ 打分排序（见 5.2）
    ├─ 分轨：course 级 1～2 条 + chapter 级若干
    └─ LLM 润色 reason（候选 > count 时）
```

### 5.2 打分因子（首版可实现）

| 因子 | 权重 | 说明 |
|------|------|------|
| `persona_target` 匹配 | 高 | 在职学员 ↑ CAREER201；`all` 通吃 |
| `tags` / `title` 与 `target_role` 关键词 | 高 | 如 target 含「RAG/AI」↑ RAG101 |
| 前置已满足 | 高 | 可立即学 |
| 薄弱点命中章标题/标签 | 中 | 现有 weak_areas 逻辑 |
| 已 `enrolled` 同课程 | 中 | 优先推荐已选课的下一章 |
| 难度适配 | 门槛 | `difficulty <= skill_level` |

**课程级 vs 章级展示策略**：

- 学员**未选课** / `enrolled_modules` 空：优先返回 **course 级** 1～2 门（如职业跃迁 vs RAG 全栈）。
- 已选某课：优先返回该课 **下一章** `module_id`（前置满足的第一章）。

### 5.3 `source` 字段语义（保持兼容）

| source | 含义 |
|--------|------|
| `career_path` | 与 target_role / persona 路线一致 |
| `weak_area` | 补强薄弱点 |
| `self_pick_extension` | 已选课后的自然续学 |
| `skill_gap` | Phase 2：`skill_mapping` 启用后 |

### 5.4 与向量检索的关系

- 推荐**不调用** Milvus（避免与 QA 抢资源、语义重复）。
- 例外（Phase 2）：学员目标描述很泛时，用 **course 级 tags + 短 query** 对目录做轻量语义匹配——首版用关键词即可。

---

## 6. 端到端时序

```
学员：「我是在职后端，想转 AI 应用开发，该学什么？」
    │
    ▼
Supervisor.decide → recommend_agent
    │
    ▼
RecommendAgent
    ├─ get_student_profile(1)
    ├─ update_student_profile(1, persona=working_professional,
    │       target_role="AI应用开发", skill_level=intermediate)
    ├─ get_next_recommendations(1, count=3)
    │     └─ course_modules 命中 RAG101（tags/目标匹配）
    │     └─ 若已 enrolled RAG101 → 推荐 RAG101-ch03
    └─ 自然语言回复 + 理由
```

---

## 7. 实现顺序

| Phase | 内容 | 产出 |
|-------|------|------|
| **P1** | `sync_course_catalog()` + lifespan 调用 | `course_modules` 有数据 |
| **P1** | 扩展 `index.json` 可选字段（CAREER201/101） | persona_target、tags |
| **P1** | `update_student_profile` 工具 + Recommend prompt | 画像可写入 |
| **P1** | 增强 `get_next_recommendations`（course/chapter 分轨 + tags） | 推荐可测 |
| P2 | `job_roles` + `skill_mapping` 导入 | 岗位差距推荐 |
| P2 | 前端 onboarding 表单写 `students` | 减少纯对话抽取 |
| P2 | 目录语义匹配（可选 Embedding） | 泛目标描述 |

---

## 8. 相关文件

| 文件 | 职责 |
|------|------|
| `src/db/catalog_sync.py` | ✅ 扫描 resources → upsert course_modules |
| `src/tools/shared_tools.py` | ✅ `update_student_profile` |
| `src/tools/recommend_tools.py` | ✅ 增强匹配与分轨 |
| `src/agents/prompts/recommend.py` | ✅ 画像写入与推荐流程 |
| `src/main.py` lifespan | ✅ 启动时 `sync_course_catalog()` |
| `resources/courses/*/index.json` | 补充 persona_target、tags、description |

---

## 9. 验收标准

1. 执行同步后 `SELECT count(*) FROM course_modules` ≥ 2 门课程 + 全部章行。
2. 对话：「我是应届生，想学 AI」→ 写入 `persona=university_student`，推荐含 RAG101 且带 `reason`。
3. 对话：「在职想跳槽」→ 推荐含 CAREER201，且非「功能开发中」占位。
4. 已 `enrolled_modules=['RAG101']` 且完成 ch01 → 推荐 RAG101-ch02。
5. 同步与索引均**不硬编码**课程名，只读 `resources/`。

答疑作用域与类比分区见 [rag/course-scope.md](rag/course-scope.md)。
