# 情感系统 (src/emotion/)

```
┌─────────────────────────────────────────────────────────────┐
│                emotion — 情感检测器                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  detector.py                                               │
│                                                             │
│  EmotionDetector                                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                     │   │
│  │  detect(text: str) → EmotionResult                   │   │
│  │     │                                               │   │
│  │     ├─→ 构建 Prompt（含 Few-Shot 示例）              │   │
│  │     ├─→ LLMProvider.analyze_emotion(text)            │   │
│  │     └─→ 返回 {state, confidence, evidence}           │   │
│  │                                                     │   │
│  │  get_recent_trend(student_id, minutes=60)             │   │
│  │     │                                               │   │
│  │     └─→ 从 SQLite emotion_records 查最近 1 小时情绪   │   │
│  │        返回趋势："持续焦虑" / "情绪好转" / "波动"     │   │
│  │                                                     │   │
│  │  should_alert(student_id) → bool                      │   │
│  │     │                                               │   │
│  │     └─→ 判断是否需要预警：                            │   │
│  │        - 连续 3 次以上 frustrated/anxious             │   │
│  │        - 连续 7 天 disengaged                        │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  数据流（情绪只检测一次）：                                   │
│                                                             │
│  学员消息 → POST /api/chat/                                 │
│     │                                                       │
│     ▼                                                       │
│  Supervisor.probe_node  ← 全链路唯一 EmotionDetector.detect │
│     ├─→ state.emotion / emotion_confidence                  │
│     ├─→ 情绪标签注入子 Agent Prompt（L7）                     │
│     └─→ run_supervisor 返回值带回 API → ChatResponse.emotion│
│                                                             │
│  禁止：routes 与 probe 各检一次（会双倍 DeepSeek 调用）        │
│  落库 emotion_records / should_alert：待接入（检测点仍为 Probe）│
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 调用约定

| 位置 | 是否调用 `detect` | 说明 |
|------|:-----------------:|------|
| `src/agents/supervisor.py` → `probe_node` | 是 | **唯一检测点** |
| `src/api/routes.py` | 否 | 从 `run_supervisor` 返回的 `emotion` 填响应 |
| 子 Agent / Prompt L7 | 否 | 只消费 `state.emotion` |

## 7 种情绪状态

| 情绪 | 含义 | Agent 响应策略 |
|------|------|------|
| `frustrated` | 对具体任务的挫败（代码跑不通、题目一直错） | 先安抚，降难度，给具体提示 |
| `bored` | 敷衍、跳过内容、不想继续当前任务 | 换讲法，加入互动或挑战 |
| `anxious` | 对自身能力或未来的担忧（怕学不会、怕找不到工作） | 安抚 + 小任务重建信心 |
| `confident` | 回答快速正确、主动要求挑战 | 加难度，给挑战 |
| `disengaged` | 长时间未学、缺乏动力 | 提醒鼓励，低门槛小目标 |
| `accomplished` | 完成目标或项目，主动分享成果 | 正向强化，推荐类似挑战 |
| `neutral` | 普通知识问答，无明显情绪 | 正常教学节奏 |

## 区分要点

- **frustrated vs anxious**：frustrated 针对具体任务（"这题太难了"），anxious 针对自身能力或未来（"我学不会"）。如不确定，选更接近的那个，confidence 给 0.5-0.7。
- **bored vs disengaged**：bored 是"这太简单没意思"（已有能力只是无趣），disengaged 是"没动力不想学"（放弃状态）。

## Prompt 策略

无 Few-Shot 示例，7 种情绪定义 + 区分要点直接写入 System Prompt。LLM 的阅读理解能力足以从简短描述中准确分类。

Prompt 实现位置：`src/llm/base.py` — `_build_emotion_prompt()`

## 导师人格适配

不同人格的导师对同一情绪有不同的回应策略。学员注册时选择偏好（可在学习过程中修改）。

| 人格 | 风格 | 适合学员 |
|------|------|------|
| `encouraging` | 温柔鼓励型 | 初学者、容易焦虑 |
| `pushing` | 严厉驱动型 | 自觉性差、需要鞭策 |
| `humorous` | 幽默风趣型 | 轻松学习、不喜欢说教 |
| `professional` | 专业简洁型 | 在职人员、时间紧 |

实现位置：`src/llm/base.py` — `CoachStyle` 枚举 + `get_coach_prompt()`。

Agent 的 System Prompt = 角色职责 + 人格 Prompt 片段。情绪分析结果不变，同一情绪不同人格给出不同回应。

| 条件 | 触发动作 |
|------|------|
| 连续 3 次 frustrated/anxious | Supervisor 主动询问"要不要换个方式？" |
| 连续 7 天 disengaged | 系统发送提醒消息 |
