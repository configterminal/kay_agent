# 开发任务

> 最后更新：2026-07-27

## P0 — 阻塞上线

（当前无）

## P1 — 高优先级

### emotion-record — 情感数据落库与预警接入

- **状态**：待实现
- **来源**：文档-代码同步审计 (2026-07-27)
- **问题**：
  - `src/emotion/detector.py` 已完整实现 `record()`、`should_alert()`、`get_recent_trend()`
  - `src/agents/supervisor.py` `probe_node` 仅调用 `detect()` 检测情绪，从未调用 `record()` 将结果写入 `emotion_records` 表
  - `should_alert()` 和 `get_recent_trend()` 代码中无任何调用点
  - 预警逻辑不存在——情绪只是检测但既不存储也不触发任何行动
- **涉及文件**：
  - `src/emotion/detector.py` — 数据层已就绪
  - `src/agents/supervisor.py` — `probe_node` 需增加 `record()` + `should_alert()` 调用
  - `src/db/schema.py` — `EmotionRecord` 表已就绪
- **建议方案**：
  1. Supervisor `probe_node` 在 `detect()` 后调用 `record(session_id, result)`
  2. `record()` 后调用 `should_alert(session_id)` 判断是否触发预警
  3. 预警结果写入 response 的 `pending_options` 或独立告警通道
- **相关文档**：`.specify/specs/emotion.md`

### reflection-loop — Agent 反思循环（ResumeAgent 优先）

- **状态**：✅ 已完成 — ResumeAgent 已接入，Phase 2/3 待排期
- **来源**：质量观测需求 (2026-07-27)
- **提交**：`c6eb29d` (2026-07-27)
- **已实现**：
  - `src/agents/reflection.py` — `reflect_on_output()` + `build_reflection_cycle()`
  - ResumeAgent 路径接入，GENERATE → REFLECT → (REVISE → REFLECT)* 最多 3 轮
  - 5 维评分 + SSE status 事件（reflect/revise phase）
- **后续**：
  - Phase 2: QA / JobMatch 接入反思循环
  - Phase 3: Reflexion 长记忆（反思失败经验存入 Store）

### memory-topic-recall — 会话内话题回溯检索

- **状态**：方案设计中
- **来源**：记忆架构调研 (2026-07-27)
- **问题**：
  - 当前近窗裁剪是机械的（只看条数），用户跳回历史话题时细节丢失
  - 摘要粒度太粗，无法检索 "之前那个父子文档索引" 的完整上下文
- **方案**：Store 新增 `thread_blocks` 命名空间 + probe 节点语义检索历史对话块
- **相关文档**：待撰写

---

## P2 — 待优化

### performance-p0 — QA 双重检索 + 面试性能
- **状态**：待开始
- **来源**：`CLAUDE.md` 后续规划
- **内容**：QA 双重检索优化 + 面试 §9 余下（真麦 VAD / Avatar P1–P2）

### http-tei — HTTP TEI 生产化
- **状态**：待开始 (Windows CPU 镜像兼容性待完善)
- **来源**：`CLAUDE.md` 后续规划

### algo-bge-interceptor — algo 写入 BGE collection 运行时拦截
- **状态**：待开始
- **来源**：`CLAUDE.md` 后续规划

### build-index-lifespan — build_index() 接入 lifespan 自动触发
- **状态**：待开始（当前手动）
- **来源**：`CLAUDE.md` 待讨论

### format-output-retry — 格式化输出 + 错误重传
- **状态**：待开始
- **来源**：`CLAUDE.md` 待讨论

---

## 占位 / 探讨

### websearch — WebSearch 兜底接入
- **状态**：部分实现 — `resume_tools.py` 已有 DuckDuckGo `_web_search_snippets()`，但未作为通用工具开放
- **来源**：`CLAUDE.md` 待讨论

### dingtalk — 钉钉 SDK 接入
- **状态**：暂缓
- **来源**：`CLAUDE.md` 后续规划

### course-resources — 课程资源后续章节补充
- **状态**：待补充
- **来源**：`CLAUDE.md` 待讨论
