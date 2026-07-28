# 记忆系统 (src/memory/)

> 状态：已落地（含上下文预算） | 最后更新：2026-07-16  
> **硬约束**：Checkpointer 可存全量历史；**进入 LLM / 子 Agent 的上下文必须按预算裁剪**。  
> Store.`summaries` 滚动摘要 + 近窗原文组 prompt；实现见 `src/memory/context.py`。

## 物理存储总览

两层记忆共享同一个 Redis Stack 实例，通过 key 前缀隔离：

```
Redis Stack (Docker: redis/redis-stack, 端口 6380)
│
├── langgraph:checkpoint:*        ← Checkpointer（框架自动管理）
│   ├── langgraph:checkpoint:{thread_id}
│   ├── langgraph:checkpoint:writes:{thread_id}
│   └── langgraph:checkpoint:pending:{thread_id}
│   存储格式: LangGraph 内部序列化（channel_values + channel_versions）
│
├── checkpoint:*                   ← Checkpointer 索引（RediSearch）
├── checkpoint_write:*             ← Checkpointer 索引（RediSearch）
│
└── students:*                     ← Store（业务代码管理）
    ├── students:{id}:weak_areas       → JSON
    ├── students:{id}:preferences      → JSON
    ├── students:{id}:knowledge        → JSON
    ├── students:{id}:summaries        → JSON
    ├── students:{id}:emotion          → JSON
    └── students:{id}:current_thread   → JSON
    存储格式: JSON 字符串（json.dumps）
```

## 逻辑架构

```
┌─────────────────────────────────────────────────────────────┐
│                      记忆系统（两层）                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │          Checkpointer（短期 — RedisSaver）           │   │
│  │                                                     │   │
│  │  每个会话一个 thread_id，自动保存：                    │   │
│  │  - 完整对话历史（messages）                           │   │
│  │  - Agent 执行状态（当前在哪个节点）                     │   │
│  │  - 工具调用结果                                        │   │
│  │                                                     │   │
│  │  Key 格式: langgraph:checkpoint:{thread_id}          │   │
│  │  管理方式: LangGraph 框架自动读写                     │   │
│  │                                                     │   │
│  │  特性：                                              │   │
│  │  - 断点恢复：中断后从上次位置继续                      │   │
│  │  - 同一 thread_id 关闭后回来能看到上次记录              │   │
│  │  - 支持 interrupt_before（高危操作前暂停）             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │        Store（长期 — MemoryStore）                     │   │
│  │                                                     │   │
│  │  Key 格式: students:{id}:{namespace}                 │   │
│  │  管理方式: 业务代码通过 MemoryStore 显式读写           │   │
│  │                                                     │   │
│  │  命名空间                    存储内容                 │   │
│  │  ─────────────────────────────────────               │   │
│  │  ["students",{id},"weak_areas"]  薄弱知识点 + 频次     │   │
│  │  ["students",{id},"preferences"] 学习偏好              │   │
│  │  ["students",{id},"knowledge"]   已掌握知识点图谱       │   │
│  │  ["students",{id},"summaries"]   会话滚动摘要（按 thread）│   │
│  │  ["students",{id},"emotion"]     上次会话结束时的情绪   │   │
│  │  ["students",{id},"current_thread"] 当前活跃 thread_id │   │
│  │                                                     │   │
│  │  特性：                                              │   │
│  │  - 跨会话持久化；summaries 内按 thread_id 分桶         │   │
│  │  - 用于构建 LLM context，不替代 Checkpointer 原文     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 两层记忆的职责边界

|                    | Checkpointer                   | Store                    |
| ------------------ | ------------------------------ | ------------------------ |
| **存什么**   | 原始对话流水账（可全量）       | 提炼后的结构化知识 + **摘要** |
| **谁写**     | LangGraph 框架自动             | 业务代码显式调用         |
| **谁读**     | 框架恢复状态；**业务裁剪后再用** | 业务代码（**构建 context**） |
| **生命周期** | 跟 thread_id（每会话独立）     | 跟 student_id（内含按 thread 的摘要） |
| **类比**     | 浏览器完整历史记录             | 笔记本「学到哪 / 聊过什么」 |

**简单说**：Checkpointer 是「聊过的原文」；Store 是「提炼后给模型看的笔记」。  
**禁止**：把 Checkpointer 全量 `messages` 原样塞进子 Agent。

## Checkpointer 断点恢复机制

### 核心设计

**调用方只传最新消息，Checkpointer 自动管理全量对话历史。**

```
┌─ 第 1 轮 ──────────────────────────────────────────────┐
│                                                         │
│  API: message="什么是 RAG？"                             │
│                                                         │
│  graph.invoke(                                          │
│      {"messages": [HumanMessage("什么是 RAG？")]},       │
│      config={"thread_id": "stu_1"}                      │
│  )                                                      │
│    │                                                     │
│    │  ① Checkpointer.get("stu_1") → 无历史              │
│    │     当前消息: [HumanMessage("什么是 RAG？")]         │
│    │                                                     │
│    │  ② probe → decide → dispatch                       │
│    │                                                     │
│    │     dispatch_node 返回:                              │
│    │       "messages": [AIMessage("RAG是...")],          │
│    │       "final_response": "RAG是..."                  │
│    │              │                                      │
│    │              ▼ add_messages 自动追加                 │
│    │      messages: [HumanMessage("什么是 RAG？"),       │
│    │                 AIMessage("RAG是...")]               │
│    │                                                     │
│    │  ③ Checkpointer.put("stu_1")                       │
│    │     保存完整 messages 到 Redis                       │
│    │                                                     │
│    ▼ 返回给调用方: final_response = "RAG是..."           │
└─────────────────────────────────────────────────────────┘

