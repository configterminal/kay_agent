# 会话内话题回溯检索 (Thread Topic Recall)

> 设计文档 · 2026-07-27 · 状态：方案设计

## 1. 问题

当前上下文管理策略是"摘要 + 近窗"：

```
build_agent_messages(all_messages, task_input, summary_text):
  ├── SystemMessage(摘要)     ← 粗粒度压缩
  ├── 近窗消息 (最近 N 轮)    ← 机械裁剪
  └── HumanMessage(本轮问题)
```

用户跳回历史话题时（"之前你提到的父子文档索引，能再讲讲吗？"），
摘要太粗、近窗无此话题，模型只能泛泛回答。

## 2. 方案

### 2.1 核心思路

在 Store 新增 `thread_blocks` 命名空间，按主题分块存储对话历史。
probe 节点新增语义检索步骤，用户消息命中历史块时注入到上下文。

```
probe 节点（现有 3 步 → 新增第 4 步）:

  ① 向量探路 → probe_evidence
  ② 情绪检测 → emotion
  ③ Store 上下文读取 → coach_style + summary
  ④ 话题回溯检索 → 新增                          ← 本次实现
     用户消息 → Redis 全文搜索 thread_blocks
     → 命中 → 注入到 conversation_summary 之前
```

### 2.2 数据模型

```
Store: students:{id}:thread_blocks:{thread_id}

{
  "blocks": [
    {
      "block_id": "block_1",
      "start_msg_index": 0,
      "end_msg_index": 4,
      "topic": "RAG 基本概念与三大核心",
      "summary": "学员询问 RAG 全称和定义，助教解释了检索增强生成的三大核心组件：知识库、检索模块、大语言模型...",
      "created_at": "2026-07-27T10:00:00"
    },
    {
      "block_id": "block_2",
      "start_msg_index": 5,
      "end_msg_index": 8,
      "topic": "Embedding 详解",
      "summary": "学员追问 embedding 概念，助教讲解了向量嵌入的语义空间、稠密检索原理...",
      "created_at": "2026-07-27T10:05:00"
    }
  ]
}
```

**块粒度**：按消息主题自动切分，而非固定窗口。
触发时机：`maybe_update_thread_summary` 触发时同步写入块。

### 2.3 检索流程（工具化）

话题回溯不嵌入 probe 节点，而是作为**Agent 工具**按需调用。
Agent 自行判断是否需要检索历史话题，避免每轮都消耗 LLM + 检索资源。

```
QA Agent（其他 Agent 同理）:
  收到用户消息 → 判断是否引用历史话题
    │
    ├── 不需要 → 正常回答，无额外开销
    │
    └── 需要 → 调用 search_thread_blocks(query)
          │
          ├── 默认搜最近 10 个块
          ├── 命中 → 历史块内容注入上下文 → 精准回答
          └── 未命中 → 正常回答
```

**3 个工具**（注入 shared_tools，所有 Agent 共享）：
- `search_thread_blocks(query, top_k, time_range)` — 语义检索历史块
- `list_thread_topics()` — 列出当前会话所有话题标题
- `delete_thread_blocks(before_days)` — 删除历史块

**系统负载自适应**：
- 系统快 → Agent 正常调工具
- 系统慢 → Agent 可以不调，不影响主回复
- 用户说"把所有相关的都找出来" → time_range="all"

## 3. 实现

### 3.1 改动范围

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/memory/context.py` | 修改 | 新增 `save_thread_block()` + `search_thread_blocks_store()` 等 7 个函数 |
| `src/tools/shared_tools.py` | 修改 | 新增 3 个 @tool: search/list/delete thread blocks |
| `src/api/routes.py` | 修改 | 新增 2 个 GET 端点（历史报表用） |
| `src/api/schemas.py` | 修改 | 新增 4 个 Pydantic 模型 |
| `src/agents/supervisor.py` | 修改 | `dispatch_node` 新增块切分写入 |
| `src/ui/` | 新建/修改 | HistoryView + TopicCard + ThreadGroup + 路由 + 侧边栏 |

**probe 节点不动** — 话题检索由 Agent 工具按需触发。

### 3.2 核心函数

```python
# src/memory/context.py 新增

def save_thread_block(
    student_id: int,
    thread_id: str,
    topic: str,
    summary: str,
    start_msg_index: int,
    end_msg_index: int,
) -> str | None:
    """保存一个对话主题块到 Store。返回 block_id。"""

def search_thread_blocks(
    student_id: int,
    thread_id: str,
    query: str,
    top_k: int = 3,
) -> list[dict]:
    """
    语义检索历史对话块。
    优先 RediSearch FT.SEARCH → 回退关键词匹配。
    返回命中块的 summary 列表。
    """

def _should_trigger_recall(user_message: str, is_first_turn: bool) -> bool:
    """判断用户消息是否需要触发话题回溯。"""
```

### 3.3 probe_node 改动

```python
# src/agents/supervisor.py probe_node 新增步骤

# ④ 话题回溯检索
recall_context = ""
if thread_id and student_id:
    try:
        if _should_trigger_recall(last_user_msg, not has_history):
            from src.memory.context import search_thread_blocks
            hits = search_thread_blocks(student_id, thread_id, last_user_msg, top_k=2)
            if hits:
                recall_lines = []
                for h in hits:
                    recall_lines.append(f"[历史话题] {h['topic']}: {h['summary']}")
                recall_context = "\n".join(recall_lines)
                logger.info("话题回溯命中 %d 条", len(hits))
    except Exception as e:
        logger.warning("话题回溯失败: %s", e)
```

### 3.4 dispatch_node 改动

在 `maybe_update_thread_summary` 触发时同步写块：

```python
# 在现有 maybe_update_thread_summary 调用之后

from src.memory.context import save_thread_block
# 当 messages 累积超过阈值 + 看起来形成了新话题时
save_thread_block(student_id, thread_id, topic, block_summary, start_idx, end_idx)
```

**块切分策略**：简化首版——当全量 messages 超过 `summary_trigger_messages` 时，
把超出近窗的部分按固定窗口切块写入。后续可升级为 LLM 话题切分。

## 4. 验证

1. 发起一次多话题对话（RAG → embedding → 父子文档）
2. 切新对话，发"之前那个父子文档的再讲下"
3. 检查日志确认 `search_thread_blocks` 命中
4. 观察回答是否引用了历史块的详细内容

## 5. 不做的

- ❌ 不用向量检索（当前 RediSearch 全文索引即可，复杂度更低）
- ❌ 不做 LLM 话题切分（首版固定窗口+关键词触发）
- ❌ 不跨 thread 检索（只在本 thread 内回溯）
