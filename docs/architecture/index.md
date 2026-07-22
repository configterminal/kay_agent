# 架构设计图

> 目录 | 最后更新：2026-07-21

- [**总体架构**](overview.md) — 分层、部署拓扑、主链路、实现状态（入口必读）
- [推理抽象层](inference-services.md) — Embedding / Rerank 可插拔（**默认 local**；http / algo）
- [配置中心](config.md) — 环境变量加载与全局配置
- [LLM 抽象层](llm.md) — 多模型统一接口与 Provider 注册
- [数据库](database.md) — SQLite 表结构、关系、数据访问策略
- [**课程目录与画像推荐**](course-catalog-recommend.md) — `course_modules` / 画像 / Recommend；岗位模板见 JobMatch
- [记忆系统](memory.md) — RedisSaver 短期 + Store 长期，**上下文预算（summaries + 近窗）**，情感分析策略
- [情感系统](emotion.md) — 7 种情绪实时检测，提示词策略，预警规则
- [RAG 系统](rag/index.md) — 传统 RAG 完整流水线（查询重写、混合检索、重排序、父子文档）
- [工具层](tools/qa.md) — Agent 工具定义与实现
- [Supervisor](agents/supervisor.md) — 层级调度主控，多意图混合模式，业务优先闲聊分流，证据驱动路由
- [QAAgent](agents/qa.md) — 智能答疑 Agent
- [ProgressAgent](agents/progress.md) — 进度追踪 Agent
- [JobMatchAgent](agents/jobmatch.md) — 课程覆盖匹配（MVP；非实时市场）
- [ResumeAgent](agents/resume.md) — 简历 fact/target 双模式 + 定向呈现 + 课练面闭环
- [InterviewAgent](agents/interview.md) — 模拟面试（文字 + 全屏语音场 P0）
- [模拟面试多模态](ui/interview-multimodal.md) — 全屏游戏态 / TTS 发现 / **Cosy 300M 试用通过**
- [简历 PDF 展示](ui/resume-pdf.md) — 优化终稿 A4 预览 / PDF 下载
- [输出 Schema](agents/schemas.md) — Agent 结构化输出定义
- [Prompt 模块](agents/prompts.md) — 多层 Prompt 组装架构
- [服务生命周期](service-lifecycle.md) — 启动加载、请求复用、关闭释放
- [**性能问题**](performance.md) — chat/简历延迟基线、双重检索与 Resume 串行 LLM、优化待办
- [**RAGAS 评测方案**](eval/ragas-plan.md) — 单轮/多轮作用域与 faithfulness（后续启用）
- [对话持久化](ui/conversation-persistence.md) — 聊天记录三层存储、前端 localStorage
- [答案跳转视频](ui/video-jump.md) — citations 从工具结果解析 → `/media` → 底部播放器 seek
- [**Chat 流式（SSE）**](ui/chat-stream.md) — `/api/chat/stream` 状态字 + token；`/chat/` 保留