┌─ 第 2 轮 ──────────────────────────────────────────────┐
│                                                         │
│  API: message="它和传统搜索有什么区别？"                  │
│                                                         │
│  graph.invoke(                                          │
│      {"messages": [HumanMessage("它和传统搜索有什么区别？")]},│
│      config={"thread_id": "stu_1"}                      │
│  )                                                      │
│    │                                                     │
│    │  ① Checkpointer.get("stu_1") → 恢复历史             │
│    │     messages: [HumanMessage("什么是 RAG？"),        │
│    │                AIMessage("RAG是...")]                │
│    │     追加新消息:                                      │
│    │     messages: [HumanMessage("什么是 RAG？"),        │
│    │                AIMessage("RAG是..."),                │
│    │                HumanMessage("它和...")]             │
│    │                                                     │
│    │  ② probe → decide → dispatch                       │
│    │                                                     │
│    │     dispatch 组 Agent 输入（见「上下文预算」）：      │
│    │       Store.summaries[thread] + 近窗原文 + 本轮消息  │
│    │       → 能消解"它"=RAG，但不必塞全量历史              │
│    │                                                     │
│    │     dispatch_node 返回:                              │
│    │       "messages": [AIMessage("区别在于...")],       │
│    │       "final_response": "区别在于..."               │
│    │              │                                      │
│    │              ▼ add_messages 自动追加                 │
│    │      messages: [..., AIMessage("区别在于...")]      │
│    │                                                     │
│    │  ③ Checkpointer.put(thread_id)                     │
│    │     更新 checkpoint，原文历史可持续增长               │
│    │  ④ 若超近窗阈值 → 滚动更新 Store.summaries          │
│    │                                                     │
│    ▼ 返回给调用方: final_response = "区别在于..."        │
└─────────────────────────────────────────────────────────┘
```

**关键链路**：

```
dispatch 返回 AIMessage → add_messages 追加 → Checkpointer 持久化全量
        │
        └─→ 另：组 Agent prompt 时只用「摘要 + 近窗」（见下文）
```

如果 dispatch_node 不返回 `messages`，第 2 轮恢复出来的历史只有用户消息，近窗里也看不到助教说过什么，指代会失败。

### 对比：持久化 vs 进模型

```
持久化（Checkpointer / QAHistory / 前端）
═══════════════════════════════════════
全量 messages 按 thread_id 保存 → 侧边栏回放、断点恢复
调用方只传当前消息 + thread_id

进模型（路由 LLM / 子 Agent / 查询重写）
═══════════════════════════════════════
❌ 禁止：state.messages 全量原样传入
✅ 必须：Store.summaries[thread] + 最近 K 轮原文 + 结构化记忆
```

### thread_id 设计

```
thread_id = 前端生成，如 "stu_{student_id}_{timestamp}"
（与 QAHistory / Checkpointer / pending_options 共用同一 key）

