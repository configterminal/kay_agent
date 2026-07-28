# Chat 流式输出（SSE）

> 状态：**已落地** | 最后更新：2026-07-21  
> 关联：[api.md](api.md) · [performance.md](../performance.md) · [overview.md](../overview.md)

## 1. 目标

整轮 chat 总时长仍约 9～11s，但体感改为：

1. **先出状态字**（检索 / 路由 / 作答中）— 避免首 1～3s 空白  
2. **再刷正文 token** — LLM 生成阶段边出边看  
3. **结束事件带齐元数据** — citations / options / resume 等与非流式一致  

非目标（本期不做）：

- 面试场 TTS 按 token 播报（仍整句合成；字幕可跟正文）  
- 取消中途请求（可后续加 `AbortController`）  
- 用假流式（跑完再按字吐）冒充加速  

## 2. 协议

### 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/` | **保留**：一次性 JSON（调试 / 面试 ChatBridge 可暂用） |
| POST | `/api/chat/stream` | **聊天主路径**：SSE |

请求体与 `/api/chat/` 相同（`ChatRequest`）。

响应：`Content-Type: text/event-stream`

### 事件类型

每条 SSE：`data: {json}\n\n`（不强制 `event:` 行，前端按 `type` 字段分支）。

| type | 时机 | 字段 |
|------|------|------|
| `status` | probe / decide / dispatch 等阶段 | `phase`, `detail`, `agent?` |
| `token` | 子 Agent / 闲聊 LLM 生成增量 | `text`（delta） |
| `done` | 整轮成功结束 | 与 `ChatResponse` 同构（`content` 为全文） |
| `error` | 失败 | `detail` |

`phase` 约定：

| phase | 文案示例 |
|-------|----------|
| `probe` | 正在理解问题… |
| `route` | 正在匹配助教… |
| `generate` | 正在作答… / 正在检索课程… |
| `cite` | 正在整理引文…（可选） |

### 示例流

```text
data: {"type":"status","phase":"probe","detail":"正在理解问题…"}

data: {"type":"status","phase":"route","detail":"正在匹配助教…"}

data: {"type":"status","phase":"generate","detail":"正在作答…","agent":"qa_agent"}

data: {"type":"token","text":"RAG"}

data: {"type":"token","text":" 是检索增强生成"}

data: {"type":"done","content":"RAG 是检索增强生成…","agent":"qa_agent","thread_id":"stu_1_…","citations":[…],"options":[],"emotion":"neutral",…}

```

## 3. 后端实现要点

```
POST /api/chat/stream
    │
    ├─ 校验学员（同 /chat/）
    ├─ StreamingResponse(text/event-stream)
    │     · ContextVar 注入 on_event 回调
    │     · 线程内 run_supervisor（与现网 Checkpointer 一致）
    │     · probe/decide/dispatch 发 status
    │     · _dispatch_to_agent：有回调时 agent.stream(messages)
    │       仅转发无 tool_call 的文本 delta → token
    │     · 闲聊 _llm_chitchat：model.stream → token
    │     · 结束后写 QAHistory + 发 done（含 normalize citations）
    └─ 异常 → error 事件后结束
```

约束：

- Checkpointer `thread_id` 与非流式相同  
- `done.content` 必须是最终全文（前端以 done 校准；token 仅加速展示）  
- 路由 structured LLM **不**向客户端吐 token（避免 JSON 碎片）  
- ReAct **工具轮**（含「我去查一下」+ tool_call）**不**吐 token；仅最终作答轮直播，避免正文错乱  

## 4. 前端实现要点

```
sendMessage
  → 推 user 气泡
  → 推 assistant 占位（content=""，streaming=true，statusDetail=…）
  → fetch /api/chat/stream，读 body.getReader()
  → status → 更新 statusDetail
  → token  → content += text（Markdown 边渲染）
  → done   → 写入 citations/options/agent，streaming=false
  → error  → 展示错误，streaming=false
```

- `isLoading`：流式过程中为 true（禁重复发送）  
- 有 token 后可隐藏三点 loading，改为气泡内光标/状态行  
- 面试 `sendInterviewTurn`：本期仍可走 `/api/chat/`（整句再 TTS）；后续可改为收齐 `done` 再播  

## 5. 验收

1. 普通问答：1～3s 内出现状态字 → 随后刷正文 → 结束出现可点 citations  
2. 与 `/api/chat/` 同题对比：`done` 字段齐全，总时长接近  
3. `logs/perf.log` 仍有 `api.chat.stream.total`（或复用 `api.chat.total` + `stream=1`）  
4. 刷新后 citations 可从 QAHistory / localStorage 恢复  

## 6. 与性能优化的关系

流式 **不减少** LLM/RAG 墙钟时间，只改善等待体验。  
吞吐优化仍见 [performance.md](../performance.md) P0（双重检索等）。
