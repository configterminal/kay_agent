# 性能问题与优化方向

> 状态：问题已记录，优化待做 | 最后更新：2026-07-17  
> 测量手段：`logs/perf.log`（`src/perf.py`）+ `/api/chat/` 端到端计时

## 1. 实测基线（2026-07-17）

| 场景 | 端到端 | 主要耗时段 |
|------|--------|------------|
| 普通问答「什么是 RAG？」 | **约 17s** | `qa_agent.invoke` ~11s；`qa.ensure_citations` 再跑一轮完整 RAG ~4s |
| 简历优化（ResumeAgent） | **约 128s～348s** | 多步工具链：brief → 联网信号 → feedback → optimize → review，每步 LLM |

典型 QA 明细（同一轮请求内）：

```
supervisor.probe.vector     ~0.3s
supervisor.decide.*         0～2s（确定性命中则无 LLM 路由）
rag.rewrite                 ~1.1s   ← Agent 内检索会跑
rag.hybrid + rerank         ~1.5s
rag.parent_expand           ~1.2s
supervisor.agent.invoke     ~11s    ← DeepSeek 生成占大头
qa.ensure_citations         ~3.7s   ← 又一轮 rewrite/hybrid/rerank/parent（与上重复）
api.chat.total              ~17s
```

结论：

- **检索本身不慢**（hybrid ~0.3s）；慢在 **LLM 轮次** 与 **重复流水线**。
- **简历慢是链路长度问题**，不是单次向量检索。

## 2. 已知瓶颈（按优先级）

### P0 — QA 双重检索

`dispatch` 层 `ensure_qa_citations`（`src/agents/citations.py`）在 Agent 已调用 `search_course_content` 后仍强制再 `retrieve` 一次。

- 现象：`tool_n=1` 时仍 `dispatch_n≥1`，`ensure_citations` ≈ 整轮 RAG。
- 预估收益：省 **约 3～4s**/问答轮。
- 方向：工具结果已有可用 citations 时跳过 dispatch 检索；仅追问/未调工具时补检索。

### P0 — Resume 多步串行 LLM

`optimize_resume_document` 等工具链内多次 `llm.invoke` + 可选 `ddgs` 联网。

- 现象：单次对话 2～6 分钟级。
- 方向（待定稿后改代码）：
  - 规则审核已通过则跳过 review LLM；
  - 合并 feedback / compose 为更少轮次；
  - 联网限时/可关；失败快速降级；
  - 前端长任务提示（避免误以为卡死）。

### P1 — 父子扩展与改写

- `rag.parent_expand` ~1.2s、`rag.rewrite` ~1.1s，在双重检索下各跑两遍。
- 方向：缓存同 query 的 rewrite；parent 批量查询优化。

### P2 — 路由 LLM

高置信确定性规则未命中时 `supervisor.decide.llm` ~2s。可继续收紧规则，减少不必要 LLM 路由。

## 3. 非目标（当前不因此降级）

- 不擅自把 RedisSaver 换成 MemorySaver。
- 不关闭 Rerank / 混合检索来「假加速」。
- HTTP TEI 仍为可选；默认 local GPU 路径保持。

## 4. 观测约定

- 应用启动调用 `setup_perf_logging()` → `logs/perf.log`。
- 关键标签标签：`api.chat.total`、`supervisor.invoke`、`supervisor.agent.invoke`、`qa.ensure_citations`、`rag.retrieve.total`。
- 优化前后用**同一问题 + 新 thread_id** 对比 `api.chat.total`。

## 5. 待办清单

> 与面试线并列时，优先做本清单 **P0（QA 双重检索）**——见 [interview-multimodal.md §9 包 E](ui/interview-multimodal.md)。

- [ ] QA：有工具 citations 时跳过二次 `retrieve`（**下一优先实现**）
- [ ] Resume：缩短 LLM 步数 + review 条件触发 + 联网超时
- [ ] RAG：rewrite / parent_expand 去重与缓存
- [ ] UI：长请求进度/可取消（尤其 Resume）
- [x] Chat SSE 流式（状态字 + token）：见 [ui/chat-stream.md](ui/chat-stream.md) — **改善体感，不减少墙钟**
- [ ] 观测：stream 路径打点 `api.chat.stream.total` / `stream.first_token`
- [ ] 复测并更新本节基线表
