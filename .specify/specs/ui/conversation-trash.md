# 对话垃圾桶 (Conversation Trash)

> 设计文档 · 2026-07-28 · 状态：方案设计

## 1. 问题

当前侧边栏删除对话是前端本地删除（只清 localStorage），数据仍存在于后端，
但没有统一的"已删除但可恢复"机制。用户需要：
- 侧边栏删对话 → 只是归档，不是真删
- 在历史报表页可以找回
- 在垃圾桶里可以彻底删除腾空间

## 2. 三层状态模型

```
活跃 (active) ──→ 垃圾桶 (trashed) ──→ 彻底删除 (purged)
  侧边栏可见         历史报表可见          不可恢复
  正常工作           灰色/划线样式
  删除→移入垃圾桶     可恢复→活跃
                    可彻底删除→永久消失
```

## 3. 实现

### 3.1 软删除标记

在 Store 中新增一个 key 记录已删除的 thread：

```
Store: students:{id}:trash

{
  "thread_ids": ["stu_1_xxx", "stu_1_yyy"],
  "trashed_at": {
    "stu_1_xxx": "2026-07-28T10:00:00",
    "stu_1_yyy": "2026-07-27T14:30:00"
  }
}
```

### 3.2 行为变化

| 操作 | 之前 | 之后 |
|------|------|------|
| 侧边栏删除 | 前端 localStorage 删除（后端数据仍存） | 后端标记为 trashed，侧边栏不显示 |
| 会话列表 API | 返回所有 thread | 默认过滤 trashed |
| 历史报表 API | 返回所有 thread | 返回所有（含 trashed），标注 `is_trashed` |
| 垃圾桶恢复 | 不存在 | 从 trash 列表移除 → 回到侧边栏 |
| 彻底删除 | 不存在 | 删除 thread_blocks + summary + trash 标记 |

### 3.3 新增 API

**PUT /api/threads/{thread_id}/trash?student_id={n}**
```json
// 请求
{ "action": "trash" | "restore" | "purge" }

// 响应
{ "ok": true, "action": "trash", "thread_id": "stu_1_xxx" }
```

- `trash`：标记为已删除
- `restore`：从垃圾桶恢复
- `purge`：彻底删除（thread_blocks + summary + trash 标记 + Checkpointer 状态）

### 3.4 现有 API 改动

**GET /api/conversations/?student_id={n}**
- 新增参数 `include_trashed=0|1`，默认 0（不显示垃圾桶）
- 侧边栏调用不加此参数 → 自动过滤

**GET /api/student/{student_id}/topics**
- 返回数据中每个 thread 新增 `is_trashed: bool` 字段
- 垃圾桶中的话题卡片用灰色样式

### 3.5 前端改动

**侧边栏 (Sidebar.vue)**：
- 删除按钮调用 `PUT /threads/{id}/trash action=trash`
- 删除后该对话从列表消失

**历史报表页 (HistoryView.vue)**：
- 每个 thread 组根据 `is_trashed` 显示不同样式（灰色/划线）
- 垃圾桶中的卡片加"恢复"按钮和"彻底删除"按钮
- "彻底删除"需要二次确认弹窗

### 3.6 数据流

```
侧边栏点删除
  → PUT /threads/{id}/trash {"action":"trash"}
  → Store 写入 students:{id}:trash
  → 侧边栏刷新列表（不显示该 thread）
  → 历史报表中该 thread 变为灰色

历史报表点恢复
  → PUT /threads/{id}/trash {"action":"restore"}
  → Store 从 trash 移除
  → 侧边栏重新显示该 thread
  → 卡片恢复正常样式

历史报表点彻底删除
  → 弹窗确认
  → PUT /threads/{id}/trash {"action":"purge"}
  → 删除 thread_blocks + summary + trash 标记
  → 从历史报表中消失
```

## 4. 改动范围

| 文件 | 改动 |
|------|------|
| `src/memory/context.py` | 新增 `trash_thread()` / `restore_thread()` / `purge_thread()` / `is_thread_trashed()` |
| `src/api/routes.py` | 新增 `PUT /threads/{id}/trash`；`GET /conversations/` 新增 `include_trashed` 参数；`GET /student/{id}/topics` 返回 `is_trashed` |
| `src/api/schemas.py` | `ThreadTopicSummary` 新增 `is_trashed` 字段 |
| `src/ui/src/components/Sidebar.vue` | 删除按钮调用 trash API |
| `src/ui/src/views/HistoryView.vue` | 垃圾桶样式 + 恢复/彻底删除按钮 |
| `src/ui/src/components/ThreadGroup.vue` | 透传 trash 状态 |

**纯后端改动为主，前端在已有页面上加交互。**

## 5. 验证

1. 侧边栏删除对话 → 侧边栏不显示 → 历史报表显示灰色
2. 历史报表点恢复 → 侧边栏重新显示 → 卡片恢复正常
3. 历史报表点彻底删除 → 弹窗确认 → 卡片消失
4. 刷新页面后状态持久（Store 存储）
