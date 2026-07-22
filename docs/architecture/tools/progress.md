# ProgressAgent 工具

```
┌─────────────────────────────────────────────────────────────┐
│                 tools/progress_tools.py                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  get_student_progress(student_id: int) → dict                │
│       └── SQLite learning_progress 聚合查询                   │
│           返回 {total_lessons, completed, in_progress,        │
│                 completion_pct, modules}                     │
│                                                             │
│  get_quiz_history(student_id: int) → list[dict]               │
│       └── SQLite quiz_attempts 查询                           │
│           返回 [{module_id, quiz_id, score, max_score,        │
│                 weak_areas, attempted_at}]                   │
│                                                             │
│  get_weak_areas(student_id: int) → list[dict]                 │
│       └── 聚合 quiz_attempts.weak_areas，按频次降序           │
│           返回 [{topic, error_count}]                         │
│                                                             │
│  get_strong_areas(student_id: int) → list[dict]               │
│       └── 分析高分知识点                                      │
│           返回 [{topic, avg_score}]                           │
│                                                             │
│  get_study_streak(student_id: int) → dict                    │
│       └── 连续学习天数 + 懈怠检测                             │
│           返回 {current_streak, longest_streak,               │
│                 days_since_last}                             │
│                                                             │
│  generate_progress_report(student_id: int) → ProgressReport   │
│       └── 汇总以上 + LLM 归纳 → Pydantic 结构化报告           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
