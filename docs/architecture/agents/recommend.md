# RecommendAgent — 个性化推荐

> 目录数据与画像流水线：[课程目录与画像推荐](../course-catalog-recommend.md)

```
┌─────────────────────────────────────────────────────────────┐
│                   RecommendAgent                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  System Prompt（多层组装）                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ L2-L5: shared.py  操作原则 + 安全 + 注入防御 + 工具协议│   │
│  │ L6:   coach.py    导师人格 Prompt                     │   │
│  │ L7:   emotion.py  情绪响应策略                         │   │
│  │ L1:   recommend.py 推荐模块专属职责                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  专属职责：                                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 1. 现状分析                                          │   │
│  │    - 先肯定学员已有积累                               │   │
│  │    - 用市场数据展示成长空间                            │   │
│  │    - 把差距转化为可执行路线                            │   │
│  │    - 禁止贩卖焦虑（"不学就被淘汰"）                   │   │
│  │                                                      │   │
│  │ 2. 推荐下一课                                        │   │
│  │    - 基于学员画像 + 进度 + 薄弱点 + 目标岗位           │   │
│  │    - 每条推荐带理由和优先级                            │   │
│  │                                                      │   │
│  │ 3. 人群差异化                                        │   │
│  │    在校生：打好基础 → 尽早接企业实战项目               │   │
│  │    在职人员：直接实战 → 缺基础时最短路径补齐           │   │
│  │    共同目标：找到心仪工作                              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  工具：get_student_profile, update_student_profile*,         │
│        get_available_modules, get_next_recommendations,     │
│        get_prerequisite_modules                             │
│        * update_student_profile 见 catalog-recommend 设计   │
│                                                             │
│  输出 Schema：RecommendationResult                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## RecommendationResult Schema

```python
class Recommendation(BaseModel):
    module_id: str
    title: str
    reason: str                    # 为什么推荐
    priority: str                  # high / medium / low
    source: str                    # career_path / weak_area / self_pick_extension / skill_gap
    estimated_hours: int
    prerequisites_met: bool

class RecommendationResult(BaseModel):
    persona: str                   # university_student / working_professional
    current_summary: str           # 现状分析一句话
    recommendations: list[Recommendation]
```