含义：
  - 每个对话窗口独立 checkpoint 与摘要桶
  - 同一学员可有多个会话；会话间 Store 学员级字段（weak_areas 等）共享
  - 禁止再用 stu_{student_id} 把多会话揉成一个图状态
```

### Redis 存储结构（Checkpointer）

```
Redis 中 Checkpointer 存的 key 结构（langgraph-checkpoint-redis 自动管理）：

  langgraph:checkpoint:{thread_id}           ← 最新 checkpoint 数据
  langgraph:checkpoint:writes:{thread_id}    ← 待处理的 writes
  langgraph:checkpoint:pending:{thread_id}   ← 待处理的 sends

每次 graph.invoke() 后自动更新，无需业务代码操作。
```

### 节点实现规范

Checkpointer 的正确工作依赖于每个 node 正确返回增量值。SupervisorState 中 `messages` 字段使用了 `add_messages` reducer：

```python
messages: Annotated[list, add_messages]
```

`add_messages` 的作用：自动将 node 返回的新消息追加到历史，不会覆盖已有消息。

**每个生成回复的 node 必须在返回值中写入 AIMessage：**

```python
# ✅ 正确 — 返回 AIMessage，add_messages 自动追加
def dispatch_node(state: SupervisorState) -> dict:
    reply = _handle_chitchat(...)
    return {
        "messages": [AIMessage(content=reply)],
        "final_response": reply,
        ...
    }

# ❌ 错误 — 只有 final_response，messages 历史中没有 Agent 回复
def dispatch_node(state: SupervisorState) -> dict:
    return {
        "final_response": reply,
        ...
    }
```

**Checkpointer 存储规则**：

```
graph.invoke({"messages": [HumanMessage("什么是RAG？")]}, config)
  ↓
每个 node 返回增量:  {"messages": [...], ...}
  ↓ add_messages 自动追加
  ↓
Checkpointer 写入完整 messages:
  [HumanMessage("什么是RAG？"), ...中间消息..., AIMessage("RAG是...")]
```

如果 node 不返回 `messages`，Checkpointer 中就只有用户消息，Agent 不知道"自己说过什么"。

### 边界情况

| 场景                             | 行为                                                                          |
| -------------------------------- | ----------------------------------------------------------------------------- |
| Redis 不可用                     | `build_supervisor_graph()` 已有 try/except 兜底，退化到无 Checkpointer 模式 |
| 新学员首次对话                   | Checkpointer.get("stu_99") 返回空，从零开始                                   |
| 学员发送空消息                   | Checkpointer 同样保存，保持一致性                                             |
| 多次 graph.invoke 同一 thread_id | Checkpointer 原文持续追加；进模型上下文由预算裁剪，不随全量膨胀 |
| 摘要落后 / 生成失败 | 本轮仅用近窗原文降级；不阻塞主回复 |

---

## 上下文预算（接通 Store.summaries）

> 本节是对「长期记忆本来要做、却未应用」的补全：**摘要写入 + 组 prompt 读取**。

### 原则

1. **持久化 ≠ Prompt**：Checkpointer 全量存；LLM 只看预算内拼装结果  
2. **Store 构建 context**：`summaries` + `weak_areas` / `preferences` 等短字段  
3. **近窗保指代**：最近若干轮必须保留原文（含助教 AIMessage），否则「它 / 1 / 刚才」会断  
4. **按调用分级预算**：路由 < 查询重写 < 子 Agent（子 Agent 最重，也最需要裁剪）

### 组 prompt 公式

```
子 Agent 输入 messages ≈
  [可选 System 增补] 会话摘要（Store.summaries[thread_id].text）
  + 最近 RECENT_TURNS 轮原文（默认 5 轮 ≈ 10 条 Human/AI）
  + 本轮 HumanMessage（含选项改写后的 input）

路由 LLM：
  最近 3 轮原文即可（现有 [-6:] 可保留），一般不塞长摘要

RAG 查询重写：
  最近 2～4 轮原文做指代消解，不传全历史
