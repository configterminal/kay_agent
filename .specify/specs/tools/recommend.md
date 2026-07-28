# RecommendAgent 工具

> 数据依赖：[课程目录与画像推荐](../course-catalog-recommend.md) — `course_modules` 须先同步，画像须 `update_student_profile` 写入。

## 工具

```
get_student_profile(student_id) → dict
    读学员画像（推荐前必调）

update_student_profile(student_id, **fields) → dict
    部分更新 persona / skill_level / target_role 等（待实现）

get_available_modules(industry, skill_level, type=None) → list[dict]
    返回可选模块列表 [{module_id, title, difficulty, type, prerequisites, estimated_hours}]

get_next_recommendations(student_id, count=5) → list[dict]
    综合推荐 [{module_id, title, reason, priority, source}]
    source: career_path / self_pick_extension / weak_area / skill_gap

get_prerequisite_modules(module_id, student_id) → list[dict]
    前置模块及完成状态 [{module_id, title, completed}]
```

## 匹配输入

| 输入 | 来源 |
|------|------|
| 候选模块 | `course_modules`（catalog_sync） |
| 画像 | `students`（update_student_profile） |
| 进度 | `learning_progress` |
| 薄弱点 | `quiz_attempts.weak_areas` |
