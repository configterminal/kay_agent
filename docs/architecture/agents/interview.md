# InterviewAgent — 模拟面试

> 状态：**文字 + 全屏语音面试场 P0 已接通并联调** — 见 [interview-multimodal.md](../ui/interview-multimodal.md)  
> 最后更新：2026-07-17  
> 工具：[tools/interview.md](../tools/interview.md) · 上游种子：Resume `interview_focus` / JobMatch `role_id`

## 1. 定位

自然对话式模拟面试（不分「第 N 题」）：提问 → 追问 → 学员反问 → 模拟 Offer → 复盘。  
多模态（开麦 ASR / 面试官 TTS / 交流打断）在 **全屏 InterviewStage + speech Provider** 预处理，Agent 只吃文本。

## 2. 架构

```
学员 → Supervisor → InterviewAgent (ReAct)
         │
         ├── get_interview_questions(role_id, difficulty, count)
         ├── evaluate_answer(question, answer, role_id)   # 可后台，不堵追问
         ├── save_interview_session(...)
         └── generate_interview_report(session_id)
```

UI：聊天 CTA「进入面试」→ 全屏游戏态（Avatar P0 + Voice）；同 `thread_id`。  
Prompt：`shared` + coach + emotion + [`prompts/interview.py`](../../src/agents/prompts/interview.py)。  
`student_id` 由会话注入，禁止向学员追问。

## 3. 与 QA / Resume / JobMatch 边界

| 意图 | 路由 |
|------|------|
| 面试技巧 / 怎么答（课程知识） | `qa_agent` |
| 开始/进行模拟面试、出题练习 | `interview_agent` |
| 简历终稿 / interview_focus 种子 | `resume_agent` 产出 → 本 Agent 消费 |
| 岗位技能差距 | `jobmatch_agent` |

## 4. 实现状态

| 项 | 状态 |
|----|------|
| `build_interview_agent` + 工具 | **已接通** |
| Supervisor 移出 UNIMPLEMENTED | **已接通** |
| ASR/TTS API（SenseVoice + Edge） | **已就绪** |
| 全屏面试场（VAD / barge-in / TTS） | **P0 已联调** |
| 开发态 DEBUG 文字入口 | **已落地**（生产默认隐藏） |
| CosyVoice-300M sidecar | **本机试用通过**（非 MOCK；见 ui/interview-multimodal.md） |
| 真数字人 Avatar P1+ | 后期 |
| 云 ASR | 不做（本期） |