```

建议默认常量（实现时落 `src/config.py` 或记忆模块常量）：

| 常量 | 建议值 | 含义 |
|------|--------|------|
| `RECENT_TURNS` | 5 | 近窗轮数（一轮 = 学员+助教） |
| `SUMMARY_TRIGGER_MESSAGES` | 12 | messages 条数超过此值则触发/更新摘要 |
| `SUMMARY_MAX_CHARS` | 800 | 单条会话摘要上限（字） |
| `TOOL_RESULT_MAX_CHARS` | 2000 | 单条工具结果进模型前截断 |

### 数据流

```
                    Checkpointer.messages（全量）
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
     条数 > SUMMARY_TRIGGER？            取末尾 RECENT_TURNS 轮
              │                               │
              ▼                               │
     LLM 滚动摘要（旧摘要+被挤出近窗的原文）    │
              │                               │
              ▼                               │
     Store.put summaries[thread_id]           │
              │                               │
              └───────────────┬───────────────┘
                              ▼
                    build_agent_context()
                    = 摘要文本 + 近窗 messages
                              │
                              ▼
                         子 Agent.invoke
```

### `summaries` 存储结构

Key：`students:{student_id}:summaries`（与现有命名空间一致）

```json
{
  "by_thread": {
    "stu_1_20260715T183000": {
      "text": "学员在问 RAG 基础；已讲检索增强与幻觉；倾向先学向量检索。",
      "source_message_count": 14,
      "updated_at": "2026-07-15T12:00:00+08:00"
    }
  }
}
```

- **按 thread 分桶**：与会话隔离一致，切换对话不串摘要  
- **滚动更新**：新摘要应覆盖「已被挤出近窗」的信息，并合并旧 `text`，避免只摘要最后一段  
- **跨会话总览**（可选，后期）：同 key 下增加 `cross_session` 字段，由多 thread 摘要再压缩；MVP 不做

### 读写时机

| 时机 | 动作 |
|------|------|
| `probe` 或 `dispatch` 前 | `get` 本 `thread_id` 摘要；与近窗一并组 context |
| `dispatch` 成功写回 AIMessage 后 | 若 `len(messages) >= SUMMARY_TRIGGER_MESSAGES` 且「未摘要条数」超出近窗 → 异步或同步更新摘要 |
| 删除会话 | 删除该 thread 的 checkpoint，并从 `summaries.by_thread` 去掉对应项 |

### 实现落点（已落地）

| 模块 | 职责 |
|------|------|
| `src/memory/context.py` | `build_agent_messages`、`maybe_update_thread_summary`、摘要读写/删除 |
| `src/config.py` → `ContextBudgetSettings` | 近窗轮数、摘要触发阈值、摘要字数上限 |
| `dispatch_node` / `_dispatch_to_agent` | 禁全量 history；组「摘要+近窗」；写回后滚动摘要 |
| `probe_node` | 读本 thread 摘要 → `conversation_summary` |
| 删除会话 API | 清 checkpoint + `summaries.by_thread[tid]` |
| Store `summaries` | 学员级 key + 按 thread 分桶 |

### 反模式

```
❌ dispatch 把 state["messages"] 全量传给子 Agent
❌ 用截断近窗却不写摘要 → 长对话丢失主题
❌ 摘要按 student 混写、不按 thread 分桶 → 多会话串台
❌ 为省事清空 Checkpointer 历史 → 前端回放/断点恢复坏掉
❌ 把 RAG 检索原文整页反复塞进多轮 messages 不截断
```

### 实现状态核对

| 设计点 | 状态 |
|--------|------|
| Checkpointer 全量持久化 | ✅ |
| Store.summaries 写入 | ✅ `maybe_update_thread_summary` |
| 组 prompt = 摘要 + 近窗 | ✅ `build_agent_messages` |
| probe 读 weak_areas + 摘要 | ✅ |
| 每会话 thread_id | ✅ |

## 情感分析策略

```
学员消息 → Supervisor
              │
              ├─→ 意图分析（路由到子 Agent）
              └─→ 情绪判断（同一个 LLM 调用，无额外成本）
              │
              ▼
         子 Agent 附带情绪标签，调整回复风格
              │
              ▼
         情绪写入 SQLite emotion_records（完整历史）
         最近一次快照写入 Redis Store（Cold Start 参考）
