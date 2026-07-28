# ProgressAgent — 进度追踪

```
┌─────────────────────────────────────────────────────────────┐
│                    ProgressAgent                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  System Prompt（多层组装）                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ L2-L5: shared.py  操作原则 + 安全 + 注入防御 + 工具协议│   │
│  │ L6:   coach.py    导师人格 Prompt                     │   │
│  │ L7:   emotion.py  情绪响应策略                         │   │
│  │ L1:   progress.py 进度模块专属职责                      │   │
│  │                                                     │   │
│  │ 组装函数：build_system_prompt(role, coach, emotion)    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  工具：get_student_progress, get_quiz_history,              │
│        get_weak_areas, get_strong_areas,                   │
│        get_study_streak, generate_progress_report           │
│                                                             │
│  输出：自然语言（默认）或 ProgressReport（结构化请求时）       │
│        见 schemas.md                                        │
│                                                             │
│  实现：LangGraph create_react_agent                         │
```
