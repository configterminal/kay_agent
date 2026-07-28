# 数据库 (src/db/)

## 表结构总览

```
┌─────────────────────────────────────────────────────────────┐
│                      SQLite (ai_ta.db)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  students                    course_modules                 │
│  ┌──────────────────┐       ┌──────────────────┐           │
│  │ id (PK)          │       │ id (PK)          │           │
│  │ username (UNIQUE) │       │ module_id (UNIQUE)│          │
│  │ display_name     │       │ course_id        │           │
│  │ persona          │       │ level            │           │
│  │ major            │       │ title            │           │
│  │ university       │       │ description      │           │
│  │ company          │       │ industry         │           │
│  │ job_title        │       │ difficulty       │           │
│  │ years_of_exp     │       │ prerequisites    │           │
│  │ target_role      │       │ estimated_hours  │           │
│  │ skill_level      │       │ lesson_count     │           │
│  │ enrolled_modules │       │ persona_target   │           │
│  │ career_paths     │       └──────────────────┘           │
│  │ created_at       │                                       │
│  │ updated_at       │       job_roles                      │
│  └──────────────────┘       │ role_id (UNIQUE) │           │
│         │                   │ title            │           │
│         │ 1:N               │ industry         │           │
│         ▼                   │ required_skills  │           │
│  ┌──────────────────┐       │ preferred_skills │           │
│  │ learning_progress │       │ salary_range     │           │
│  │──────────────────│       │ description      │           │
│  │ id (PK)          │       └──────────────────┘           │
│  │ student_id (FK)  │                                       │
│  │ module_id        │       skill_mapping                  │
│  │ lesson_id        │       ┌──────────────────┐           │
│  │ status           │       │ id (PK)          │           │
│  │ time_spent_mins  │       │ skill_name       │           │
│  │ source           │       │ role_id (FK)     │           │
│  │ last_accessed_at │       │ is_required      │           │
│  │ completed_at     │       │ module_id        │           │
│  │ notes            │       │ coverage_status  │           │
│  └──────────────────┘       └──────────────────┘           │
│         │                                                   │
│         │ 1:N                                               │
│         ▼                                                   │
│  ┌──────────────────┐                                       │
│  │ quiz_attempts     │       qa_history                     │
│  │──────────────────│       ┌──────────────────┐           │
│  │ id (PK)          │       │ id (PK)          │           │
│  │ student_id (FK)  │       │ student_id (FK)  │           │
│  │ module_id        │       │ question         │           │
│  │ quiz_id          │       │ answer           │           │
│  │ score            │       │ retrieved_docs   │           │
│  │ max_score        │       │ feedback         │           │
│  │ answers (JSON)   │       │ course_module    │           │
│  │ weak_areas (JSON)│       │ created_at       │           │
│  │ attempted_at     │       └──────────────────┘           │
│  └──────────────────┘                                       │
│                                                             │
│  interview_sessions         emotion_records                 │
│  ┌──────────────────┐       ┌──────────────────┐           │
│  │ id (PK)          │       │ id (PK)          │           │
│  │ student_id (FK)  │       │ student_id (FK)  │           │
│  │ job_role_id      │       │ state            │           │
│  │ questions (JSON) │       │ confidence       │           │
│  │ answers (JSON)   │       │ trigger          │           │
│  │ feedback (JSON)  │       │ context          │           │
│  │ score            │       │ created_at       │           │
│  │ offer_details    │       └──────────────────┘           │
│  │ created_at       │                                       │
│  └──────────────────┘                                       │
└─────────────────────────────────────────────────────────────┘
```

## 表关系

```
students 1──N learning_progress
students 1──N quiz_attempts
students 1──N qa_history
students 1──N interview_sessions
students 1──N emotion_records
course_modules（独立）
job_roles（独立）
skill_mapping（关联 job_roles ↔ course_modules）
```

## 会话线程设计

`qa_history` 表通过 `thread_id` 支持多会话窗口：

```
一个 student
  └── 多个 thread_id（会话窗口）
        └── 多条 qa_history 记录（消息）

thread_id = f"stu_{student_id}_{timestamp}"   ← 每次"新对话"新建一个
```

| 字段 | 说明 |
|------|------|
| `thread_id`（新增） | VARCHAR(128)，会话标识，同一次对话窗口内的所有消息共享 |
| `question` | 用户消息 |
| `answer` | Agent 回复 |

查询会话列表：`SELECT DISTINCT thread_id, MIN(question), MIN(created_at) FROM qa_history WHERE student_id=? GROUP BY thread_id ORDER BY MIN(created_at) DESC`

查询会话消息：`SELECT * FROM qa_history WHERE thread_id=? ORDER BY created_at ASC`

## 数据访问策略

**混合方式，需要时再抽象**：

| 场景 | 做法 |
|------|------|
| 简单查询（单表、主键、count） | 直接调 SQLAlchemy Session |
| 复杂查询（跨表聚合、多条件） | 封装 Repository 方法 |
| 测试 | SQLite 内存库 |

**需要封装的 Repository 方法**：
- `ProgressRepo.get_weak_areas(student_id)` — 跨 quiz_attempts 聚合 + 排序
- `JobMatchRepo.analyze_gap(student_id, role_id)` — 跨 3 表（进度 + 岗位 + skill_mapping）
- `RecommendRepo.get_next(student_id, count)` — 多条件排序 + 前置检查

## 课程目录与推荐数据

向量库（Milvus）索引**课时内容**，不负责「选哪门课」。推荐依赖 SQLite `course_modules`，由 `resources/courses/` 同步填充。

详见 [**课程目录与画像推荐**](course-catalog-recommend.md)（`sync_course_catalog`、画像写入、匹配规则）。

**Phase 1**：`sync_course_catalog()` 已写入 `course_modules`（课程级 + 章级）；`skill_mapping` / `job_roles` 仍为空（Phase 2）。
