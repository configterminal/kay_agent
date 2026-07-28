# Prompt 模块 — 多层组装架构

> 所有 Agent 的 System Prompt 由运行时组装，而非硬编码。

## 架构原则

参考 2025-2026 业界最佳实践，采用 **7 层脚手架模型**：

| 层 | 内容 | 文件 | 变更频率 |
|------|------|------|:--:|
| L1 | 身份与职责 | `qa.py` / `progress.py` / ... | 每 Agent 不同 |
| L2 | 操作原则 + **按需编号选项**（仅需选择时） | `shared.py` | 全局共享 |
| L3 | 安全与拒绝 | `shared.py` | 全局共享 |
| L4 | 注入防御 | `shared.py` | 全局共享 |
| L5 | 工具协议 | `shared.py` | 全局共享 |
| L6 | 输出与语气（导师人格） | `coach.py` | 运行时选择 |
| L7 | 运行时上下文（情绪策略） | `emotion.py` | 运行时动态注入 |

## 组装公式

```
build_system_prompt(role_prompt, coach_style, emotion) =
    shared_base (L2-L5)
    + coach_prompt (L6)
    + emotion_strategy (L7)
    + role_prompt (L1)
```

## 目录结构

```
src/agents/prompts/
├── __init__.py      # build_system_prompt() 组装函数
├── shared.py        # L2-L5：操作原则 + 安全 + 注入防御 + 工具协议
├── coach.py         # 4 种导师人格 Prompt
├── emotion.py       # 7 种情绪响应策略
├── qa.py            # QAAgent 专属
├── progress.py      # ProgressAgent 专属
├── recommend.py     # RecommendAgent 专属
├── jobmatch.py      # JobMatchAgent（课程覆盖匹配）
├── resume.py        # ResumeAgent（fact/target 双模式 + 定向呈现）
└── interview.py     # InterviewAgent（模拟面试）
```