```

- **实时**：每条消息都分析，不存在滞后
- **零额外成本**：Supervisor 分析意图时顺带判断情绪
- **Cold Start**：Store 存上次会话最后情绪，下次打开第一条消息就会更新

## 环境配置

### Redis Stack 容器

记忆系统依赖 Redis Stack（Checkpointer + Store）。Windows 上通过 Docker Desktop 运行：

```powershell
docker run -d --name redis-stack -p 6380:6379 -p 8002:8001 redis/redis-stack:latest
```

| 端口映射         | 说明                                        |
| ---------------- | ------------------------------------------- |
| `-p 6380:6379` | Redis 服务端口，宿主 6380 → 容器 6379      |
| `-p 8002:8001` | RedisInsight Web UI，宿主 8002 → 容器 8001 |

> **注意**：使用 6380 而非默认的 6379，避免与 Windows 上可能存在的本地 Redis 服务冲突。

### 环境变量 (.env)

```
REDIS_HOST=localhost
REDIS_PORT=6380
REDIS_DB=0
```

## Store 长期记忆设计

### 技术选型

Store 基于 RedisJSON + RediSearch 实现结构化知识的存储和检索：

| 能力 | 技术 | 说明 |
|------|------|------|
| 数据存储 | RedisJSON (`JSON.SET` / `JSON.GET`) | JSON 结构化存储，支持字段级操作 |
| 全文搜索 | RediSearch (`FT.SEARCH`) | 对 JSON 字段建索引，支持全文搜索 |
| 语义搜索 | RediSearch + Embedding（后续） | 向量语义搜索，当前先做全文搜索 |

### 数据写入流程

```
业务代码
  │
  │  MemoryStore.put(["students", "123", "weak_areas"], {"hash_table": 3})
  │
  ▼
  MemoryStore._make_key(["students", "123", "weak_areas"]) → "students:123:weak_areas"
  │
  │  redis.json().set("students:123:weak_areas", "$", {...})
  │
  ▼
  RedisJSON 存储:  { "hash_table": 3 }
  │
  │  RediSearch 索引自动覆盖（PREFIX 匹配 "students:*"）
  │
  ▼
  可被 search() 检索
```

### 数据读取流程

```
业务代码
  │
  │  MemoryStore.get(["students", "123", "weak_areas"])
  │
  ▼
  redis.json().get("students:123:weak_areas")
  │
  ▼
  返回: {"hash_table": 3}
```

### 搜索流程

```
业务代码
  │
  │  MemoryStore.search("hash_table", "weak_areas")
  │
  ▼
  _ensure_index("weak_areas")   ← 幂等，索引不存在则创建
  │
  │  FT.CREATE idx:students:weak_areas
  │    ON JSON
  │    PREFIX 1 students:
  │    SCHEMA
  │      $.hash_table AS hash_table NUMERIC
  │      $.value AS value TEXT
  │      ...
  │
  ▼
  FT.SEARCH idx:students:weak_areas "hash_table"
  │
  ▼
  返回匹配结果列表
```

### 索引设计

每个 namespace 对应一个 RediSearch 索引，索引名格式：`idx:students:{namespace}`

```
students:{id}:weak_areas     → idx:students:weak_areas
students:{id}:preferences    → idx:students:preferences
students:{id}:knowledge      → idx:students:knowledge
students:{id}:summaries      → idx:students:summaries
students:{id}:emotion        → idx:students:emotion
```

索引 PREFIX 统一为 `students:`，同一个 namespace 的不同 student_id 共享一个索引。存储时 key 格式为 `students:{id}:{namespace}`，RediSearch 自动按前缀匹配。

### MemoryStore 完整接口

```
class MemoryStore:
    ── 基础操作（已实现，改用 RedisJSON）─
    get(keys: list[str]) → dict | None        # JSON.GET
    put(keys: list[str], data: dict)           # JSON.SET
    delete(keys: list[str])                    # JSON.DEL
    exists(keys: list[str]) → bool             # JSON.TYPE

    ── 搜索（待实现）──
    search(query: str, namespace: str)         # FT.SEARCH

    ── 批量操作（已实现）──
    get_all(pattern: str) → list[dict]         # SCAN + JSON.GET
    delete_all(pattern: str) → int             # SCAN + DEL
```
