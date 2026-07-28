# 共享工具 (Supervisor 级)

所有子 Agent 和 Supervisor 均可使用的工具。

## 工具清单

```
get_student_profile(student_id: int) → dict
    学员完整画像 {persona, skill_level, career_paths, self_pick_modules, coach_style}

get_career_paths(student_id: int) → list[dict]
    所有职业线路 [{role_id, title, status, is_primary}]

switch_career_path(student_id: int, role_id: str) → dict
    切换主要方向 {success, message}

follow_career_path(student_id: int, role_id: str) → dict
    关注新线路，先给概述，确认后加 {success, message, overview}

archive_career_path(student_id: int, role_id: str) → dict
    放弃线路，保留已学记录 {success, message}

add_self_pick_module(student_id: int, module_id: str) → dict
    学员自选课程 {success, message}

get_self_pick_modules(student_id: int) → list[dict]
    零散课程列表 [{module_id, title, status}]

switch_coach_style(student_id: int, style: str) → dict
    切换导师人格 {success, message, new_style}
    触发词："切换人格"/"换风格"/"换个导师"

get_long_term_memory(student_id: int, key: str) → dict | None
    Redis Store 读

set_long_term_memory(student_id: int, key: str, value: dict) → bool
    Redis Store 写
```
