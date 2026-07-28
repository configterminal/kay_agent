# 对话持久化设计 (src/ui + src/api)

> 最后更新：2026-07-16 | 与 [记忆系统 · 上下文预算](../memory.md) 对齐

## 核心概念

一个会话（thread）= 一个对话窗口，包含多轮 Q&A。用户"新对话"创建新 thread。

```
qa_history 表

  thread_id = stu_1_20260715T120000
    ├── Q: "什么是RAG？"
    ├── A: "RAG是检索增强生成..."
    ├── Q: "能举个例吗？"
    └── A: "比如你可以用LangChain..."

  thread_id = stu_1_20260715T121500
    ├── Q: "我的学习进度"
    └── A: "你已完成3个模块..."
```

## 统一 thread_id（每会话独立）

前端、QAHistory、Checkpointer、`pending_options`、Store.`summaries.by_thread` **共用同一** `thread_id`（如 `stu_{student_id}_{timestamp}`）。

| 用途 | key | 管什么 |
|------|-----|--------|
| **Checkpointer** | 请求中的 `thread_id` | 该会话图状态 + 全量 messages（持久化，不进模型全量） |
| **QAHistory** | 同一 `thread_id` | 侧边栏列表与消息回放 |
| **Store.summaries** | `students:{id}:summaries` → `by_thread[tid]` | 该会话滚动摘要（进模型） |

> 已废弃：`Checkpointer = stu_{student_id}` 与归档 thread 分叉——会导致多会话串状态。

## 用户行为 → 对应逻辑

```
打开页面
  → 前端 从 localStorage 恢复上次 thread_id + messages
  → GET /api/conversations?student_id=N → 侧边栏显示会话列表
  → 若有上次 thread，切换并 GET .../state 恢复 pending_options

在当前窗口发消息
  → POST /api/chat/ { message, thread_id, selected_option_id? }
  → Checkpointer / QAHistory / 摘要均使用该 thread_id
  → 子 Agent 上下文 = summaries[thread] + 近窗（见 memory.md）

点击侧边栏某个会话
  → 切换 thread_id → 拉 messages + state（选项条）

点"新对话"
  → 新 thread_id = stu_{student_id}_{timestamp}
  → 空消息区；与旧会话状态完全隔离

删除会话
  → 删 QAHistory + checkpoint + summaries.by_thread[tid]
```

## 数据存储三层架构

```
┌─ 短期记忆（断点恢复用）──────────────────────┐
│  Redis Checkpointer                          │
│  thread_id: 与前端/归档相同（每会话独立）      │
│  存: 完整对话 messages + Agent 状态           │
│  管: LangGraph 框架自动读写                  │
└──────────────────────────────────────────────┘

┌─ 长期记忆（知识提炼 / 进模型）────────────────┐
│  RedisJSON Store                            │
│  students:{id}:summaries → by_thread[tid]  │
│  students:{id}:weak_areas / preferences    │
│  管: 业务代码（context.py 组 prompt）         │
└──────────────────────────────────────────────┘

┌─ 历史归档（会话列表 + 消息查询）────────────┐
│  SQLite qa_history 表                      │
│  关键字段: thread_id（会话标识）              │
│  按 thread_id 聚合 → 会话列表               │
│  按 thread_id 查询 → 会话内全部消息           │
└──────────────────────────────────────────────┘
```

## API 设计

### POST /api/chat/（已有，加 thread_id 参数）

```json
// 请求
{"student_id": 1, "message": "什么是RAG？", "thread_id": "stu_1_20260715T120000"}

// 响应（不变）
{"content": "RAG是...", "emotion": "neutral"}
```

后端行为：写入 `qa_history` 时带上 `thread_id`；Checkpointer 仍用 `stu_{student_id}`。

### GET /api/conversations?student_id=N

按 `thread_id` 聚合，返回会话列表（不是逐条 Q&A）：

```json
{
  "student_id": 1,
  "conversations": [
    {"thread_id": "stu_1_20260715T121500", "title": "我的学习进度", "created_at": "..."},
    {"thread_id": "stu_1_20260715T120000", "title": "什么是RAG？", "created_at": "..."}
  ]
}
```

### GET /api/conversations/{thread_id}/messages（新增）

返回某个会话下的全部消息：

```json
{
  "thread_id": "stu_1_20260715T120000",
  "messages": [
    {"id": 1, "role": "user", "content": "什么是RAG？", "created_at": "..."},
    {"id": 2, "role": "assistant", "content": "RAG是检索增强...", "created_at": "..."},
    {"id": 3, "role": "user", "content": "能举个例吗？", "created_at": "..."},
    {"id": 4, "role": "assistant", "content": "比如...", "created_at": "..."}
  ]
}
```

### DELETE /api/conversations/{thread_id}（新增）

删除整个会话及其所有消息：

```json
// 响应
{"success": true, "deleted": 3}  // 删除了 3 条 Q&A 记录
```

> 只会删除 QAHistory 归档；Checkpointer 的短期记忆不受影响。

## 前端状态管理

```
┌─ 会话列表（从 API 拉）──────────────────────┐
│  conversationList = ref([])                 │
│  onMounted → GET /api/conversations         │
│  "新对话"后 → 乐观插入新条目                  │
│  悬停会话 → 显示删除按钮 🗑️                  │
│  删除后 → 刷新列表 + 清理 localStorage        │
└─────────────────────────────────────────────┘

┌─ 当前 thread_id ────────────────────────────┐
│  currentThreadId = ref(localStorage恢复)     │
│  切换会话 → 更新 currentThreadId             │
│  发消息 → 带上 currentThreadId               │
└─────────────────────────────────────────────┘

┌─ 当前 thread 的消息 ───────────────────────┐
│  messages = ref([])                         │
│  切换到某 thread → GET thread/{id}/messages │
│  发消息 → 追加到 messages                    │
│  每条 messages 变化 → localStorage 写入      │
│  key: chat_messages_{currentThreadId}       │
└─────────────────────────────────────────────┘
```

## 数据库改动

`qa_history` 表新增 `thread_id` 字段：

```python
class QAHistory(Base):
    __tablename__ = "qa_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    thread_id = Column(String(128))      # ← 新增
    question = Column(Text)
    answer = Column(Text)
    ...
```

## 实现清单

| 层 | 文件 | 改动 |
|------|------|------|
| 数据库 | `src/db/schema.py` | QAHistory 加 thread_id 字段 |
| 后端 | `src/api/routes.py` | `/chat/` 接受 thread_id 并存入；`/conversations` 按 thread_id 聚合返回；新增 `/conversations/{thread_id}/messages` |
| 删除会话 | `DELETE /api/conversations/{thread_id}` | 删除该 thread 全部消息；前端清除 localStorage + 刷新列表 |
| 前端 | `src/ui/src/App.vue` | 管理 currentThreadId + localStorage 多 key + 删除逻辑 |
| 前端 | `src/ui/src/components/Sidebar.vue` | 显示按 thread 聚合的会话列表 + 悬停删除按钮 |
