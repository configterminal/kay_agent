# QAAgent — 智能答疑

```
┌─────────────────────────────────────────────────────────────┐
│                      QAAgent                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  System Prompt（多层组装）                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ L2-L5: shared.py  操作原则 + 安全 + 注入防御 + 工具协议│   │
│  │ L6:   coach.py    导师人格 Prompt                     │   │
│  │ L7:   emotion.py  情绪响应策略                         │   │
│  │ L1:   qa.py       答疑模块专属职责                      │   │
│  │                                                     │   │
│  │ 组装函数：build_system_prompt(role, coach, emotion)    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  工具：search_course_content,                                │
│        get_lesson_content, get_qa_history                    │
│                                                             │
│  实现：LangGraph create_react_agent                          │
│        纯文本输出，不需要 Pydantic Schema                     │
│                                                             │
│  视频跳转：不由本 Agent 结构化输出；                           │
│  编排层从 search_course_content 工具结果抽 citations          │
│  （见 ui/video-jump.md）                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 与 Supervisor 的交互

```
Supervisor route → QAAgent
    │
    ├── 接收：messages（包含学员问题 + 情绪标签 + CoachStyle）
    │
    ├── Agent.invoke()
    │     └── 内部调用工具 + LLM 生成回答
    │
    └── 返回：{"output": "自然语言回答"}
         → Supervisor 直接展示给学员
```

## 为什么不需要格式化输出

答疑的产出是自然语言，学员看的就是最终结果。不需要 Supervisor 再加工。结构化数据（分数、列表、匹配度）才需要 Schema。

## 答案跳转视频（与本 Agent 的边界）

- QAAgent **仍输出纯文本**；Prompt 不要求模型填写 `media_path` / 秒数。
- `search_course_content` 工具返回已含 `start_sec` / `media_path`；由 **编排出口** 解析本轮工具结果生成 `citations`，经 API 下发前端 seek。
- 详见 [答案跳转视频](../ui/video-jump.md)。
