# API 接口设计

> 前端 Vue 3 ↔ 后端 FastAPI 通信规范。无 Mock 数据，全部走真实数据源。

## 接口总览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/` | 发送消息，一次性返回（含 `citations`）；调试/面试可暂用 |
| POST | `/api/chat/stream` | **聊天主路径**：SSE 状态字 + token + done（见 [chat-stream.md](chat-stream.md)） |
| GET | `/media/{path}` | 只读课程 mp4（根目录 `resources/`，见 [video-jump.md](video-jump.md)） |
| GET | `/api/student/{id}` | 查询学员信息 |
| PUT | `/api/student/{id}` | 更新学员信息（人格切换等） |
| GET | `/api/conversations/{student_id}` | 历史对话列表 |
| GET | `/api/conversation/{thread_id}` | 加载某个对话 |

---

## POST /api/chat/

核心接口。前端只传 `student_id` + `message`；`coach_style` 由 Probe 从 Store 读取，`emotion` 仅在 Probe 检测一次并经 `run_supervisor` 返回。

### 请求

```json
{
  "message": "什么是RAG？",
  "student_id": 1
}
```

### 后端处理流程

```
1. SQLite students 表 → 校验学员存在
2. run_supervisor(graph, student_id, message)
   └─ probe：EmotionDetector.detect（全链路唯一）+ 向量探路 + Store
   └─ 本轮 QA 工具结果 → citations（编排出口解析，非 LLM 编造）
3. 用返回值填 ChatResponse（补 media_url；source/score = Top1 兼容）
```

### 响应

```json
{
  "content": "RAG是检索增强生成技术...",
  "source": "课程《RAG全栈技术》第2章 第2-3节 @1:05",
  "score": 0.95,
  "emotion": "neutral",
  "agent": "qa_agent",
  "thread_id": "stu_1_…",
  "options": [],
  "citations": [
    {
      "source": "课程…… @1:05",
      "score": 0.95,
      "section": "02-03",
      "title": "解锁RAG三大核心",
      "start_sec": 65,
      "end_sec": 110,
      "media_path": "courses/RAG101 …/02-03 ….mp4",
      "media_url": "/media/courses/RAG101%20…/02-03%20….mp4",
      "captions_url": "/captions/courses/RAG101%20…/02-03%20….vtt",
      "kp_title": "RAG三大核心的组成与作用",
      "kp_summary": "…",
      "kp_index": 0
    }
  ],
  "analogy_citations": []
}
```

> `source` / `score` 取 `citations[0]`，兼容旧前端。完整跳转设计见 [video-jump.md](video-jump.md)；类比区见 [course-scope](../rag/course-scope.md)。

### 错误响应

```json
{
  "error": "学员不存在",
  "detail": "student_id=999 未找到"
}
```

---

## GET /api/student/{id}

查询学员基本信息。

### 响应

```json
{
  "id": 1,
  "display_name": "张三",
  "persona": "university_student",
  "coach_style": "encouraging",
  "skill_level": "beginner",
  "target_role": "Python 后端开发"
}
```

---

## PUT /api/student/{id}

更新学员信息。

### 请求

```json
{
  "coach_style": "pushing"
}
```

### 响应

```json
{
  "success": true,
  "message": "已切换为严厉驱动型"
}
```

---

## GET /api/conversations/{student_id}

历史对话列表。

### 响应

```json
{
  "conversations": [
    {
      "thread_id": "student_1_session_20260714",
      "title": "RAG 概念讨论",
      "last_message": "什么是RAG的三大核心？",
      "updated_at": "2026-07-14T18:30:00"
    }
  ]
}
```

---

## GET /api/conversation/{thread_id}

加载指定对话的完整消息。

### 响应

```json
{
  "thread_id": "student_1_session_20260714",
  "messages": [
    {"role": "user", "content": "RAG是什么？", "timestamp": "..."},
    {"role": "assistant", "content": "RAG是...", "source": "...", "timestamp": "..."}
  ]
}
```

---

## 技术栈

| 层 | 选型 |
|------|------|
| 后端框架 | FastAPI |
| 异步支持 | uvicorn |
| CORS | fastapi.middleware.cors |
| 数据验证 | Pydantic v2 |
| 流式输出 | SSE（`POST /api/chat/stream`，见 [chat-stream.md](chat-stream.md)） |
